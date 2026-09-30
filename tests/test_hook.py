"""U5 tests: ZCode hook adapter — injection (AE1), blocking (AE5), override.

Seams under test: hook.run_hook/main, cli off/on/status/index, and the ZCode
hook registration helper. pipeline.route is mocked (RouteSpy); the catalog is
a real small one in tmp_path, built like test_pipeline's. KTD4 invariants
asserted throughout: additionalContext never blocks (exit 0); blocking = exit
2 + reason on stderr naming `router off`; routing_enabled=false proceeds
unrouted with no output.
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router import cli, hook, pipeline  # noqa: E402
from router.catalog import Catalog  # noqa: E402
from router.config import RouterConfig  # noqa: E402
from router.jev import JevTimeoutError  # noqa: E402
from router.pipeline import RouteResult  # noqa: E402

PROMPT = "help me price our SaaS"
POINTER = "- [skill] Pricing Analysis — Price SaaS plans (/skills/pricing/SKILL.md)"
FINGERPRINT = "fp-test-1234"


# -- fixtures -------------------------------------------------------------------

def make_state(tmp_path, enabled=True, with_key=True):
    """Config TOML + populated catalog under tmp_path; (config_path, catalog_path)."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    cat = Catalog(state_dir / "catalog.db")
    cat.upsert(
        "skill",
        {"id": "pricing", "name": "Pricing Analysis",
         "description": "Price SaaS plans", "path": "/skills/pricing/SKILL.md"},
    )
    cat.db.execute(
        "INSERT INTO meta(key, value) VALUES('catalog_fingerprint', ?)",
        (FINGERPRINT,),
    )
    cat.db.commit()
    cat.close()

    lines = ["# router config (comment line must survive)"]
    if with_key:
        lines.append(f"routing_enabled = {str(enabled).lower()}")
    lines += [
        "timeout_ms = 30000",
        f'state_dir = "{state_dir}"',
        "",
        "[sources]",
        'skill_dirs = ["/tmp/skills"]',
    ]
    cfg = tmp_path / "router.toml"
    cfg.write_text("\n".join(lines) + "\n")
    return cfg, state_dir / "catalog.db"


def payload(prompt=PROMPT, transcript=None, session_id="s-1"):
    return json.dumps(
        {"prompt": prompt, "session_id": session_id,
         "transcript_path": str(transcript) if transcript else None}
    )


class RouteSpy:
    """Stand-in for pipeline.route: records states, returns canned or raises."""

    def __init__(self, result=None, exc=None):
        self.result = result or RouteResult(
            injections=[POINTER], verdicts={}, no_match=False
        )
        self.exc = exc
        self.calls = []

    def __call__(self, state, catalog, ask=None, worker_ceiling=6):
        self.calls.append(state)
        if self.exc:
            raise self.exc
        return self.result


# -- routing success path (AE1) ---------------------------------------------------

def test_payload_routes_to_additional_context(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(payload(), cfg)

    assert out.exit_code == 0
    assert out.additional_context == POINTER
    assert out.stderr_reason is None
    assert len(spy.calls) == 1
    assert PROMPT in spy.calls[0]


def test_missing_payload_fields_tolerated(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(json.dumps({"prompt": PROMPT}), cfg)

    assert out.exit_code == 0
    assert out.additional_context == POINTER


def test_state_includes_transcript_tail(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("\n".join(f"alpha-{i:02d}" for i in range(1, 11)) + "\n")
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(payload(transcript=transcript), cfg)

    assert out.exit_code == 0
    state = spy.calls[0]
    assert PROMPT in state
    assert "alpha-06" in state          # last-5 tail starts here
    assert "alpha-05" not in state      # older lines dropped


def test_prompt_state_redacted_before_pipeline(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    secret = "op://wxfehwvpffxvjvxpyep7wjdv2a/item/field/api_key"
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)

    hook.run_hook(payload(prompt=f"read {secret} then price"), cfg)

    state = spy.calls[0]
    assert "[REDACTED]" in state
    assert "op://" not in state


def test_main_prints_hook_json_ae1(monkeypatch, tmp_path, capsys):
    cfg, _ = make_state(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(payload()))
    monkeypatch.setattr(hook.pipeline, "route", RouteSpy())

    rc = hook.main(["--config", str(cfg)])

    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    hso = doc["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert hso["additionalContext"] == POINTER


def test_empty_injections_exit0_no_stdout(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    spy = RouteSpy(result=RouteResult(injections=[], verdicts={}, no_match=True))
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(payload(), cfg)

    assert out.exit_code == 0
    assert out.additional_context is None  # no_match: nothing printed, still exit 0


# -- blocking path (AE5, R9, KTD4) ---------------------------------------------

def test_jev_timeout_blocks_exit2(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    spy = RouteSpy(exc=JevTimeoutError("Jev API timed out after 30.000s"))
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(payload(), cfg)

    assert out.exit_code == 2
    assert out.additional_context is None
    assert out.stderr_reason.startswith("ROUTING BLOCKED:")
    assert "timed out" in out.stderr_reason
    assert "router off" in out.stderr_reason


def test_timeout_block_main_no_stdout(monkeypatch, tmp_path, capsys):
    cfg, _ = make_state(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(payload()))
    monkeypatch.setattr(
        hook.pipeline, "route",
        RouteSpy(exc=JevTimeoutError("Jev API timed out after 30.000s")),
    )

    rc = hook.main(["--config", str(cfg)])
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.out == ""                        # no additionalContext on block
    assert "ROUTING BLOCKED" in captured.err
    assert "router off" in captured.err


def test_router_exception_blocks_not_traceback(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    monkeypatch.setattr(hook.pipeline, "route", RouteSpy(exc=RuntimeError("boom")))

    out = hook.run_hook(payload(), cfg)  # returns an outcome; never raises

    assert out.exit_code == 2
    assert out.stderr_reason.startswith("ROUTING BLOCKED:")
    assert "RuntimeError" in out.stderr_reason
    assert "router off" in out.stderr_reason


def test_malformed_payload_fail_closed(tmp_path):
    cfg, _ = make_state(tmp_path)
    for bad in ('{"prompt": "unterminated', "[]"):
        out = hook.run_hook(bad, cfg)
        assert out.exit_code == 2, bad
        assert out.stderr_reason.startswith("ROUTING BLOCKED:")
        assert "router off" in out.stderr_reason


def test_missing_catalog_blocks(tmp_path):
    cfg, catalog_path = make_state(tmp_path)
    catalog_path.unlink()

    out = hook.run_hook(payload(), cfg)

    assert out.exit_code == 2
    assert out.stderr_reason.startswith("ROUTING BLOCKED:")
    assert "catalog" in out.stderr_reason


def test_missing_config_blocks(tmp_path):
    out = hook.run_hook(payload(), tmp_path / "nope.toml")

    assert out.exit_code == 2
    assert out.stderr_reason.startswith("ROUTING BLOCKED:")


# -- override: routing_enabled=false proceeds unrouted (KTD5) --------------------

def test_routing_disabled_proceeds_unrouted(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path, enabled=False)
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(payload(), cfg)

    assert out.exit_code == 0
    assert out.additional_context is None
    assert out.stderr_reason is None
    assert spy.calls == []  # pipeline never fires


def test_routing_disabled_main_no_output(monkeypatch, tmp_path, capsys):
    cfg, _ = make_state(tmp_path, enabled=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(payload()))

    rc = hook.main(["--config", str(cfg)])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""


# -- CLI: off/on/status/index roundtrip -------------------------------------------

def test_cli_status_off_on_roundtrip(tmp_path, capsys, monkeypatch):
    cfg, _ = make_state(tmp_path, enabled=True)

    assert cli.main(["--config", str(cfg), "status"]) == 0
    status = capsys.readouterr().out
    assert "routing enabled" in status
    assert FINGERPRINT in status
    assert "skill=1" in status

    # off: turns proceed unrouted
    assert cli.main(["--config", str(cfg), "off"]) == 0
    capsys.readouterr()
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)
    out = hook.run_hook(payload(), cfg)
    assert (out.exit_code, out.additional_context) == (0, None)
    assert spy.calls == []
    assert cli.main(["--config", str(cfg), "status"]) == 0
    assert "routing disabled" in capsys.readouterr().out

    # on: routing restored
    assert cli.main(["--config", str(cfg), "on"]) == 0
    capsys.readouterr()
    out = hook.run_hook(payload(), cfg)
    assert out.exit_code == 0
    assert out.additional_context == POINTER
    assert len(spy.calls) == 1

    # the flip preserved every other line and rewrote the key in place
    text = cfg.read_text()
    assert text.count("routing_enabled") == 1
    assert "# router config (comment line must survive)" in text
    assert 'skill_dirs = ["/tmp/skills"]' in text
    assert 'timeout_ms = 30000' in text


def test_cli_toggle_appends_when_key_absent(tmp_path, capsys):
    cfg, _ = make_state(tmp_path, with_key=False)

    assert cli.main(["--config", str(cfg), "off"]) == 0
    capsys.readouterr()
    assert RouterConfig.load(cfg).routing_enabled is False
    text = cfg.read_text()
    assert "routing_enabled = false" in text
    assert text.count("routing_enabled") == 1

    assert cli.main(["--config", str(cfg), "on"]) == 0
    capsys.readouterr()
    assert RouterConfig.load(cfg).routing_enabled is True
    assert cfg.read_text().count("routing_enabled") == 1


def test_cli_status_without_catalog(tmp_path, capsys):
    cfg, _ = make_state(tmp_path)
    (tmp_path / "state" / "catalog.db").unlink()

    assert cli.main(["--config", str(cfg), "status"]) == 0
    status = capsys.readouterr().out
    assert "routing enabled" in status
    assert "fingerprint none" in status


def test_cli_index_delegates(monkeypatch, tmp_path):
    cfg, _ = make_state(tmp_path)
    recorded = []
    monkeypatch.setattr(
        cli.indexer, "main", lambda argv: (recorded.append(argv), 0)[1]
    )

    assert cli.main(["--config", str(cfg), "index"]) == 0
    assert recorded == [["--config", str(cfg)]]

    assert cli.main(["--config", str(cfg), "index", "--verbose"]) == 0
    assert recorded[-1] == ["--config", str(cfg), "--verbose"]


# -- ZCode hook registration helper ----------------------------------------------

def test_print_zcode_hook_config(tmp_path, capsys):
    cfg, _ = make_state(tmp_path)
    config = RouterConfig.load(cfg)

    hook.print_zcode_hook_config(config, config_path=cfg)

    doc = json.loads(capsys.readouterr().out)
    entry = doc["hooks"]["events"]["UserPromptSubmit"][0]
    assert entry["command"] == f"python3 -m router.hook --config {cfg}"
    assert entry["timeoutMs"] == 45000  # >= Jev 30s timeout per KTD4

"""U11 tests: nightly judge — telemetry scan, Jev Score per routed turn,
tuning sidecar TOMLs, indexer merge, recreate-migration safety."""
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from router import judge
from router.catalog import Catalog
from router.config import RouterConfig
from router.indexer import run_index
from router.jev import JevError, Score
from router.memory import SessionMemory
from router.telemetry import append_turn

QID = "turn_outcome"


# -- helpers ---------------------------------------------------------------

def make_skill(root: Path, name: str, description: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n")
    return p


def make_cfg(tmp_path: Path, **kw) -> RouterConfig:
    skills = kw.pop("skills_root", None) or (tmp_path / "skills")
    skills.mkdir(parents=True, exist_ok=True)
    defaults = dict(
        skill_dirs=[str(skills)],
        vault_rules=[],
        brain_vaults=[],
        roster_path="",
        state_dir=str(tmp_path / "state"),
    )
    defaults.update(kw)
    return RouterConfig(**defaults)


def canned_ask(state: str, questions: dict, *args, **kwargs) -> dict:
    """Canned scorer: usage evidence drives the score (used -> high)."""
    assert QID in questions and questions[QID]["type"] == "score"
    if "referenced by later turns: yes" in state:
        return {QID: Score(score=0.9, confidence=0.9)}
    return {QID: Score(score=0.1, confidence=0.9)}


def build_catalog(cfg: RouterConfig) -> str:
    return run_index(cfg).fingerprint


def row_of(cfg: RouterConfig, table: str, rid: str) -> dict:
    cat = Catalog(cfg.state_path("catalog.db"))
    try:
        cols = [c[1] for c in cat.db.execute(f"PRAGMA table_info({table})")]
        rec = cat.db.execute(
            f"SELECT * FROM {table} WHERE id=?", (rid,)
        ).fetchone()
        assert rec is not None
        return dict(zip(cols, rec))
    finally:
        cat.close()


# -- 1. used-pointer turn scores higher than ignored ------------------------

def test_used_pointer_scores_higher_than_ignored(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "alpha", "alpha tool")
    make_skill(Path(cfg.skill_dirs[0]), "beta", "beta tool")
    build_catalog(cfg)
    mem = SessionMemory(cfg.state_dir)
    # session A: alpha injected, later turn references it -> used
    mem.record_turn("sessA", "start the alpha work", ["alpha"])
    mem.record_turn("sessA", "continue with alpha please", [])
    # session B: beta injected, later turns never reference it -> ignored
    mem.record_turn("sessB", "start the beta work", ["beta"])
    mem.record_turn("sessB", "totally unrelated weather chat", [])
    for sid in ("sessA", "sessB"):
        append_turn(cfg.state_dir, {"session": sid, "injection_count": 1})

    report = judge.run_judge(cfg, ask_fn=canned_ask, index_fn=lambda: None)

    assert report.turns_scored == 2          # one ask per routed (injected) turn
    assert report.ask_errors == 0
    assert report.stats["alpha"].avg_score == pytest.approx(0.9)
    assert report.stats["beta"].avg_score == pytest.approx(0.1)
    assert report.stats["alpha"].avg_score > report.stats["beta"].avg_score
    assert report.stats["beta"].used_n == 0 and report.stats["alpha"].used_n >= 1


def test_turns_without_injections_are_not_scored(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "alpha", "alpha tool")
    build_catalog(cfg)
    mem = SessionMemory(cfg.state_dir)
    mem.record_turn("s", "plain turn, nothing routed", [])
    append_turn(cfg.state_dir, {"session": "s", "injection_count": 0})

    calls = []

    def spy(state, questions, *a, **k):
        calls.append(state)
        return {QID: Score(score=0.5, confidence=0.5)}

    report = judge.run_judge(cfg, ask_fn=spy, index_fn=lambda: None)
    assert calls == [] and report.turns_scored == 0


# -- 2. judge writes a tuning file with rationale ----------------------------

def test_judge_writes_tuning_file_with_rationale(tmp_path):
    cfg = make_cfg(tmp_path)
    skills = Path(cfg.skill_dirs[0])
    make_skill(skills, "alpha", "alpha tool")
    make_skill(skills, "gamma", "gamma helper for deployments")
    build_catalog(cfg)
    mem = SessionMemory(cfg.state_dir)
    # gamma injected twice, never referenced by later prompts, low scores
    mem.record_turn("s", "please wire the webhook retries", ["gamma"])
    mem.record_turn("s", "now check the webhook queue depth", ["gamma"])
    mem.record_turn("s", "unrelated chatter about weather", [])
    for _ in range(2):
        append_turn(cfg.state_dir, {"session": "s", "injection_count": 1})

    report = judge.run_judge(cfg, ask_fn=canned_ask, index_fn=lambda: None)

    tuning_dir = cfg.state_path("tuning")
    assert {p.name for p in tuning_dir.glob("*.toml")} == {"gamma.toml"}
    data = tomllib.loads((tuning_dir / "gamma.toml").read_text())
    assert data["capability_id"] == "gamma"
    ov = data["override"]
    assert ov and all({"field", "old", "new", "rationale"} <= set(o) for o in ov)
    assert ov[0]["field"] == "trigger_terms"
    assert ov[0]["old"] == "gamma helper for deployments"  # catalog value
    assert "webhook" in ov[0]["new"] and ov[0]["new"] != ov[0]["old"]
    assert "webhook" not in ov[0]["old"]
    assert ov[0]["rationale"].strip()  # documented tuning
    # alpha was used + high score: no proposal, and the log records the change
    assert not (tuning_dir / "alpha.toml").exists()
    log = cfg.state_path("judge.log").read_text()
    assert "gamma" in log and "trigger_terms" in log
    assert len(report.proposals) == 1


# -- 3. no-telemetry night is a no-op ----------------------------------------

def test_no_telemetry_night_is_noop(tmp_path):
    cfg = make_cfg(tmp_path)  # no telemetry, no sessions

    def boom(state, questions, *a, **k):
        raise AssertionError("ask must not be called on a no-op night")

    index_calls = []

    report = judge.run_judge(
        cfg, ask_fn=boom, index_fn=lambda: index_calls.append(1)
    )
    assert report.turns_scored == 0
    assert report.proposals == []
    assert index_calls == []  # no rerun either: nothing changed
    assert not cfg.state_path("tuning").exists()


def test_ask_failure_is_logged_not_fatal(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "alpha", "alpha tool")
    build_catalog(cfg)
    mem = SessionMemory(cfg.state_dir)
    mem.record_turn("s", "start the alpha work", ["alpha"])
    mem.record_turn("s", "continue alpha", [])
    append_turn(cfg.state_dir, {"session": "s", "injection_count": 1})

    def failing(state, questions, *a, **k):
        raise JevError("Jev API HTTP 500")

    report = judge.run_judge(cfg, ask_fn=failing, index_fn=lambda: None)
    assert report.turns_scored == 0
    assert report.ask_errors == 1
    assert report.proposals == []


# -- 4. tuning merge applies field override at index time ---------------------

def test_tuning_merge_applies_override_at_index_time(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "delta", "delta does things")
    fp_plain = build_catalog(cfg)
    base = row_of(cfg, "skill", "delta")
    assert base["trigger_terms"] == "delta does things"  # source value

    tuning_dir = cfg.state_path("tuning")
    tuning_dir.mkdir(parents=True, exist_ok=True)
    (tuning_dir / "delta.toml").write_text(
        'capability_id = "delta"\n'
        "[[override]]\n"
        'field = "trigger_terms"\n'
        'old = "delta does things"\n'
        'new = "delta does things deploy webhook"\n'
        'rationale = "nightly judge: low usage"\n'
        "[[override]]\n"
        'field = "description"\n'
        'old = "delta does things"\n'
        'new = "delta does things (tuned)"\n'
        'rationale = "nightly judge: descriptor gap"\n'
        "[[override]]\n"
        'field = "trigger_terms"\n'
        'old = "stale source value"\n'
        'new = "must not apply"\n'
        'rationale = "old mismatch guard"\n'
    )
    result = run_index(cfg)

    tuned = row_of(cfg, "skill", "delta")
    assert tuned["trigger_terms"] == "delta does things deploy webhook"
    assert tuned["description"] == "delta does things (tuned)"
    assert "must not apply" not in tuned["trigger_terms"]  # old-mismatch skipped
    assert result.fingerprint != fp_plain  # tuning changes the fingerprint


# -- 5. recreate migration never loses tuning --------------------------------

def test_recreate_migration_never_loses_tuning(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "delta", "delta does things")
    cfg.state_path("tuning").mkdir(parents=True, exist_ok=True)
    (cfg.state_path("tuning") / "delta.toml").write_text(
        'capability_id = "delta"\n'
        "[[override]]\n"
        'field = "trigger_terms"\n'
        'old = "delta does things"\n'
        'new = "delta does things tuned"\n'
        'rationale = "nightly judge"\n'
    )
    run_index(cfg)
    assert row_of(cfg, "skill", "delta")["trigger_terms"].endswith("tuned")

    # recreate migration: catalog rebuilt from scratch (derived-only)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(cfg.state_path("catalog.db")) + suffix)
        if p.exists():
            p.unlink()
    run_index(cfg)
    assert row_of(cfg, "skill", "delta")["trigger_terms"] == (
        "delta does things tuned"
    )


# -- 6. judge reruns the index after writing tuning ---------------------------

def test_judge_reruns_index_after_proposals(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "gamma", "gamma helper for deployments")
    build_catalog(cfg)
    mem = SessionMemory(cfg.state_dir)
    mem.record_turn("s", "please wire the webhook retries", ["gamma"])
    mem.record_turn("s", "check the webhook queue", ["gamma"])
    for _ in range(2):
        append_turn(cfg.state_dir, {"session": "s", "injection_count": 1})

    index_calls = []
    report = judge.run_judge(
        cfg, ask_fn=canned_ask, index_fn=lambda: index_calls.append(1)
    )
    assert report.proposals and index_calls == [1]


def test_full_loop_proposal_lands_in_catalog(tmp_path):
    cfg = make_cfg(tmp_path)
    make_skill(Path(cfg.skill_dirs[0]), "gamma", "gamma helper for deployments")
    build_catalog(cfg)
    mem = SessionMemory(cfg.state_dir)
    mem.record_turn("s", "please wire the webhook retries", ["gamma"])
    mem.record_turn("s", "check the webhook queue", ["gamma"])
    for _ in range(2):
        append_turn(cfg.state_dir, {"session": "s", "injection_count": 1})

    judge.run_judge(cfg, ask_fn=canned_ask)  # default index_fn: real rerun
    tuned = row_of(cfg, "skill", "gamma")
    assert "webhook" in tuned["trigger_terms"]


# -- 7. CLI contract -----------------------------------------------------------

def test_main_accepts_config_flag(tmp_path, capsys):
    cfg_path = tmp_path / "router.toml"
    cfg_path.write_text(
        f'state_dir = "{tmp_path / "state"}"\n'
        f'skill_dirs = ["{tmp_path / "skills"}"]\n'
    )
    rc = judge.main(["--config", str(cfg_path)])
    assert rc == 0
    assert "scored 0" in capsys.readouterr().out  # no-op night summary

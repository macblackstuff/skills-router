"""U10 tests: per-turn telemetry + golden-set evals (KTD10, R11).

Seams under test: telemetry.append_turn + the single hook.py wiring call;
evals.load_golden/load_baseline (partition contract), run_router (mock ask
injected; real jev.ask only when --live), hit_at_k (majority-of-3 via
thresholds.resample), evaluate/score_baseline, sweep (calibration partition
ONLY — no holdout prompt is ever routed by the sweep), report (router-vs-
baseline markdown rows), and the evals CLI.

Golden expected ids are QUALIFIED router ids ("skill:pricing") — the same
format pipeline verdicts and gate survivors use (test_pipeline asserts
verdicts["gate"]["survivors"] == ["skill:pricing"]).
"""
import copy
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router import evals, hook, telemetry  # noqa: E402
from router.catalog import Catalog  # noqa: E402
from router.caches import prompt_fingerprint  # noqa: E402
from router.indexer import pack_shards  # noqa: E402
from router.jev import Choice, Noul  # noqa: E402
from router.pipeline import RouteResult  # noqa: E402
from router.thresholds import resample  # noqa: E402

PROMPT = "help me price our SaaS"
POINTER = "- [skill] Pricing Analysis — Price SaaS plans (/skills/pricing/SKILL.md)"


# -- fixtures -------------------------------------------------------------------

def build_catalog(db_path, rows, budget_tokens=3000):
    """Real catalog with indexer-packed shards (same shape as test_pipeline)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cat = Catalog(db_path)
    for r in rows:
        cat.upsert("skill", r)
    packed = pack_shards([dict(r) for r in rows], budget_tokens=budget_tokens)
    cat.db.execute(
        "INSERT INTO meta(key, value) VALUES('shards:skill', ?)",
        (json.dumps(packed),),
    )
    cat.db.commit()
    return cat


def small_rows():
    return [
        {"id": "pricing", "name": "Pricing Analysis",
         "description": "Price SaaS plans", "path": "/skills/pricing/SKILL.md"},
        {"id": "cold-email", "name": "Cold Email",
         "description": "Write cold outbound emails", "path": "/skills/cold-email/SKILL.md"},
    ]


def wide_rows(n=20):
    """Long descriptors so a small shard budget really forces multiple shards."""
    return [
        {"id": f"cap-{i:02d}", "name": f"Cap {i:02d}",
         "description": (
             f"Analyze pricing caps for enterprise deal {i:02d} in region with "
             "volume discounts and multi-year renewals plus procurement rules"
         ),
         "path": f"/skills/cap-{i:02d}/SKILL.md"}
        for i in range(n)
    ]


class RoutedAsk:
    """Mock ask that routes each prompt to its scripted ids, else no-match.

    Records every call as {state, questions}. One route() fires several ask
    calls (triage, fan workers, gate) whose states grow candidate text, so
    the BARE prompt is the triage call's state — triage_states is what the
    partition-contract assertions use: no holdout prompt may ever be routed
    by the sweep.
    """

    def __init__(self, script=None):
        self.script = dict(script or {})
        self.calls = []

    @property
    def states(self):
        return [c["state"] for c in self.calls]

    @property
    def triage_states(self):
        return [
            c["state"] for c in self.calls
            if any(q.startswith("triage_") for q in c["questions"])
        ]

    def __call__(self, state, questions, **kwargs):
        self.calls.append({"state": state, "questions": copy.deepcopy(questions)})
        expected = self.script.get(state, [])
        answers = {}
        for qid, spec in questions.items():
            if qid.startswith("triage_"):
                answers[qid] = Noul(p=0.99 if expected else 0.0)
            elif qid.startswith("recall_"):
                pick = next((c for c in spec["criteria"] if c in expected), "none")
                answers[qid] = Choice(choice=pick,
                                      probabilities={pick: 0.97}, confidence=0.97)
            elif qid == "gate_inject":
                pick = next((c for c in spec["criteria"] if c != "none"), "none")
                answers[qid] = Choice(choice=pick,
                                      probabilities={pick: 0.98}, confidence=0.98)
            elif qid == "gate_capture":
                answers[qid] = Noul(p=0.0)
            else:  # pragma: no cover
                raise AssertionError(f"unexpected question id {qid!r}")
        return answers


def golden_file(tmp_path, entries):
    p = tmp_path / "golden.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return p


def baseline_file(tmp_path, rows):
    p = tmp_path / "baseline.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def make_state(tmp_path, rows):
    """Config TOML + indexed catalog under tmp_path; (config_path, state_dir)."""
    cfg, state_dir = tmp_path / "router.toml", tmp_path / "state"
    cat = build_catalog(state_dir / "catalog.db", rows)
    cat.close()
    cfg.write_text(f'state_dir = "{state_dir}"\n')
    return cfg, state_dir


def hook_payload(prompt=PROMPT, session_id="s-1"):
    return json.dumps({"prompt": prompt, "session_id": session_id})


class RouteSpy:
    def __init__(self, result=None):
        self.result = result or RouteResult(
            injections=[POINTER], verdicts={"gate": {"survivors": ["skill:pricing"]}},
            no_match=False,
        )
        self.calls = []

    def __call__(self, state, catalog, ask=None, worker_ceiling=6):
        self.calls.append(state)
        return self.result


# -- telemetry.append_turn --------------------------------------------------------

TELEMETRY_ENTRY = {
    "session": "s-1",
    "prompt_fingerprint": "fp" * 32,
    "latency_ms": 42,
    "cost_usd": 0.0005,
    "injection_count": 2,
    "cache_hit": False,
    "verdicts_digest": "vd" * 32,
}

FIELDS = ("ts", "session", "prompt_fingerprint", "latency_ms", "cost_usd",
          "injection_count", "cache_hit", "verdicts_digest")


def test_append_turn_writes_full_schema_line(tmp_path):
    state_dir = tmp_path / "state"

    record = telemetry.append_turn(state_dir, dict(TELEMETRY_ENTRY))

    assert record is not None
    lines = (state_dir / "telemetry" / "turns.jsonl").read_text().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    for field in FIELDS:
        assert field in doc, field
    for field in TELEMETRY_ENTRY:
        assert doc[field] == TELEMETRY_ENTRY[field]
    assert isinstance(doc["ts"], str) and doc["ts"]  # iso-8601, filled by the writer


def test_append_turn_creates_missing_dirs_and_appends(tmp_path):
    state_dir = tmp_path / "deep" / "nested" / "state"
    telemetry.append_turn(state_dir, dict(TELEMETRY_ENTRY))
    telemetry.append_turn(state_dir, dict(TELEMETRY_ENTRY, session="s-2"))

    lines = telemetry.turns_path(state_dir).read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["session"] == "s-2"


def test_append_turn_respects_caller_ts(tmp_path):
    record = telemetry.append_turn(tmp_path, {"ts": "2026-09-30T00:00:00+00:00"})
    assert record["ts"] == "2026-09-30T00:00:00+00:00"


def test_append_turn_never_raises_returns_none_on_failure(tmp_path, monkeypatch):
    # a NUL byte in the filename makes every open() raise — the write must be
    # swallowed (routing already succeeded), not propagated into the hook.
    monkeypatch.setattr(telemetry, "TURNS_REL", ("telemetry", "tu\0rns.jsonl"))

    assert telemetry.append_turn(tmp_path, dict(TELEMETRY_ENTRY)) is None


def test_digest_canonical_and_sensitive():
    assert telemetry.digest({"a": 1, "b": 2}) == telemetry.digest({"b": 2, "a": 1})
    assert telemetry.digest({"a": 1, "b": 2}) != telemetry.digest({"a": 2, "b": 1})


# -- hook.py wiring: telemetry on the success path --------------------------------

def test_hook_success_appends_telemetry_after_route(monkeypatch, tmp_path):
    cfg, state_dir = make_state(tmp_path, small_rows())
    spy = RouteSpy()
    monkeypatch.setattr(hook.pipeline, "route", spy)

    out = hook.run_hook(hook_payload(), cfg)

    assert out.exit_code == 0 and out.additional_context == POINTER
    lines = telemetry.turns_path(state_dir).read_text().splitlines()
    assert len(lines) == 1  # exactly one line per routed turn
    doc = json.loads(lines[0])
    assert doc["session"] == "s-1"
    assert doc["prompt_fingerprint"] == prompt_fingerprint(PROMPT)
    assert doc["injection_count"] == 1
    assert doc["cache_hit"] is False
    assert doc["verdicts_digest"] == telemetry.digest(spy.result.verdicts)
    assert isinstance(doc["latency_ms"], int) and doc["latency_ms"] >= 0
    assert isinstance(doc["cost_usd"], (int, float))


def test_hook_no_match_still_records_telemetry(monkeypatch, tmp_path):
    cfg, state_dir = make_state(tmp_path, small_rows())
    empty = RouteResult(injections=[], verdicts={"triage": {}}, no_match=True)
    monkeypatch.setattr(hook.pipeline, "route", RouteSpy(result=empty))

    out = hook.run_hook(hook_payload(), cfg)

    assert out.exit_code == 0 and out.additional_context is None
    doc = json.loads(telemetry.turns_path(state_dir).read_text().splitlines()[0])
    assert doc["injection_count"] == 0


def test_hook_telemetry_failure_does_not_break_the_turn(monkeypatch, tmp_path):
    cfg, _state_dir = make_state(tmp_path, small_rows())
    monkeypatch.setattr(hook.pipeline, "route", RouteSpy())
    # NUL byte in the target filename makes every write raise — the hook must
    # still succeed because append_turn swallows the failure (KTD11).
    monkeypatch.setattr(telemetry, "TURNS_REL", ("telemetry", "bad\0name.jsonl"))

    out = hook.run_hook(hook_payload(), cfg)

    assert out.exit_code == 0
    assert out.additional_context == POINTER


def test_hook_disabled_or_blocked_writes_no_telemetry(monkeypatch, tmp_path):
    cfg, state_dir = make_state(tmp_path, small_rows())
    # disabled: route never fires, no telemetry line
    cfg.write_text(f'state_dir = "{state_dir}"\nrouting_enabled = false\n')
    monkeypatch.setattr(hook.pipeline, "route", RouteSpy())
    hook.run_hook(hook_payload(), cfg)
    assert not telemetry.turns_path(state_dir).exists()


# -- golden / baseline loading ----------------------------------------------------

def test_seeded_golden_file_is_24_entries_12_12():
    entries = evals.load_golden(evals.DEFAULT_GOLDEN)

    assert len(entries) == 24
    assert sum(e.partition == "calib" for e in entries) == 12
    assert sum(e.partition == "holdout" for e in entries) == 12
    assert len({e.prompt for e in entries}) == 24  # unique prompts
    for e in entries:
        assert e.prompt and e.expected  # every entry routable and scorable


def test_seeded_baseline_covers_every_golden_prompt():
    entries = evals.load_golden(evals.DEFAULT_GOLDEN)
    baseline = evals.load_baseline(evals.DEFAULT_BASELINE)

    missing = [e.prompt for e in entries if e.prompt not in baseline]
    assert missing == []
    for picks in baseline.values():
        assert isinstance(picks, tuple) and all(isinstance(p, str) for p in picks)


def test_load_golden_rejects_unknown_partition(tmp_path):
    p = golden_file(tmp_path, [
        {"id": "a", "prompt": "one", "expected": ["skill:pricing"], "partition": "calib"},
        {"id": "b", "prompt": "two", "expected": ["skill:pricing"], "partition": "train"},
    ])
    with pytest.raises(evals.EvalError, match="line 2"):
        evals.load_golden(p)


def test_load_golden_rejects_missing_or_empty_expected(tmp_path):
    p = golden_file(tmp_path, [{"id": "a", "prompt": "one", "partition": "calib"}])
    with pytest.raises(evals.EvalError, match="line 1"):
        evals.load_golden(p)

    p2 = golden_file(tmp_path, [
        {"id": "a", "prompt": "one", "expected": [], "partition": "calib"}])
    with pytest.raises(evals.EvalError, match="expected"):
        evals.load_golden(p2)


def test_load_golden_tolerates_corrupt_lines(tmp_path):
    p = tmp_path / "golden.jsonl"
    p.write_text(
        json.dumps({"prompt": "one", "expected": ["skill:pricing"],
                    "partition": "calib"}) + "\n"
        + "not json at all\n"
        + json.dumps({"prompt": "two", "expected": ["skill:research"],
                      "partition": "holdout"}) + "\n"
    )
    entries = evals.load_golden(p)
    assert [e.prompt for e in entries] == ["one", "two"]


def test_partition_entries_filters_and_validates():
    entries = evals.load_golden(evals.DEFAULT_GOLDEN)
    calib = evals.partition_entries(entries, "calib")
    holdout = evals.partition_entries(entries, "holdout")
    assert len(calib) == 12 and len(holdout) == 12
    assert not {e.partition for e in calib} - {"calib"}

    with pytest.raises(evals.EvalError):
        evals.partition_entries(entries, "train")


# -- run_router: mock ask injected, real jev.ask only on --live --------------------

def test_routed_ids_reads_gate_survivors():
    res = RouteResult(injections=[POINTER],
                      verdicts={"gate": {"survivors": ["skill:pricing"]}}, no_match=False)
    assert evals.routed_ids(res) == ["skill:pricing"]
    assert evals.routed_ids(RouteResult(
        injections=[], verdicts={"triage": {"skill": "skip"}}, no_match=True)) == []


def test_run_router_uses_injected_mock_ask(tmp_path, monkeypatch):
    cat = build_catalog(tmp_path / "catalog.db", small_rows())
    mock = RoutedAsk({PROMPT: ["pricing"]})
    monkeypatch.setattr(evals.jev, "ask",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("real ask used")))

    result = evals.run_router(PROMPT, cat, ask=mock)

    assert evals.routed_ids(result) == ["skill:pricing"]
    assert mock.triage_states == [PROMPT]  # the bare prompt is the triage state
    cat.close()


def test_run_router_defaults_to_real_jev_ask(tmp_path, monkeypatch):
    cat = build_catalog(tmp_path / "catalog.db", small_rows())
    seen = []

    def stub(state, questions, **kwargs):
        seen.append(state)
        return {qid: Noul(p=0.0) for qid in questions}  # triage skips everything

    monkeypatch.setattr(evals.jev, "ask", stub)
    evals.run_router(PROMPT, cat)  # ask=None -> real jev.ask (stubbed at source)

    assert seen == [PROMPT]
    cat.close()


# -- hit@k + majority-of-3 ----------------------------------------------------------

def test_hit_at_k_canned_results():
    # 3/3 runs hit at k=1
    assert evals.hit_at_k([["a"], ["a"], ["a"]], ["a"], 1) is True
    # majority 2/3 -> hit
    assert evals.hit_at_k([["a"], ["a"], ["b"]], ["a"], 1) is True
    # minority 1/3 -> miss
    assert evals.hit_at_k([["a"], ["b"], ["b"]], ["a"], 1) is False
    # 0/3
    assert evals.hit_at_k([["b"], ["b"], ["b"]], ["a"], 1) is False


def test_hit_at_k_depth_three_vs_one():
    # top-3 contains the expected id, top-1 does not
    results = [["x", "y", "a"]]
    assert evals.hit_at_k(results, ["a"], 3) is True
    assert evals.hit_at_k(results, ["a"], 1) is False


def test_hit_at_k_majority_via_thresholds_resample():
    votes = [True, True, False]
    assert evals.hit_at_k([["a"], ["a"], ["b"]], ["a"], 1) == resample(votes, k=3)


def test_hit_at_k_no_majority_returns_none():
    # 2 runs, split vote -> resample has no strict majority
    assert evals.hit_at_k([["a"], ["b"]], ["a"], 1) is None
    assert evals.hit_at_k([], ["a"], 1) is None


# -- evaluate / score_baseline (partition-explicit) ---------------------------------

def _two_entries():
    return [
        evals.GoldenEntry(id="h1", prompt="route me to pricing",
                          expected=("skill:pricing",), partition="holdout"),
        evals.GoldenEntry(id="h2", prompt="route me to research",
                          expected=("skill:research",), partition="holdout"),
    ]


def test_evaluate_scores_only_requested_partition(tmp_path):
    cat = build_catalog(tmp_path / "catalog.db", small_rows())
    entries = [
        evals.GoldenEntry(id="c1", prompt="calib one",
                          expected=("skill:pricing",), partition="calib"),
        evals.GoldenEntry(id="h1", prompt="holdout one",
                          expected=("skill:pricing",), partition="holdout"),
    ]
    mock = RoutedAsk({"holdout one": ["pricing"]})

    score = evals.evaluate(entries, cat, "holdout", ask=mock, runs=1)

    assert mock.triage_states == ["holdout one"]  # calib prompt never routed here
    assert (score.mode, score.partition, score.prompts) == ("router", "holdout", 1)
    assert score.hit1 == 1.0 and score.hit3 == 1.0
    cat.close()


def test_evaluate_hit_fractions_and_stability_on_canned_routing(tmp_path):
    cat = build_catalog(tmp_path / "catalog.db", small_rows())
    mock = RoutedAsk({"route me to pricing": ["pricing"]})  # second prompt no-match

    score = evals.evaluate(_two_entries(), cat, "holdout", ask=mock, runs=3)

    assert score.prompts == 2
    assert score.hit1 == pytest.approx(0.5)
    assert score.hit3 == pytest.approx(0.5)
    assert score.stability == pytest.approx(1.0)  # deterministic mock: full agreement
    assert len(mock.triage_states) == 6  # 2 prompts x 3 runs (triage fires once per route)
    cat.close()


def test_evaluate_rejects_unknown_partition(tmp_path):
    cat = build_catalog(tmp_path / "catalog.db", small_rows())
    with pytest.raises(evals.EvalError):
        evals.evaluate(_two_entries(), cat, "train", ask=RoutedAsk())
    cat.close()


def test_score_baseline_matches_expected_native_picks():
    entries = _two_entries()
    baseline = {"route me to pricing": ["skill:pricing"],
                "route me to research": ["skill:wiki"]}

    score = evals.score_baseline(entries, baseline, "holdout")

    assert score.mode == "baseline"
    assert score.prompts == 2
    assert score.hit1 == pytest.approx(0.5)
    assert score.hit3 == pytest.approx(0.5)
    assert score.stability is None  # deterministic: no resample variance


def test_score_baseline_hit3_but_not_hit1():
    entries = [evals.GoldenEntry(id="h1", prompt="p", expected=("skill:a",),
                                 partition="holdout")]
    baseline = {"p": ["skill:x", "skill:y", "skill:a"]}  # correct pick ranks 3rd

    score = evals.score_baseline(entries, baseline, "holdout")

    assert score.hit1 == 0.0
    assert score.hit3 == 1.0


def test_score_baseline_missing_entry_counts_as_miss():
    entries = _two_entries()
    score = evals.score_baseline(entries, {}, "holdout")
    assert score.hit1 == 0.0 and score.hit3 == 0.0


# -- sweep: calibration partition only, repacks shards, names winner ----------------

def test_sweep_never_routes_holdout_prompts(tmp_path):
    cat = build_catalog(tmp_path / "catalog.db", wide_rows())
    entries = [
        evals.GoldenEntry(id="c1", prompt="calib pricing", expected=("skill:cap-00",),
                          partition="calib"),
        evals.GoldenEntry(id="h1", prompt="holdout pricing", expected=("skill:cap-00",),
                          partition="holdout"),
    ]
    mock = RoutedAsk({"calib pricing": ["cap-00"]})

    rows, lines = evals.sweep(entries, cat, ask=mock, runs=1,
                              budgets=(600, 5000), max_options=(0,))

    assert set(mock.triage_states) == {"calib pricing"}  # holdout prompt never routed
    assert len(rows) == 2
    assert all(r["prompts"] == 1 for r in rows)
    cat.close()


def test_sweep_repacks_shards_and_names_winning_budget(tmp_path):
    cat = build_catalog(tmp_path / "catalog.db", wide_rows())
    entries = [evals.GoldenEntry(id="c1", prompt="calib pricing",
                                 expected=("skill:cap-00",), partition="calib")]
    mock = RoutedAsk({"calib pricing": ["cap-00"]})

    rows, lines = evals.sweep(entries, cat, ask=mock, runs=1,
                              budgets=(600, 5000), max_options=(0, 2))

    shards = {(r["budget"], r["max_options"]): r["shards"] for r in rows}
    assert shards[(5000, 0)] == 1          # big budget: one shard
    assert shards[(600, 0)] > 1            # small budget: budget forces a split
    assert shards[(5000, 2)] > shards[(5000, 0)]  # options-per-shard knob works
    winner = [ln for ln in lines if ln.startswith("winning")]
    assert len(winner) == 1
    assert "budget" in winner[0] and "hit@1" in winner[0]
    cat.close()


def test_repack_shards_keeps_every_option_reachable(tmp_path):
    cat = build_catalog(tmp_path / "catalog.db", wide_rows())
    evals.repack_shards(cat, budget_tokens=600, max_options=3)

    packed = json.loads(cat.rows(
        "SELECT value FROM meta WHERE key='shards:skill'")[0][0])
    ids = [rid for shard in packed["shards"] for rid in shard["ids"]]
    assert set(ids) == {r["id"] for r in wide_rows()}  # coverage preserved
    assert all(len(s["ids"]) <= 3 for s in packed["shards"])
    assert [s["i"] for s in packed["shards"]] == list(range(len(packed["shards"])))
    cat.close()


# -- report: router-vs-baseline markdown rows ----------------------------------------

def test_report_includes_router_and_baseline_rows():
    scores = [
        evals.Score(mode="router", partition="holdout", prompts=12,
                    hit1=0.667, hit3=0.833, stability=0.94),
        evals.Score(mode="baseline", partition="holdout", prompts=12,
                    hit1=0.5, hit3=0.667, stability=None),
    ]
    lines = evals.report(scores)

    assert lines[0].startswith("| mode |")
    router_rows = [ln for ln in lines if ln.startswith("| router ")]
    baseline_rows = [ln for ln in lines if ln.startswith("| baseline ")]
    assert len(router_rows) == 1 and len(baseline_rows) == 1
    assert "holdout" in router_rows[0] and "holdout" in baseline_rows[0]
    assert "0.667" in router_rows[0] and "0.500" in baseline_rows[0]
    assert "n/a" in baseline_rows[0]  # baseline is deterministic: no variance


# -- CLI ------------------------------------------------------------------------------

def test_cli_mock_mode_makes_no_jev_calls_and_prints_report(tmp_path, capsys,
                                                            monkeypatch):
    cfg, _ = make_state(tmp_path, small_rows())
    g = golden_file(tmp_path, [
        {"id": "h1", "prompt": PROMPT, "expected": ["skill:pricing"],
         "partition": "holdout"}])
    b = baseline_file(tmp_path, [{"id": "h1", "prompt": PROMPT, "native": ["skill:pricing"]}])
    monkeypatch.setattr(
        evals.jev, "ask",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("mock mode called Jev")))

    rc = evals.main(["--config", str(cfg), "--golden", str(g), "--baseline", str(b)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "mock" in out
    assert "| router |" in out and "| baseline |" in out


def test_cli_live_passes_real_jev_ask(tmp_path, capsys, monkeypatch):
    cfg, _ = make_state(tmp_path, small_rows())
    g = golden_file(tmp_path, [
        {"id": "h1", "prompt": PROMPT, "expected": ["skill:pricing"],
         "partition": "holdout"}])
    b = baseline_file(tmp_path, [{"id": "h1", "prompt": PROMPT, "native": []}])
    seen = []

    def stub(state, questions, **kwargs):
        seen.append(state)
        return {qid: Noul(p=0.0) for qid in questions}

    monkeypatch.setattr(evals.jev, "ask", stub)

    rc = evals.main(["--config", str(cfg), "--golden", str(g), "--baseline", str(b),
                     "--live", "--runs", "1"])

    out = capsys.readouterr().out
    assert rc == 0
    assert seen == [PROMPT]  # live mode routed through jev.ask (triage = bare prompt)
    assert "live" in out


def test_cli_sweep_names_winning_budget(tmp_path, capsys, monkeypatch):
    cfg, _ = make_state(tmp_path, wide_rows())
    g = golden_file(tmp_path, [
        {"id": "c1", "prompt": PROMPT, "expected": ["skill:cap-00"],
         "partition": "calib"}])
    b = baseline_file(tmp_path, [{"id": "c1", "prompt": PROMPT, "native": ["skill:cap-00"]}])
    monkeypatch.setattr(
        evals.jev, "ask",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("mock sweep called Jev")))

    rc = evals.main(["--config", str(cfg), "--golden", str(g), "--baseline", str(b),
                     "--sweep", "--budgets", "600,5000"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "winning" in out
    assert "| budget |" in out


def test_cli_missing_catalog_errors_cleanly(tmp_path, capsys):
    cfg = tmp_path / "router.toml"
    cfg.write_text(f'state_dir = "{tmp_path / "nostate"}"\n')
    g = golden_file(tmp_path, [{"id": "h1", "prompt": PROMPT,
                                "expected": ["skill:pricing"], "partition": "holdout"}])
    b = baseline_file(tmp_path, [])

    rc = evals.main(["--config", str(cfg), "--golden", str(g), "--baseline", str(b)])

    assert rc == 2
    assert "error" in capsys.readouterr().err.lower()

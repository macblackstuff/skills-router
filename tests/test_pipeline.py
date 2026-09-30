"""U4 tests: pipeline triage -> parallel recall fan -> gate, with a mock Jev.

Every scenario drives `route()` with a MockAsk (canned typed answers keyed by
question-id patterns) and asserts on the recorded calls: which layers fired,
which shards fanned, coverage of options, and the injected pointer lines.
"""
import copy
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.catalog import Catalog
from router.indexer import pack_shards
from router.jev import Choice, Noul
from router.pipeline import route

PROMPT = "help me price our SaaS"


def _choice(pick, probs, conf=0.9):
    return Choice(choice=pick, probabilities=dict(probs), confidence=conf)


def _none_choice():
    return Choice(choice="none", probabilities={"none": 0.99}, confidence=0.99)


class MockAsk:
    """Canned ask() dispatching on question-id patterns; records every call."""

    def __init__(self, triage=None, fan=None, gate=None, capture_p=0.01):
        self.triage = triage or {}      # type -> Noul p
        self.fan = fan or {}            # "recall_<type>_<i>" -> Choice
        self.gate = gate                # Choice for gate_inject
        self.capture_p = capture_p
        self.calls = []                 # [{"state": str, "questions": {qid: spec}}]
        self._lock = threading.Lock()

    def __call__(self, state, questions, **kwargs):
        with self._lock:
            self.calls.append(
                {"state": state, "questions": copy.deepcopy(questions)}
            )
        answers = {}
        for qid in questions:
            if qid.startswith("triage_"):
                answers[qid] = Noul(p=self.triage.get(qid[len("triage_"):], 0.01))
            elif qid.startswith("recall_"):
                answers[qid] = self.fan.get(qid, _none_choice())
            elif qid == "gate_inject":
                assert self.gate is not None, "unexpected gate call"
                answers[qid] = self.gate
            elif qid == "gate_capture":
                answers[qid] = Noul(p=self.capture_p)
            else:  # pragma: no cover
                raise AssertionError(f"unexpected question id {qid!r}")
        return answers

    def calls_with(self, prefix):
        return [c for c in self.calls if any(q.startswith(prefix) for q in c["questions"])]


# -- fixtures -----------------------------------------------------------------

SKILL_ROWS = [
    {"id": "pricing", "name": "Pricing Analysis",
     "description": "Price SaaS plans\nLonger body.", "path": "/skills/pricing/SKILL.md"},
    {"id": "cold-email", "name": "Cold Email",
     "description": "Write cold outbound emails", "path": "/skills/cold-email/SKILL.md"},
]
RULE_ROWS = [
    {"id": "pricing", "name": "Pricing Rule",
     "description": "Never discount below floor", "path": "/rules/pricing.md"},
    {"id": "secrets", "name": "Secrets Rule",
     "description": "Never print secrets", "path": "/rules/secrets.md"},
]


def build_catalog(tmp_path, spec, budget_tokens=3000):
    """Catalog with real indexer-packed shards written to meta shards:<type>."""
    cat = Catalog(tmp_path / "catalog.db")
    for t, rows in spec.items():
        cat.ensure_type(t)
        for r in rows:
            cat.upsert(t, r)
        packed = pack_shards(rows, budget_tokens=budget_tokens)
        cat.db.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"shards:{t}", json.dumps(packed)),
        )
    cat.db.commit()
    return cat


def write_manual_shards(cat, type_, shards):
    """Hand-built shard payloads in the indexer's stored format."""
    packed = {
        "budget_tokens": 0, "chars_per_token": 4, "overlap_fraction": 0.1,
        "count": len(shards), "shards": shards,
    }
    cat.db.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"shards:{type_}", json.dumps(packed)),
    )
    cat.db.commit()


# -- scenarios ------------------------------------------------------------------

def test_end_to_end_pointer_line(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS, "rule": RULE_ROWS})
    mock = MockAsk(
        triage={"skill": 0.98, "rule": 0.01},
        fan={"recall_skill_0": _choice(
            "pricing", {"pricing": 0.97, "cold-email": 0.02, "none": 0.01})},
        gate=_choice("skill:pricing", {"skill:pricing": 0.98, "none": 0.02}),
    )
    res = route(PROMPT, cat, ask=mock)

    assert res.injections == [
        "- [skill] Pricing Analysis — Price SaaS plans (/skills/pricing/SKILL.md)"
    ]
    assert res.no_match is False
    assert res.capture_candidate == 0.01
    # triage is ONE call carrying a Noul per present type
    triage_calls = mock.calls_with("triage_")
    assert len(triage_calls) == 1
    assert set(triage_calls[0]["questions"]) == {"triage_skill", "triage_rule"}
    assert all(spec["type"] == "noul" for spec in triage_calls[0]["questions"].values())
    # only the passed type's shards fire
    recall_qids = [q for c in mock.calls_with("recall_") for q in c["questions"]]
    assert recall_qids == ["recall_skill_0"]
    # verdicts
    assert res.verdicts["triage"] == {"rule": "skip", "skill": "act"}
    assert res.verdicts["fan"]["recall_skill_0"] == {"choice": "pricing", "p": 0.97}
    assert res.verdicts["gate"]["choice"] == "skill:pricing"
    assert res.verdicts["gate"]["survivors"] == ["skill:pricing"]


def test_triage_escalate_does_not_proceed(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS})
    mock = MockAsk(triage={"skill": 0.5})
    res = route(PROMPT, cat, ask=mock)
    assert res.verdicts["triage"] == {"skill": "escalate"}
    assert mock.calls_with("recall_") == []
    assert res.no_match is True
    assert res.injections == []


def test_no_match_when_triage_skips_everything(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS, "rule": RULE_ROWS})
    mock = MockAsk()  # default triage p=0.01 -> skip
    res = route(PROMPT, cat, ask=mock)
    assert res.no_match is True
    assert res.injections == []
    assert len(mock.calls) == 1  # the triage call only
    assert "gate" not in res.verdicts


def test_no_match_when_fan_finds_nothing(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS})
    mock = MockAsk(triage={"skill": 0.99})  # fan defaults to "none"
    res = route(PROMPT, cat, ask=mock)
    assert res.no_match is True
    assert res.injections == []
    assert mock.calls_with("gate_") == []
    assert res.capture_candidate is None


def test_no_match_when_gate_picks_none(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS})
    mock = MockAsk(
        triage={"skill": 0.99},
        fan={"recall_skill_0": _choice("pricing", {"pricing": 0.96, "none": 0.04})},
        gate=_choice("none", {"skill:pricing": 0.02, "none": 0.98}),
        capture_p=0.9,
    )
    res = route(PROMPT, cat, ask=mock)
    assert res.no_match is True
    assert res.injections == []
    assert res.capture_candidate == 0.9  # capture question still answered


def test_gate_trims_cross_type_duplicates(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS, "rule": RULE_ROWS})
    mock = MockAsk(
        triage={"skill": 0.99, "rule": 0.99},
        fan={
            "recall_skill_0": _choice("pricing", {"pricing": 0.96, "none": 0.04}),
            "recall_rule_0": _choice("pricing", {"pricing": 0.96, "none": 0.04}),
        },
        gate=_choice("skill:pricing",
                     {"skill:pricing": 0.97, "rule:pricing": 0.02, "none": 0.01}),
    )
    res = route(PROMPT, cat, ask=mock)
    # same capability id won under both types; gate keeps the skill one only
    assert res.injections == [
        "- [skill] Pricing Analysis — Price SaaS plans (/skills/pricing/SKILL.md)"
    ]
    assert res.verdicts["gate"]["survivors"] == ["skill:pricing"]
    assert res.no_match is False


def test_multi_shard_type_covers_all_shards(tmp_path):
    rows = [
        {"id": f"cap-{i:02d}", "name": f"Cap {i:02d}",
         "description": f"Analyze pricing caps for enterprise deal number {i:02d} region",
         "path": f"/skills/cap-{i:02d}/SKILL.md"}
        for i in range(10)
    ]
    cat = build_catalog(tmp_path, {"skill": rows}, budget_tokens=60)
    expected = pack_shards(rows, budget_tokens=60)["shards"]
    assert len(expected) >= 2  # the fixture really is multi-shard

    mock = MockAsk(
        triage={"skill": 0.99},
        fan={"recall_skill_0": _choice("cap-00", {"cap-00": 0.97, "none": 0.03})},
        gate=_choice("skill:cap-00", {"skill:cap-00": 0.98, "none": 0.02}),
    )
    res = route(PROMPT, cat, ask=mock)

    recall_calls = mock.calls_with("recall_")
    assert {q for c in recall_calls for q in c["questions"]} == {
        f"recall_skill_{s['i']}" for s in expected
    }
    # every option of every shard is offered to some worker
    offered = set()
    for c in recall_calls:
        for spec in c["questions"].values():
            offered.update(spec["criteria"])
    assert {r["id"] for r in rows} <= offered
    assert res.injections == [
        "- [skill] Cap 00 — Analyze pricing caps for enterprise deal number 00 "
        "region (/skills/cap-00/SKILL.md)"
    ]


def test_worker_ceiling_merges_instead_of_dropping(tmp_path):
    rows = [
        {"id": i, "name": i.upper(), "description": f"does {i}",
         "path": f"/skills/{i}.md"}
        for i in "abcdef"
    ]
    cat = build_catalog(tmp_path, {"skill": rows})
    shards = [
        {"i": 0, "ids": ["a", "b"],
         "text": "a | A | does a\nb | B | does b", "chars": 24, "est_tokens": 6},
        {"i": 1, "ids": ["c", "d"],
         "text": "c | C | does c\nd | D | does d", "chars": 24, "est_tokens": 6},
        {"i": 2, "ids": ["e", "f"],
         "text": "e | E | does e\nf | F | does f", "chars": 24, "est_tokens": 6},
    ]
    write_manual_shards(cat, "skill", shards)

    mock = MockAsk(
        triage={"skill": 0.99},
        fan={"recall_skill_0": _choice("a", {"a": 0.97, "b": 0.01, "none": 0.02})},
        gate=_choice("skill:a", {"skill:a": 0.98, "none": 0.02}),
    )
    res = route(PROMPT, cat, ask=mock, worker_ceiling=2)

    recall_calls = mock.calls_with("recall_")
    assert len(recall_calls) == 2  # ceiling honored: no third worker
    assert set(recall_calls[0]["questions"]) == {"recall_skill_0"}
    assert set(recall_calls[1]["questions"]) == {"recall_skill_1"}
    # remaining shards merged into the last worker: coverage preserved
    merged_criteria = set(next(iter(recall_calls[1]["questions"].values()))["criteria"])
    assert {"c", "d", "e", "f", "none"} <= merged_criteria
    offered = set()
    for c in recall_calls:
        for spec in c["questions"].values():
            offered.update(spec["criteria"])
    assert offered == {"a", "b", "c", "d", "e", "f", "none"}
    assert res.injections == ["- [skill] A — does a (/skills/a.md)"]
    assert res.no_match is False


def test_capture_candidate_passthrough(tmp_path):
    cat = build_catalog(tmp_path, {"skill": SKILL_ROWS})
    mock = MockAsk(
        triage={"skill": 0.99},
        fan={"recall_skill_0": _choice("pricing", {"pricing": 0.97, "none": 0.03})},
        gate=_choice("skill:pricing", {"skill:pricing": 0.99, "none": 0.01}),
        capture_p=0.98,
    )
    res = route(PROMPT, cat, ask=mock)
    assert res.capture_candidate == 0.98

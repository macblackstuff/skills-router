"""U6 tests: session memory, active-set decay, transcript tail, state assembly.

Proof-first for KTD6/R7 (AE3): a "continue" turn resolves through memory —
active capability ids are exposed in the Jev state, so the router need not
re-inject; active capabilities decay per turn and become re-injectable after
ttl runs out; a missing session file is a clean cold start; concurrent
sessions keep separate files.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.memory import (
    DEFAULT_TTL,
    ROLLING_LINES,
    SessionMemory,
    transcript_tail,
)


# -- AE3: "continue" resolves the active capability via memory -----------------


def test_continue_turn_exposes_active_capability_in_state(tmp_path):
    mem = SessionMemory(tmp_path)
    mem.record_turn("s1", "price our SaaS", ["skill:pricing"])

    loaded = mem.load("s1")
    assert loaded["active_ids"] == ["skill:pricing"]

    state = mem.context_state("continue", "s1", None)
    assert state.startswith("PROMPT:\ncontinue")
    assert "skill:pricing" in state  # active ids join the Jev state


def test_entry_shape_on_disk(tmp_path):
    mem = SessionMemory(tmp_path)
    mem.record_turn("s1", "prompt text", ["skill:pricing", "rule:secrets"])

    path = tmp_path / "sessions" / "s1.jsonl"
    assert path.is_file()
    entry = json.loads(path.read_text().splitlines()[0])
    assert entry["ts"]
    assert entry["turn_digest"] == hashlib.sha256(b"prompt text").hexdigest()
    assert entry["injected"] == ["skill:pricing", "rule:secrets"]
    assert [a["id"] for a in entry["active_set"]] == ["skill:pricing", "rule:secrets"]
    assert all(a["turns_left"] == DEFAULT_TTL for a in entry["active_set"])


# -- decay: ttl runs out, capability becomes re-injectable ---------------------


def test_decayed_capability_drops_then_is_reinjectable(tmp_path):
    mem = SessionMemory(tmp_path)
    mem.record_turn("s1", "t1", ["skill:pricing"])
    for prompt in ("t2", "t3"):  # ttl 3 -> 2 -> 1, still active
        mem.record_turn("s1", prompt, [])
        assert mem.load("s1")["active_ids"] == ["skill:pricing"]
    mem.record_turn("s1", "t4", [])  # ttl hits 0 -> dropped
    assert mem.load("s1")["active_ids"] == []

    mem.record_turn("s1", "t5", ["skill:pricing"])  # re-injectable at full ttl
    assert mem.load("s1")["active_ids"] == ["skill:pricing"]


def test_reinjection_refreshes_ttl(tmp_path):
    mem = SessionMemory(tmp_path)
    mem.record_turn("s1", "t1", ["skill:pricing"])
    mem.record_turn("s1", "t2", [])  # 2 left
    mem.record_turn("s1", "t3", ["skill:pricing"])  # refreshed to 3
    for prompt in ("t4", "t5"):  # 2 left, then 1 left
        mem.record_turn("s1", prompt, [])
    assert mem.load("s1")["active_ids"] == ["skill:pricing"]


# -- cold start ----------------------------------------------------------------


def test_missing_file_is_clean_cold_start(tmp_path):
    mem = SessionMemory(tmp_path)
    assert mem.load("never-seen") == {
        "rolling_summary_lines": [],
        "active_ids": [],
    }
    assert mem.context_state("hello", "never-seen", None) == "PROMPT:\nhello"


def test_transcript_tail_missing_file_returns_empty(tmp_path):
    assert transcript_tail(tmp_path / "nope.jsonl") == []


# -- rolling summary -------------------------------------------------------------


def test_rolling_summary_keeps_last_ten_prompts(tmp_path):
    mem = SessionMemory(tmp_path)
    for i in range(12):
        mem.record_turn("s1", f"p{i}", [])
    lines = mem.load("s1")["rolling_summary_lines"]
    assert lines == [f"p{i}" for i in range(2, 12)]
    assert len(lines) == ROLLING_LINES


# -- transcript tail --------------------------------------------------------------


def test_transcript_tail_last_k_nonempty_lines(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\nline0\nline1\n\nline2\nline3\nline4\nline5\nline6\n\n")
    assert transcript_tail(f, k=5) == [f"line{i}" for i in range(2, 7)]
    assert transcript_tail(f, k=10) == [f"line{i}" for i in range(7)]


# -- concurrent sessions ----------------------------------------------------------


def test_concurrent_sessions_keep_separate_files(tmp_path):
    mem = SessionMemory(tmp_path)
    mem.record_turn("sess-a", "pa", ["skill:pricing"])
    mem.record_turn("sess-b", "pb", ["rule:secrets"])

    a = tmp_path / "sessions" / "sess-a.jsonl"
    b = tmp_path / "sessions" / "sess-b.jsonl"
    assert a.is_file() and b.is_file()
    assert mem.load("sess-a")["active_ids"] == ["skill:pricing"]
    assert mem.load("sess-b")["active_ids"] == ["rule:secrets"]


# -- state assembly ----------------------------------------------------------------


def test_context_state_assembles_prompt_tail_and_active(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("u: price it\na: ok\n")
    mem = SessionMemory(tmp_path)
    mem.record_turn("s1", "earlier", ["skill:pricing"])

    state = mem.context_state("continue", "s1", transcript)
    assert state.startswith("PROMPT:\ncontinue")
    assert "u: price it" in state and "a: ok" in state
    assert "skill:pricing" in state
    # ordering: prompt, then transcript tail, then active ids
    assert state.index("continue") < state.index("u: price it")
    assert state.index("a: ok") < state.index("skill:pricing")


# -- resilience: corrupt state rebuilds, never crashes (KTD4) -------------------


def test_corrupt_last_line_is_skipped_not_fatal(tmp_path):
    mem = SessionMemory(tmp_path)
    mem.record_turn("s1", "p1", ["skill:pricing"])
    with (tmp_path / "sessions" / "s1.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")

    loaded = mem.load("s1")
    assert loaded["active_ids"] == ["skill:pricing"]
    assert loaded["rolling_summary_lines"] == ["p1"]
    mem.record_turn("s1", "p2", [])  # decay continues from last sane entry
    assert mem.load("s1")["active_ids"] == ["skill:pricing"]

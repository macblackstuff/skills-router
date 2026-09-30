"""U15 tests: capture drainer (KTD11, R13/F5).

Plan scenarios: skill-shaped capture -> SKILL.md stub drafted; rule capture ->
typed section drafted with type mapping; roster capture -> roster line; review
mode never writes sources directly; auto mode writes the captured-sources root
and reindex runs (jev.ask mocked); duplicate capture skipped by hash.

Queue entries are produced by the real U14 capture.append() so the pending
line shape stays canonical ({ts, session, kind, payload, turn_context}).
jev.ask is replaced by AskSpy returning one typed Score per call.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router import capture, cli, drainer  # noqa: E402
from router.catalog import Catalog  # noqa: E402
from router.config import RouterConfig  # noqa: E402
from router.jev import JevError, JevTimeoutError, Score  # noqa: E402
from router.sources import roster as roster_source  # noqa: E402
from router.sources import rules as rules_source  # noqa: E402
from router.sources import skills as skills_source  # noqa: E402

SKILL_TEXT = "user asked to run `recut` to trim clips; no indexed skill covers it"
RULE_TEXT = "always run the full test suite before committing"
MODEL_TEXT = "gpt-9 handled long-context work best; worth a roster entry"


# -- helpers ----------------------------------------------------------------------

def _config(tmp_path, mode="review"):
    cfg = RouterConfig()
    cfg.state_dir = str(tmp_path / "state")
    cfg.capture_mode = mode
    return cfg


def _queue(cfg, *candidates):
    for cand in candidates:
        assert capture.append(cand, cfg) is True


def _drain(cfg, tmp_path, **kw):
    kw.setdefault("captured_root", tmp_path / "captured")
    return drainer.drain(cfg, **kw)


class AskSpy:
    """Fake jev.ask: one Score answer per call; records (state, questions)."""

    def __init__(self, score=0.9, confidence=0.8, exc=None):
        self.score = score
        self.confidence = confidence
        self.exc = exc
        self.calls = []

    def __call__(self, state, questions):
        self.calls.append((state, questions))
        if self.exc is not None:
            raise self.exc
        return {drainer.WORTH_QID: Score(score=self.score, confidence=self.confidence)}


def _log_text(cfg):
    p = cfg.state_path("captures", "drainer.log")
    return p.read_text() if p.exists() else ""


# -- review-mode drafting ----------------------------------------------------------

class TestReviewModeDrafts:
    def test_skill_capture_drafts_stub(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"})
        spy = AskSpy(score=0.9)

        result = _drain(cfg, tmp_path, ask=spy)

        assert (result.judged, result.accepted, result.discarded, result.duplicates) == (1, 1, 0, 0)
        assert result.error is None
        assert result.reindexed is False
        stubs = list(cfg.state_path("captures", "drafts", "skill").rglob("SKILL.md"))
        assert len(stubs) == 1
        assert result.drafts == stubs
        fm = skills_source.parse_frontmatter(stubs[0].read_text())
        assert fm.get("name")
        assert " ".join(SKILL_TEXT.split()) in str(fm.get("description")) + stubs[0].read_text()
        # a scored draft keeps its Jev verdict recorded in the log
        assert "accepted" in _log_text(cfg)
        assert "0.9" in _log_text(cfg)

    def test_rule_capture_drafts_typed_section(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": RULE_TEXT, "session": "s-1", "kind": "rule"})
        spy = AskSpy(score=0.85)

        result = _drain(cfg, tmp_path, ask=spy)

        assert result.accepted == 1
        rule_dir = cfg.state_path("captures", "drafts", "rule")
        sections = list(rule_dir.glob("*.md"))
        assert len(sections) == 1
        body = sections[0].read_text()
        assert body.lstrip().startswith("#")
        assert RULE_TEXT in body
        rows = rules_source.iter_rows([rule_dir])
        assert len(rows) == 1
        assert RULE_TEXT in rows[0]["description"]

    def test_roster_capture_drafts_line(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {
            "text": MODEL_TEXT, "session": "s-1", "kind": "model",
            "payload": {"models": ["gpt-9"]},
        })
        spy = AskSpy(score=0.88)

        result = _drain(cfg, tmp_path, ask=spy)

        assert result.accepted == 1
        lines_file = cfg.state_path("captures", "drafts", "model", "captured-models.md")
        assert lines_file.is_file()
        body = lines_file.read_text()
        assert "- gpt-9 — " in body
        assert MODEL_TEXT in body
        rows = roster_source.iter_rows(lines_file)
        assert [r["name"] for r in rows] == ["gpt-9"]

    def test_learning_capture_drafts_note(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": "vim motions compound over years", "session": "s-1"})
        result = _drain(cfg, tmp_path, ask=AskSpy(score=0.9))
        assert result.accepted == 1
        notes = list(cfg.state_path("captures", "drafts", "learning").glob("*.md"))
        assert len(notes) == 1
        assert "vim motions" in notes[0].read_text()

    def test_review_never_writes_source_tree(self, tmp_path):
        cfg = _config(tmp_path)  # capture_mode defaults to review
        captured = tmp_path / "captured"
        captured.mkdir()
        (captured / "keep.txt").write_text("sentinel")
        _queue(
            cfg,
            {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"},
            {"text": RULE_TEXT, "session": "s-1", "kind": "rule"},
        )
        index_calls = []
        result = _drain(
            cfg, tmp_path, ask=AskSpy(score=0.95), index_run=lambda: index_calls.append(1)
        )

        assert result.accepted == 2
        assert sorted(p.name for p in captured.iterdir()) == ["keep.txt"]
        assert (captured / "keep.txt").read_text() == "sentinel"
        assert index_calls == []  # nothing indexed changed in review mode

    def test_discard_logs_rationale_and_is_final(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": "transient one-off detail", "session": "s-1", "kind": "learning"})
        spy = AskSpy(score=0.3)

        first = _drain(cfg, tmp_path, ask=spy)
        assert (first.judged, first.accepted, first.discarded) == (1, 0, 1)
        assert first.drafts == []
        log = _log_text(cfg)
        assert "discarded" in log
        assert "0.3" in log  # rationale: score below threshold

        # a discard is a drain decision: the hash is ledgered, not re-judged
        second = _drain(cfg, tmp_path, ask=spy)
        assert second.judged == 0
        assert second.duplicates == 1
        assert len(spy.calls) == 1

    def test_draft_writes_leave_no_temp_files(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(
            cfg,
            {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"},
            {"text": RULE_TEXT, "session": "s-1", "kind": "rule"},
            {"text": MODEL_TEXT, "session": "s-1", "kind": "model",
             "payload": {"models": ["gpt-9"]}},
        )
        _drain(cfg, tmp_path, ask=AskSpy(score=0.9))
        drafts = cfg.state_path("captures", "drafts")
        assert list(drafts.rglob("*.tmp")) == []
        assert list(drafts.rglob("*.tmp-*")) == []


# -- auto mode: captured-sources root + reindex ------------------------------------

class TestAutoMode:
    def test_auto_writes_captured_root_and_reindexes(self, tmp_path):
        cfg = _config(tmp_path, mode="auto")
        _queue(
            cfg,
            {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"},
            {"text": RULE_TEXT, "session": "s-1", "kind": "rule"},
        )
        captured = tmp_path / "captured"
        index_calls = []
        result = _drain(
            cfg, tmp_path, ask=AskSpy(score=0.9), index_run=lambda: index_calls.append(1)
        )

        assert result.accepted == 2
        assert result.reindexed is True
        assert index_calls == [1]
        skill_stubs = list((captured / "skill").rglob("SKILL.md"))
        assert len(skill_stubs) == 1
        assert skills_source.parse_frontmatter(skill_stubs[0].read_text()).get("name")
        assert list((captured / "rule").glob("*.md"))
        # drafts dir is review-mode-only; auto mode never touches it
        assert not cfg.state_path("captures", "drafts").exists()

    def test_auto_full_flow_file_to_indexed_row(self, tmp_path):
        """U15 verification: queued capture -> file -> index -> routable row."""
        cfg = _config(tmp_path, mode="auto")
        captured = tmp_path / "captured"
        cfg.skill_dirs = [str(captured / "skill")]
        _queue(cfg, {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"})

        result = _drain(cfg, tmp_path, ask=AskSpy(score=0.9))  # default index run

        assert result.reindexed is True
        cat = Catalog(cfg.state_path("catalog.db"))
        try:
            assert cat.count("skill") == 1
            row = cat.rows("SELECT id, name, path FROM skill")[0]
            assert row[2] == str(next((captured / "skill").rglob("SKILL.md")))
        finally:
            cat.close()

    def test_auto_no_accepts_no_reindex(self, tmp_path):
        cfg = _config(tmp_path, mode="auto")
        _queue(cfg, {"text": "transient one-off detail", "session": "s-1"})
        index_calls = []
        result = _drain(
            cfg, tmp_path, ask=AskSpy(score=0.2), index_run=lambda: index_calls.append(1)
        )
        assert result.discarded == 1
        assert result.reindexed is False
        assert index_calls == []

    def test_default_captured_root_is_repo_sources_captured(self):
        root = drainer.default_captured_root()
        assert root.parts[-2:] == ("sources", "captured")
        assert root.parent.parent == Path(drainer.__file__).resolve().parents[2]


# -- hash ledger --------------------------------------------------------------------

class TestDrainedLedger:
    def test_duplicate_capture_skipped_by_hash(self, tmp_path):
        cfg = _config(tmp_path)
        cand = {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"}
        _queue(cfg, cand, dict(cand))  # same content queued twice
        spy = AskSpy(score=0.9)

        first = _drain(cfg, tmp_path, ask=spy)
        assert (first.judged, first.accepted, first.duplicates) == (1, 1, 1)
        assert len(spy.calls) == 1
        drained = cfg.state_path("captures", "drained.jsonl")
        assert len(drained.read_text().splitlines()) == 1

        # a later drain of the same pending lines skips everything by hash
        _queue(cfg, dict(cand))
        second = _drain(cfg, tmp_path, ask=spy)
        assert second.judged == 0
        assert second.duplicates == 3  # all three pending lines hit the ledger
        assert len(spy.calls) == 1  # no second Jev call
        stubs = list(cfg.state_path("captures", "drafts", "skill").rglob("SKILL.md"))
        assert len(stubs) == 1


# -- failures ------------------------------------------------------------------------

class TestFailures:
    def test_jev_failure_stops_drain_keeps_candidate_pending(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(
            cfg,
            {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"},
            {"text": RULE_TEXT, "session": "s-1", "kind": "rule"},
        )
        spy = AskSpy(exc=JevTimeoutError("Jev API timed out"))

        result = _drain(cfg, tmp_path, ask=spy)

        assert result.judged == 0
        assert result.error is not None
        assert not cfg.state_path("captures", "drained.jsonl").exists()
        pending = cfg.state_path("captures", "pending.jsonl").read_text()
        assert len([l for l in pending.splitlines() if l]) == 2  # retried next drain
        assert list(cfg.state_path("captures").rglob("SKILL.md")) == []

    def test_malformed_answer_is_drain_error_not_crash(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"})

        def bad_answer(state, questions):
            return {drainer.WORTH_QID: "not-a-score"}

        result = _drain(cfg, tmp_path, ask=bad_answer)
        assert result.error is not None
        assert result.judged == 0

    def test_malformed_pending_lines_skipped(self, tmp_path):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": RULE_TEXT, "session": "s-1", "kind": "rule"})
        pending = cfg.state_path("captures", "pending.jsonl")
        with pending.open("a", encoding="utf-8") as f:
            f.write("{{not json at all\n")
            f.write("\n")
        result = _drain(cfg, tmp_path, ask=AskSpy(score=0.9))
        assert result.judged == 1
        assert result.accepted == 1
        assert "malformed" in _log_text(cfg)

    def test_missing_queue_is_clean_noop(self, tmp_path):
        cfg = _config(tmp_path)
        result = _drain(cfg, tmp_path, ask=AskSpy(score=0.9))
        assert (result.judged, result.accepted, result.discarded, result.duplicates) == (0, 0, 0, 0)
        assert result.error is None
        assert not cfg.state_path("captures", "drainer.log").exists()

    def test_empty_payload_text_skipped(self, tmp_path):
        cfg = _config(tmp_path)
        pending = cfg.state_path("captures", "pending.jsonl")
        pending.parent.mkdir(parents=True)
        # blank-text line written directly: capture.append() refuses to queue one
        pending.write_text(
            json.dumps({"ts": "t", "session": "s-1", "kind": "skill",
                        "payload": {"text": "   "}, "turn_context": {}}) + "\n"
        )
        spy = AskSpy(score=0.9)
        result = _drain(cfg, tmp_path, ask=spy)
        assert result.judged == 0
        assert len(spy.calls) == 0


# -- CLI: router capture ---------------------------------------------------------------

class TestCliCapture:
    def _toml(self, tmp_path, cfg):
        path = tmp_path / "router.toml"
        path.write_text(
            f'state_dir = "{cfg.state_dir}"\ncapture_mode = "{cfg.capture_mode}"\n'
        )
        return path

    def test_capture_subcommand_drains_and_reports(self, tmp_path, capsys, monkeypatch):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"})
        monkeypatch.setattr(drainer.jev, "ask", AskSpy(score=0.9))

        assert cli.main(["--config", str(self._toml(tmp_path, cfg)), "capture"]) == 0
        out = capsys.readouterr().out
        assert "accepted 1" in out
        stubs = list(cfg.state_path("captures", "drafts", "skill").rglob("SKILL.md"))
        assert len(stubs) == 1
        assert str(stubs[0]) in out

    def test_capture_auto_mode_reports_reindex(self, tmp_path, capsys, monkeypatch):
        cfg = _config(tmp_path, mode="auto")
        _queue(cfg, {"text": RULE_TEXT, "session": "s-1", "kind": "rule"})
        captured = tmp_path / "captured"
        calls = []
        monkeypatch.setattr(drainer.jev, "ask", AskSpy(score=0.9))
        monkeypatch.setattr(drainer, "default_captured_root", lambda: captured)
        monkeypatch.setattr(drainer.indexer, "run_index", lambda c, **kw: calls.append(c) or 0)

        assert cli.main(["--config", str(self._toml(tmp_path, cfg)), "capture"]) == 0
        assert calls == [cfg]
        assert list((captured / "rule").glob("*.md"))
        assert "reindexed yes" in capsys.readouterr().out

    def test_capture_jev_error_exit_2(self, tmp_path, capsys, monkeypatch):
        cfg = _config(tmp_path)
        _queue(cfg, {"text": SKILL_TEXT, "session": "s-1", "kind": "skill"})

        def boom(state, questions):
            raise JevError("Jev API HTTP 500")

        monkeypatch.setattr(drainer.jev, "ask", boom)
        rc = cli.main(["--config", str(self._toml(tmp_path, cfg)), "capture"])
        assert rc == 2
        assert "error" in capsys.readouterr().err.lower()

    def test_capture_empty_queue_exit_0(self, tmp_path, capsys, monkeypatch):
        cfg = _config(tmp_path)
        monkeypatch.setattr(drainer.jev, "ask", AskSpy(score=0.9))
        assert cli.main(["--config", str(self._toml(tmp_path, cfg)), "capture"]) == 0
        assert "judged 0" in capsys.readouterr().out

"""U14 tests: per-turn learning capture queue (KTD11, R13/F5).

Plan scenarios: unknown skill mentioned -> queue entry carrying turn context;
rule-shaped instruction ("always X") -> candidate typed "rule"; no candidates
-> no queue write; queue append failure -> log-and-continue (returns False,
never raises, turn NOT blocked). Plus the classify() heuristic and the
detect_model_mentions() roster auto-discovery flagging.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router import capture
from router.config import RouterConfig


def _config(tmp_path):
    cfg = RouterConfig()
    cfg.state_dir = str(tmp_path / "state")
    return cfg


def _pending(cfg):
    return cfg.state_path("captures", "pending.jsonl")


def _lines(cfg):
    p = _pending(cfg)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line]


class TestQueueAppend:
    def test_unknown_skill_mention_queues_entry_with_context(self, tmp_path):
        cfg = _config(tmp_path)
        candidate = {
            "text": "user asked to run `recut`, a tool with no indexed skill",
            "session": "sess-42",
            "turn_context": {
                "prompt": "use recut to cut this clip",
                "injections": ["- [skill] ffmpeg — convert media (bin/ffmpeg)"],
                "capture_p": 0.83,
            },
        }
        assert capture.append(candidate, cfg) is True

        entries = _lines(cfg)
        assert len(entries) == 1
        entry = entries[0]
        assert set(entry) == {"ts", "session", "kind", "payload", "turn_context"}
        assert entry["session"] == "sess-42"
        assert entry["kind"] == "skill"
        assert entry["payload"]["text"] == candidate["text"]
        assert entry["turn_context"] == candidate["turn_context"]
        datetime.fromisoformat(entry["ts"])  # timestamp parses

    def test_rule_shaped_instruction_typed_rule(self, tmp_path):
        cfg = _config(tmp_path)
        ok = capture.append(
            {"text": "always run the full suite before committing", "session": "s1"},
            cfg,
        )
        assert ok is True
        assert _lines(cfg)[0]["kind"] == "rule"

    def test_no_candidates_no_write(self, tmp_path):
        cfg = _config(tmp_path)
        assert capture.append({}, cfg) is False
        assert capture.append({"session": "s1"}, cfg) is False  # no text
        assert capture.append({"text": "   "}, cfg) is False     # blank text
        assert not _pending(cfg).exists()
        assert not cfg.state_path("captures").exists()

    def test_append_failure_returns_false_no_exception(self, tmp_path, capsys):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("i am a regular file")
        cfg = _config(tmp_path)
        cfg.state_dir = str(blocker)  # mkdir under a file -> OSError

        assert capture.append(
            {"text": "always commit small", "session": "s1"}, cfg
        ) is False
        assert "capture" in capsys.readouterr().err.lower()

    def test_appends_accumulate_one_line_each(self, tmp_path):
        cfg = _config(tmp_path)
        capture.append({"text": "learned X compounds", "session": "s1"}, cfg)
        capture.append({"text": "always Y", "session": "s1"}, cfg)
        assert len(_lines(cfg)) == 2


class TestClassify:
    @pytest.mark.parametrize(
        "text,kind",
        [
            ("always run tests before committing", "rule"),
            ("never push straight to main", "rule"),
            ("you must keep diffs minimal", "rule"),
            ("user mentioned the `recut` tool", "skill"),
            ("install the ripgrep cli for searching", "skill"),
            ("use the indexer skill", "skill"),
            ("vim motions compound over years", "learning"),
            ("", "learning"),
        ],
    )
    def test_heuristic(self, text, kind):
        assert capture.classify(text) == kind


class TestDetectModelMentions:
    def test_flags_unrostered_models_roster_case_insensitive(self):
        text = "compare glm-4.6 against gpt-5 for this task"
        assert capture.detect_model_mentions(text, ["GLM-4.6"]) == ["gpt-5"]

    def test_all_rostered_returns_empty(self):
        text = "gpt-5 vs glm-4.6"
        assert capture.detect_model_mentions(text, ["gpt-5", "GLM-4.6"]) == []

    def test_plain_hyphenated_words_not_flagged(self):
        text = "the read-only state-dir layout is fine"
        assert capture.detect_model_mentions(text, []) == []

    def test_family_word_flagged_deduped(self):
        text = "ask sonnet first, then sonnet again"
        assert capture.detect_model_mentions(text, []) == ["sonnet"]

    def test_versioned_identifier_kept_whole(self):
        text = "claude-3.5-sonnet handled it"
        assert capture.detect_model_mentions(text, []) == ["claude-3.5-sonnet"]

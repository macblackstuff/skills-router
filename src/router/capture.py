"""U14: per-turn learning capture (KTD11, R13/F5).

The gate's capture question (RouteResult.capture_candidate) flags candidate
learnings each turn. This module appends each candidate as ONE JSONL line to
``<state_dir>/captures/pending.jsonl``:

    {"ts": ..., "session": ..., "kind": ..., "payload": {...}, "turn_context": {...}}

Rules (fixed by KTD11): zero mid-turn source writes; the queue line carries
the turn context the U15 drainer needs; appends flush immediately (batched
with the telemetry write); an append failure LOGS AND CONTINUES — routing
already succeeded, so append() returns False and never raises, and the
candidate is simply recovered on the next drain.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from typing import Iterable, List

from router.config import RouterConfig

PENDING_REL = ("captures", "pending.jsonl")

# kind heuristics — order is fixed: rule-shaped beats skill-shaped beats learning
_RULE_RE = re.compile(r"\b(always|never|must)\b", re.IGNORECASE)
_TOOL_RE = re.compile(
    r"\b(skill|tool|cli|command|plugin|binary)\b|`[^`]+`", re.IGNORECASE
)

# model mentions: versioned identifiers (glm-4.6, gpt-4o, claude-3.5-sonnet)
# or bare family words. The identifier branch is first so a full token like
# "claude-3.5-sonnet" is consumed once instead of matching family words inside.
_MENTION_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+(?:\.[0-9]+)?)+"
    r"|\b(?:gpt|claude|glm|gemini|llama|mistral|qwen|deepseek|sonnet|opus|haiku|grok)\b",
    re.IGNORECASE,
)


def classify(candidate_text: str) -> str:
    """Heuristic typing: "rule" | "skill" | "learning"."""
    text = (candidate_text or "").strip()
    if not text:
        return "learning"
    if _RULE_RE.search(text):
        return "rule"
    if _TOOL_RE.search(text):
        return "skill"
    return "learning"


def detect_model_mentions(text: str, roster_names: Iterable[str]) -> List[str]:
    """Model-like names in text that are NOT in the roster (case-insensitive).

    Word-level regex match, first-occurrence order, deduplicated — used to
    flag roster auto-discovery candidates.
    """
    roster = {str(name).strip().lower() for name in roster_names}
    flagged: List[str] = []
    for match in _MENTION_RE.finditer(text or ""):
        token = match.group(0)
        if "-" in token and not any(ch.isdigit() for ch in token):
            continue  # plain hyphenated word ("state-dir"), not a model id
        if token.lower() in roster:
            continue
        if token.lower() not in [f.lower() for f in flagged]:
            flagged.append(token)
    return flagged


def append(candidate: dict, config: RouterConfig) -> bool:
    """Append one candidate to the pending-capture queue. NEVER raises.

    Returns True when the line landed, False when there was nothing to
    capture or the write failed (logged, turn continues; the candidate is
    recovered on the next drain).
    """
    try:
        text = str(candidate.get("text") or "").strip()
        if not candidate or not text:
            return False
        payload = dict(candidate.get("payload") or {})
        payload.setdefault("text", text)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": str(candidate.get("session") or ""),
            "kind": candidate.get("kind") or classify(text),
            "payload": payload,
            "turn_context": candidate.get("turn_context") or {},
        }
        path = config.state_path(*PENDING_REL)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception as e:  # routing already succeeded; never block the turn
        print(
            f"router capture: append failed ({type(e).__name__}: {e}); "
            "line recovered on next drain",
            file=sys.stderr,
        )
        return False

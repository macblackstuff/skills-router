"""Session memory + active-set (U6, KTD6, R7).

Per-session JSONL file under <state_dir>/sessions/<session_id>.jsonl. Each
appended entry is one turn:

    {"ts": <iso-8601 utc>, "turn_digest": <sha256 of prompt>,
     "prompt": <raw prompt text>, "injected": [qualified ids],
     "active_set": [{"id": ..., "turns_left": n}, ...]}

Active-set decay: every record_turn decrements turns_left on surviving entries
(default ttl 3 turns, dropped at 0), then arms/refreshes this turn's injected
ids at full ttl. An active capability stays resolvable for ttl subsequent
turns — a "continue" prompt resolves through memory without re-injection
(AE3) — and becomes re-injectable once it decays out.

context_state() assembles the Jev-facing state (prompt + transcript tail +
active-ids block); the caller runs jev.redact() over the result before
egress (KTD2). Corrupt or partially written JSONL lines are skipped, never
crash the turn (KTD4: session state rebuilds rather than crashes).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable, List

DEFAULT_TTL = 3    # turns an injected capability stays active without re-injection
ROLLING_LINES = 10  # rolling summary window: last-N turn prompts
TAIL_LINES = 5      # default transcript tail (last-K non-empty lines)


def transcript_tail(path: str | Path | None, k: int = TAIL_LINES) -> List[str]:
    """Last-k non-empty lines of a transcript; missing/unreadable -> []."""
    if not path:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-k:]


class SessionMemory:
    """Per-session JSONL turn log with active-set decay."""

    def __init__(self, state_dir: Path | str) -> None:
        self._sessions_dir = Path(state_dir).expanduser() / "sessions"

    def _path(self, session_id: str) -> Path:
        safe = str(session_id).replace("/", "_").replace("\\", "_")
        return self._sessions_dir / f"{safe}.jsonl"

    def _entries(self, session_id: str) -> List[dict]:
        """Parsed entries, corrupt/blank lines skipped (KTD4)."""
        try:
            text = self._path(session_id).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return []
        entries: List[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def load(self, session_id: str) -> dict:
        """Rolling summary (last ROLLING_LINES prompts) + current active ids."""
        entries = self._entries(session_id)
        prompts = [str(e["prompt"]) for e in entries if e.get("prompt")]
        active = entries[-1].get("active_set", []) if entries else []
        return {
            "rolling_summary_lines": prompts[-ROLLING_LINES:],
            "active_ids": [str(a["id"]) for a in active if a.get("id")],
        }

    def record_turn(
        self, session_id: str, prompt: str, injected_ids: Iterable[str] = ()
    ) -> dict:
        """Append this turn; decay the active set, arm/refresh injections.

        Decay runs before arming: entries surviving from the previous turn
        lose one turn (dropped at 0), then this turn's injected ids land at
        DEFAULT_TTL — refreshing an already-active id re-arms its full ttl.
        """
        entries = self._entries(session_id)
        previous = entries[-1].get("active_set", []) if entries else []
        active: dict[str, int] = {}
        for item in previous:
            left = int(item.get("turns_left", 0)) - 1
            rid = item.get("id")
            if left > 0 and rid:
                active[str(rid)] = left
        for rid in injected_ids:
            active[str(rid)] = DEFAULT_TTL

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "turn_digest": hashlib.sha256(str(prompt).encode("utf-8")).hexdigest(),
            "prompt": str(prompt),
            "injected": [str(rid) for rid in injected_ids],
            "active_set": [
                {"id": rid, "turns_left": left} for rid, left in active.items()
            ],
        }
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        with self._path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def context_state(
        self,
        prompt: str,
        session_id: str,
        transcript_path: str | Path | None = None,
        tail_k: int = TAIL_LINES,
    ) -> str:
        """Prompt + transcript tail + active-ids block, pre-redaction.

        The active-ids block is what lets Jev resolve a follow-up ("continue")
        to the already-injected capability instead of re-injecting it (R7).
        """
        state = f"PROMPT:\n{prompt}"
        tail = transcript_tail(transcript_path, k=tail_k)
        if tail:
            state += "\n\nTRANSCRIPT TAIL:\n" + "\n".join(tail)
        active_ids = self.load(session_id)["active_ids"]
        if active_ids:
            state += (
                "\n\nACTIVE CAPABILITIES (already injected this session; "
                "do not re-inject):\n"
                + "\n".join(f"- {rid}" for rid in active_ids)
            )
        return state

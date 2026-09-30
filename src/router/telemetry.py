"""Per-turn telemetry (U10, R11): one JSONL line per routed turn.

<state_dir>/telemetry/turns.jsonl carries the fields the U11 nightly judge
scores (R11: latency, cost, injection size, cache hit rate) plus a verdicts
digest for session-trace replay:

    {"ts": <iso-8601 utc>, "session": ..., "prompt_fingerprint": ...,
     "latency_ms": ..., "cost_usd": ..., "injection_count": ...,
     "cache_hit": ..., "verdicts_digest": ...}

append_turn NEVER raises (KTD11): the write is batched onto the turn's
success path after routing already succeeded, so a telemetry failure only
logs to stderr and returns None — the turn continues unrouted-telemetry but
routed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TURNS_REL = ("telemetry", "turns.jsonl")


def turns_path(state_dir: Path | str) -> Path:
    """<state_dir>/telemetry/turns.jsonl."""
    p = Path(state_dir).expanduser()
    for part in TURNS_REL:
        p = p / part
    return p


def digest(obj: Any) -> str:
    """sha256 over canonical JSON (sorted keys) — e.g. a verdicts digest."""
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_turn(state_dir: Path | str, entry: dict) -> dict | None:
    """Append one per-turn telemetry line; returns the written record or None.

    ``ts`` is added unless the caller supplied one. Never raises (KTD11):
    on any write failure the line is logged to stderr and None is returned —
    routing already succeeded, telemetry must not block the turn.
    """
    try:
        record = dict(entry)
        record.setdefault(
            "ts", datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        path = turns_path(state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
    except Exception as e:  # noqa: BLE001 — telemetry never blocks a turn
        print(
            f"router telemetry: append failed ({type(e).__name__}: {e}); "
            "turn continues without the line",
            file=sys.stderr,
        )
        return None

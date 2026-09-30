"""Roster auto-discovery (U9, R10/AE6): at index time, scan session
transcripts under ``<state_dir>/sessions/`` for model names that are absent
from the owner's roster, and append one flag per (model, transcript) to
``<state_dir>/captures/roster_flags.jsonl``:

    {"ts": ..., "model": ..., "count": ..., "transcript": "..."}

Detection reuses ``capture.detect_model_mentions``. Transcript lines are
JSONL-tolerant: a line that parses as JSON contributes its string values
(recursively), anything else contributes the raw line. Scanning never
raises — the index run must not fail because transcripts are unreadable.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from router import capture
from router.config import RouterConfig
from router.sources import roster as roster_source

FLAGS_REL = ("captures", "roster_flags.jsonl")
SESSIONS_DIRNAME = "sessions"


def _strings(node) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _line_text(line: str) -> str:
    s = line.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            return "\n".join(_strings(json.loads(s)))
        except (json.JSONDecodeError, ValueError):
            pass
    return line


def _transcript_text(path: Path) -> str:
    parts: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts.append(_line_text(line))
    return "\n".join(parts)


def scan(config: RouterConfig, roster_names: list[str] | None = None,
         transcripts_dir: str | Path | None = None) -> list[dict]:
    """Flag models named in transcripts but absent from the roster.

    Appends to ``captures/roster_flags.jsonl`` and returns the entries this
    call wrote (idempotent: a (model, transcript) pair is recorded once).
    """
    try:
        tdir = Path(transcripts_dir).expanduser() if transcripts_dir \
            else config.state_path(SESSIONS_DIRNAME)
        if not tdir.is_dir():
            return []
        if roster_names is None:
            if not config.roster_path:
                return []  # no roster to compare against -> discovery off
            roster_names = roster_source.names(config.roster_path)

        flags_path = config.state_path(*FLAGS_REL)
        seen: set[tuple[str, str]] = set()
        if flags_path.is_file():
            for line in flags_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    e = json.loads(line)
                    seen.add((str(e.get("model", "")).lower(), str(e.get("transcript", ""))))
                except json.JSONDecodeError:
                    continue

        out: list[dict] = []
        flags_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for tf in sorted(p for p in tdir.rglob("*") if p.is_file()):
            try:
                text = _transcript_text(tf)
            except OSError as e:
                print(f"router discovery: skip {tf} ({e})", file=sys.stderr)
                continue
            for model in capture.detect_model_mentions(text, roster_names or []):
                key = (model.lower(), str(tf))
                if key in seen:
                    continue
                n = len(re.findall(re.escape(model), text, re.IGNORECASE))
                entry = {"ts": now, "model": model, "count": n, "transcript": str(tf)}
                with flags_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                seen.add(key)
                out.append(entry)
        return out
    except Exception as e:  # additive step: never fail the index run
        print(f"router discovery: scan failed ({type(e).__name__}: {e})", file=sys.stderr)
        return []

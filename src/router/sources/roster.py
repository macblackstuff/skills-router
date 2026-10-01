"""Roster source: owner-maintained markdown -> model rows.

Recognized line shapes:
- bullets: `- Name — description` (em/en dash)
- table rows: `| Name | description |` (header + separator rows skipped)
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from router.sources._common import iso as _iso

from router.sources.rules import slug

_BULLET_RE = re.compile(r"^[-*]\s+(.+?)\s+[—–]\s+(.+)$")
_SEP_CELL_RE = re.compile(r"^[\s:\-|]+$")


def _table_cells(line: str) -> list[str] | None:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")) or len(s) < 2:
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def iter_rows(path: str | Path, type_name: str = "model") -> list[dict]:
    p = Path(path).expanduser()
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    st = p.stat()
    rows: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        name = desc = None
        m = _BULLET_RE.match(s)
        if m:
            name, desc = m.group(1), m.group(2)
        elif s.startswith("|"):
            cells = _table_cells(s)
            nxt = _table_cells(lines[i + 1]) if i + 1 < len(lines) else None
            is_separator = bool(nxt) and all(
                _SEP_CELL_RE.match(c or "-") for c in nxt if c != ""
            )
            if cells and is_separator:
                i += 2  # header row + separator
                continue
            if cells and not all(_SEP_CELL_RE.match(c or "-") for c in cells if c):
                if len(cells) >= 2 and cells[0]:
                    name, desc = cells[0], cells[1]
        i += 1
        if not name or not desc:
            continue
        rows.append({
            "id": slug(name),
            "name": name,
            "description": desc,
            "trigger_terms": desc,
            "path": str(p),
            "source": str(p),
            "version": None,
            "content_hash": hashlib.sha256(line.encode("utf-8", "replace")).hexdigest(),
            "last_verified": _iso(st.st_mtime),
            "enabled": 1,
            "extras": json.dumps({"line": i}),
            "_mtime": st.st_mtime,
        })
    return rows


def names(path: str | Path) -> list[str]:
    """Model names only — used by discovery to compare against transcripts."""
    return [str(r["name"]) for r in iter_rows(path)]

"""Memories source: memory notes -> memory rows.

One row per ``*.md`` file under the configured roots (recursive, like the
knowledge adapter). Name comes from frontmatter ``name``, else the first H1,
else the file stem; description is the first paragraph after the title.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from router.sources.rules import first_paragraph, strip_frontmatter
from router.sources.skills import parse_frontmatter

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")


def _title_and_body(text: str) -> tuple[str | None, str]:
    """Split off a leading H1 title, returning (title_or_None, remaining)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = _H1_RE.match(line.strip())
        if m:
            return m.group(1).strip(), "\n".join(lines[:i] + lines[i + 1:])
        break
    return None, text


def iter_rows(dirs: list[str | Path], type_name: str = "memory") -> list[dict]:
    files: list[Path] = []
    for d in dirs:
        root = Path(d).expanduser()
        if root.is_dir():
            files.extend(sorted(root.rglob("*.md")))
        elif root.is_file():
            files.append(root)
    rows: list[dict] = []
    for f in files:
        raw = f.read_bytes()
        text = strip_frontmatter(raw.decode("utf-8", "replace"))
        fm = parse_frontmatter(raw.decode("utf-8", "replace"))
        h1, body = _title_and_body(text)
        name = str(fm.get("name") or h1 or f.stem)
        description = first_paragraph(body)
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        version = meta.get("version") or fm.get("version")
        st = f.stat()
        rows.append({
            "id": f.stem,
            "name": name,
            "description": description,
            "trigger_terms": description,  # description doubles as triggers
            "path": str(f),
            "source": str(f.parent),
            "version": str(version) if version not in (None, "") else None,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "last_verified": _iso(st.st_mtime),
            "enabled": 1,
            "extras": json.dumps({"file": f.name, "topic": h1 or f.stem}),
            "_mtime": st.st_mtime,
        })
    return rows

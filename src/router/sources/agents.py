"""Agents source: agent-definition markdown -> agent rows.

One row per ``*.md`` file at the top level of each configured dir (a directly
listed file also counts). Frontmatter uses the small YAML subset parsed by
skills.parse_frontmatter: ``name``, ``description``, optional ``model``,
``tools`` (comma-separated or list) and ``metadata.version``. Files without
frontmatter fall back to stem + first paragraph.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from router.sources.rules import first_paragraph, strip_frontmatter
from router.sources.skills import parse_frontmatter


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")


def _files(dirs: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        p = Path(d).expanduser()
        if p.is_dir():
            out.extend(sorted(q for q in p.iterdir()
                              if q.is_file() and q.suffix == ".md"))
        elif p.is_file():
            out.append(p)
    return out


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if v in (None, ""):
        return []
    return [s.strip() for s in str(v).split(",") if s.strip()]


def iter_rows(dirs: list[str | Path], type_name: str = "agent") -> list[dict]:
    rows: list[dict] = []
    for f in _files(dirs):
        raw = f.read_bytes()
        text = raw.decode("utf-8", "replace")
        fm = parse_frontmatter(text)
        body = strip_frontmatter(text)
        name = str(fm.get("name") or f.stem)
        description = str(fm.get("description") or "") or first_paragraph(body)
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        version = meta.get("version") or fm.get("version")
        model = fm.get("model")
        st = f.stat()
        rows.append({
            "id": name,
            "name": name,
            "description": description,
            "trigger_terms": description,  # description doubles as triggers
            "path": str(f),
            "source": str(f.parent),
            "version": str(version) if version not in (None, "") else None,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "last_verified": _iso(st.st_mtime),
            "enabled": 1,
            "extras": json.dumps({
                "file": f.name,
                "model": str(model) if model not in (None, "") else None,
                "tools": _as_list(fm.get("tools")),
            }),
            "_mtime": st.st_mtime,
        })
    return rows

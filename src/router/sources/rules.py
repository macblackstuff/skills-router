"""Rules source: markdown rule files -> rule rows (heading = name, first
paragraph after the heading = description). Accepts files or directories
(scanned recursively for *.md).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from router.sources._common import content_hash, iso as _iso

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def slug(text: str, limit: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].rstrip("-") or "section"


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1:])
    return text


def split_headings(text: str) -> list[tuple[str, int, str]]:
    """Return (heading, level, body-including-heading-line) per heading."""
    sections: list[tuple[str, int, list[str]]] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            sections.append((m.group(2), len(m.group(1)), [line]))
        elif sections:
            sections[-1][2].append(line)
    return [(h, lvl, "\n".join(body).strip("\n")) for h, lvl, body in sections]


def first_paragraph(text: str) -> str:
    para: list[str] = []
    for line in text.splitlines():
        if line.strip():
            para.append(line.strip())
        elif para:
            break
    return " ".join(para)


def iter_rows(paths: list[str | Path], type_name: str = "rule") -> list[dict]:
    files: list[Path] = []
    for p in paths:
        q = Path(p).expanduser()
        if q.is_dir():
            files.extend(sorted(q.rglob("*.md")))
        elif q.is_file():
            files.append(q)
    rows: list[dict] = []
    for f in files:
        raw = f.read_bytes()
        text = strip_frontmatter(raw.decode("utf-8", "replace"))
        st = f.stat()
        base = {
            "path": str(f),
            "source": str(f.parent),
            "version": None,
            "last_verified": _iso(st.st_mtime),
            "enabled": 1,
            "_mtime": st.st_mtime,
        }
        sections = split_headings(text)
        if not sections:
            if text.strip():
                rows.append({
                    "id": f.stem, "name": f.stem,
                    "description": first_paragraph(text),
                    **base,
                    "trigger_terms": first_paragraph(text),
                    "content_hash": content_hash(raw),
                    "extras": json.dumps({"file": f.name, "level": 0}),
                })
            continue
        for heading, level, body in sections:
            description = first_paragraph("\n".join(body.splitlines()[1:])) or heading
            rows.append({
                "id": f"{f.stem}:{slug(heading)}",
                "name": heading,
                "description": description,
                "trigger_terms": description,
                **base,
                "content_hash": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(),
                "extras": json.dumps({"file": f.name, "level": level}),
            })
    return rows

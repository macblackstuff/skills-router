"""Knowledge source: brain-vault pages -> page/section outline rows.

One row per `##` section (KTD8): id `page#section`, name = section heading,
description = first sentence (<=200 chars), extras carry {page, heading_path,
body (verbatim), body_hash}. Heading-less pages emit a single page-level row.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from router.sources.rules import slug, strip_frontmatter

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")


def first_sentence(text: str, limit: int = 200) -> str:
    s = " ".join(text.split())
    if not s:
        return ""
    for i, ch in enumerate(s):
        if ch in ".!?" and (i + 1 == len(s) or s[i + 1] == " "):
            return s[: i + 1][:limit]
    return s[:limit]


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")


def _sections(text: str) -> tuple[str, list[tuple[str | None, list[str]]]]:
    """Return (page_title, [(section_heading_or_None, body_lines)])."""
    page_title = ""
    sections: list[tuple[str | None, list[str]]] = []
    for line in text.splitlines():
        m1 = _H1_RE.match(line)
        if m1:
            page_title = m1.group(1)
            continue
        m2 = _H2_RE.match(line)
        if m2:
            sections.append((m2.group(1), [line]))
        elif sections:
            sections[-1][1].append(line)
    return page_title, sections


def iter_rows(dirs: list[str | Path], type_name: str = "knowledge") -> list[dict]:
    files: list[Path] = []
    for d in dirs:
        root = Path(d).expanduser()
        if root.is_dir():
            files.extend(sorted(root.rglob("*.md")))
    rows: list[dict] = []
    for f in files:
        raw = f.read_bytes()
        text = strip_frontmatter(raw.decode("utf-8", "replace"))
        page_title, sections = _sections(text)
        page_title = page_title or f.stem
        st = f.stat()
        if not sections:
            body = text.strip("\n")
            if body.strip():
                body_hash = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
                prose = "\n".join(l for l in text.splitlines() if not _H1_RE.match(l))
                rows.append({
                    "id": f"{f.stem}#page",
                    "name": page_title,
                    "description": first_sentence(prose),
                    "trigger_terms": first_sentence(prose),
                    "path": str(f),
                    "source": str(f.parent),
                    "version": None,
                    "content_hash": body_hash,
                    "last_verified": _iso(st.st_mtime),
                    "enabled": 1,
                    "extras": json.dumps({
                        "page": page_title,
                        "heading_path": page_title,
                        "body": body,
                        "body_hash": body_hash,
                    }),
                    "_mtime": st.st_mtime,
                })
            continue
        used_ids: set[str] = set()
        for heading, body_lines in sections:
            body = "\n".join(body_lines).strip("\n")
            body_hash = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
            base_id = f"{f.stem}#{slug(heading)}"
            row_id, n = base_id, 1
            while row_id in used_ids:
                n += 1
                row_id = f"{base_id}-{n}"
            used_ids.add(row_id)
            heading_path = f"{page_title} > {heading}"
            summary = first_sentence("\n".join(body_lines[1:]))
            rows.append({
                "id": row_id,
                "name": heading,
                "description": summary,
                "trigger_terms": summary,
                "path": str(f),
                "source": str(f.parent),
                "version": None,
                "content_hash": body_hash,
                "last_verified": _iso(st.st_mtime),
                "enabled": 1,
                "extras": json.dumps({
                    "page": page_title,
                    "heading_path": heading_path,
                    "body": body,
                    "body_hash": body_hash,
                }),
                "_mtime": st.st_mtime,
            })
    return rows

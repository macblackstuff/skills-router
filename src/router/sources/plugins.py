"""Plugins source: plugin directories with plugin.md frontmatter -> plugin rows.

Mirrors the skills adapter: one level of subdirs under each configured root;
a subdir counts as a plugin when it holds ``plugin.md`` (or ``PLUGIN.md``)
whose frontmatter uses the small YAML subset parsed by skills.parse_frontmatter.
"""
from __future__ import annotations

import json
from pathlib import Path

from router.sources._common import content_hash, iso as _iso

from router.sources.skills import parse_frontmatter


def _plugin_md(d: Path) -> Path | None:
    for name in ("plugin.md", "PLUGIN.md"):
        p = d / name
        if p.is_file():
            return p
    return None


def iter_rows(dirs: list[str | Path], type_name: str = "plugin") -> list[dict]:
    rows: list[dict] = []
    for d in dirs:
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for sd in sorted(root.iterdir()):
            if not sd.is_dir():
                continue
            plugin_md = _plugin_md(sd)
            if plugin_md is None:
                continue
            raw = plugin_md.read_bytes()
            fm = parse_frontmatter(raw.decode("utf-8", "replace"))
            name = str(fm.get("name") or sd.name)
            description = str(fm.get("description") or "")
            meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
            version = meta.get("version") or fm.get("version")
            st = plugin_md.stat()
            rows.append({
                "id": name,
                "name": name,
                "description": description,
                "trigger_terms": description,  # description doubles as triggers
                "path": str(plugin_md),
                "source": str(root),
                "version": str(version) if version not in (None, "") else None,
                "content_hash": content_hash(raw),
                "last_verified": _iso(st.st_mtime),
                "enabled": 1,
                "extras": json.dumps({"dir": sd.name}),
                "_mtime": st.st_mtime,
            })
    return rows

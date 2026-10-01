"""MCP source: MCP server config JSON files -> mcp rows (one per server).

Accepts the cross-harness ``{"mcpServers": {...}}`` shape or a bare
``{name: {...}}`` map. Each configured path may be a directory (its
top-level ``*.json`` files are read) or a JSON file directly. Malformed
files are skipped, never raised.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from router.sources._common import iso as _iso

from router.sources.rules import slug


def _servers(raw) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("mcpServers")
    if isinstance(inner, dict):
        return {k: v for k, v in inner.items() if isinstance(v, dict)}
    if raw and all(isinstance(v, dict) for v in raw.values()):
        return raw
    return {}


def _files(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        q = Path(p).expanduser()
        if q.is_dir():
            out.extend(sorted(q.glob("*.json")))
        elif q.is_file():
            out.append(q)
    return out


def iter_rows(paths: list[str | Path], type_name: str = "mcp") -> list[dict]:
    rows: list[dict] = []
    for f in _files(paths):
        try:
            raw = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        st = f.stat()
        for name, spec in _servers(raw).items():
            command = str(spec.get("command") or "")
            args = [str(a) for a in spec.get("args") or []]
            url = str(spec.get("url") or "")
            description = str(spec.get("description") or "")
            if not description:
                description = " ".join([command] + args).strip() or url or name
            transport = "http" if (url and not command) else "stdio"
            rows.append({
                "id": slug(name),
                "name": name,
                "description": description,
                "trigger_terms": description,  # description doubles as triggers
                "path": str(f),
                "source": str(f.parent),
                "version": str(spec["version"]) if spec.get("version") not in (None, "") else None,
                "content_hash": hashlib.sha256(
                    json.dumps(spec, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "last_verified": _iso(st.st_mtime),
                "enabled": 1,
                "extras": json.dumps({
                    "command": command or None,
                    "args": args,
                    "url": url or None,
                    "transport": transport,
                    "file": f.name,
                }),
                "_mtime": st.st_mtime,
            })
    return rows

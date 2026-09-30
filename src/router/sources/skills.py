"""Skills source: skill directories with SKILL.md frontmatter -> skill rows.

Frontmatter parsing uses a deliberately small YAML subset (stdlib only):
`key: value` lines, one nesting level (`metadata:` + indented `version:`),
quoted scalars, and folded (`>-`) / literal (`|`) block scalars.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

_KEY_RE = re.compile(r"^(\s*)([A-Za-z0-9_.\- ]+?):\s*(.*)$")
_FOLDED = (">", ">-", ">", "|", "|-")  # block scalar introducers


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    top_key: str | None = None
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = _KEY_RE.match(line)
        if not m:
            i += 1
            continue
        indent, key, val = m.group(1), m.group(2).strip(), m.group(3).strip()
        if val in _FOLDED or val[:1] in (">", "|"):
            # block scalar: collect following indented/blank lines
            parts: list[str] = []
            j = i + 1
            base = len(indent)
            while j < len(lines) and lines[j].strip() != "---":
                nxt = lines[j]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= base:
                    break
                if nxt.strip():
                    parts.append(nxt.strip())
                j += 1
            value: object = " ".join(parts)
            i = j
        else:
            value = _scalar(val)
            i += 1
        if not indent:
            fm[key] = value
            top_key = key
        elif top_key:
            holder = fm[top_key] if isinstance(fm[top_key], dict) else {}
            fm[top_key] = holder
            holder[key] = value
    return fm


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")


def iter_rows(dirs: list[str | Path], type_name: str = "skill") -> list[dict]:
    rows: list[dict] = []
    for d in dirs:
        root = Path(d).expanduser()
        if not root.is_dir():
            continue
        for sd in sorted(root.iterdir()):
            skill_md = sd / "SKILL.md"
            if not sd.is_dir() or not skill_md.is_file():
                continue
            raw = skill_md.read_bytes()
            fm = parse_frontmatter(raw.decode("utf-8", "replace"))
            name = str(fm.get("name") or sd.name)
            description = str(fm.get("description") or "")
            meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
            version = meta.get("version")
            st = skill_md.stat()
            rows.append({
                "id": name,
                "name": name,
                "description": description,
                "trigger_terms": description,  # simple: description doubles as triggers
                "path": str(skill_md),
                "source": str(root),
                "version": str(version) if version not in (None, "") else None,
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "last_verified": _iso(st.st_mtime),
                "enabled": 1,
                "extras": json.dumps({"dir": sd.name}),
                "_mtime": st.st_mtime,
            })
    return rows

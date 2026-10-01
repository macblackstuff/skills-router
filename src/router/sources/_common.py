"""Shared helpers for source adapters (extracted from per-file duplicates)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds")


def content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def md_files(dirs: list[str | Path], names: tuple[str, ...] = ("README.md", "readme.md")) -> list[Path]:
    """Markdown files under each dir (top level), for dir-shaped sources."""
    out: list[Path] = []
    for d in dirs:
        d = Path(d).expanduser()
        if d.is_dir():
            for name in names:
                p = d / name
                if p.is_file():
                    out.append(p)
    return out

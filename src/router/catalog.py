"""Typed catalog: one SQLite file, one table per capability type + relations.

The catalog is derived-only (R13/KTD11): rows arrive via the indexer, never by
hand. Migration model is recreate — the fingerprint keys cache invalidation.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

CORE_TYPES = (
    "skill",
    "rule",
    "knowledge",
    "model",
    "file_location",
    "plugin",
    "agent",
    "memory",
    "mcp",
)


def core_columns() -> tuple[str, ...]:
    return (
        "id TEXT PRIMARY KEY",
        "subtype TEXT",
        "name TEXT NOT NULL",
        "description TEXT",
        "trigger_terms TEXT",
        "path TEXT",
        "source TEXT",
        "version TEXT",
        "content_hash TEXT",
        "last_verified TEXT",
        "enabled INTEGER NOT NULL DEFAULT 1",
        "extras TEXT",  # JSON
    )


class Catalog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def close(self) -> None:
        self.db.close()

    # -- schema ---------------------------------------------------------

    def _ensure_schema(self) -> None:
        for t in CORE_TYPES:
            self._create_type_table(t)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS relations ("
            "from_id TEXT, to_id TEXT, kind TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.db.commit()

    def _create_type_table(self, t: str) -> None:
        cols = ", ".join(core_columns())
        self.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({cols})")

    def ensure_type(self, t: str) -> None:
        """Auto-create a custom type with the same core contract (R4)."""
        self._create_type_table(t)
        self.db.commit()

    # -- rows ------------------------------------------------------------

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self.db.execute(sql, params).fetchall()

    def count(self, table: str) -> int:
        return int(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def upsert(self, table: str, row: dict) -> None:
        cols = [c.split()[0] for c in core_columns()]
        provided = [c for c in cols if c in row]
        vals = [row.get(c) for c in provided]
        placeholders = ", ".join("?" for _ in provided)
        updates = ", ".join(f"{c}=excluded.{c}" for c in provided if c != "id")
        sql = (
            f"INSERT INTO {table} ({', '.join(provided)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        self.db.execute(sql, vals)
        self.db.commit()

    # -- fingerprint -----------------------------------------------------

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for (name,) in sorted(
            self.rows("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ):
            h.update(name.encode())
            try:
                count = self.count(name)
            except sqlite3.DatabaseError:
                continue
            h.update(str(count).encode())
            for r in self.rows(f"SELECT * FROM {name} ORDER BY 1 LIMIT 5000"):
                h.update(repr(r).encode())
        return h.hexdigest()

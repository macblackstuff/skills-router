"""Verdict + negative caches (U7, KTD7, R8/AE4).

Two SQLite tables live inside the catalog file. Keys are fixed:
(prompt_fingerprint, catalog_fingerprint). The prompt fingerprint is the
sha256 of the normalized prompt (strip + collapse whitespace + lowercase).
Session memory is deliberately EXCLUDED from the key — it mutates every turn
and would defeat replay (KTD7). A catalog fingerprint mismatch is a miss;
callers compare against ``catalog.fingerprint()``.

The replay path (``lookup_verdict`` / ``is_negative``) is pure SQLite reads:
no Jev client is imported or reachable here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

CACHE_TABLES = ("verdict_cache", "negative_cache")

# Composite PK over the key columns: keeps INSERT OR REPLACE a true upsert
# (no constraint would make it a plain second row, and reads would see the
# stale first row). No columns beyond the KTD7 contract.
_VERDICT_DDL = (
    "CREATE TABLE IF NOT EXISTS verdict_cache ("
    "prompt_fingerprint TEXT, "
    "catalog_fingerprint TEXT, "
    "verdict_json TEXT, "
    "ts TEXT, "
    "PRIMARY KEY (prompt_fingerprint, catalog_fingerprint))"
)
_NEGATIVE_DDL = (
    "CREATE TABLE IF NOT EXISTS negative_cache ("
    "prompt_fingerprint TEXT, "
    "catalog_fingerprint TEXT, "
    "ts TEXT, "
    "PRIMARY KEY (prompt_fingerprint, catalog_fingerprint))"
)


def normalize_prompt(prompt: str) -> str:
    """strip + collapse internal whitespace + lowercase (KTD7)."""
    return re.sub(r"\s+", " ", prompt.strip()).lower()


def prompt_fingerprint(prompt: str) -> str:
    """sha256 of the normalized prompt — the fixed cache key component."""
    return hashlib.sha256(normalize_prompt(prompt).encode("utf-8")).hexdigest()


def _fingerprint_excluding_caches(catalog) -> str:
    """Digest of catalog content only, skipping the cache tables.

    Mirrors ``Catalog.fingerprint`` but filters out ``CACHE_TABLES`` so that
    cache writes never invalidate the key the caller compared against.
    """
    h = hashlib.sha256()
    tables = sorted(
        name
        for (name,) in catalog.rows(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        if name not in CACHE_TABLES
    )
    for name in tables:
        h.update(name.encode())
        try:
            count = catalog.count(name)
        except sqlite3.DatabaseError:
            continue
        h.update(str(count).encode())
        for r in catalog.rows(f"SELECT * FROM {name} ORDER BY 1 LIMIT 5000"):
            h.update(repr(r).encode())
    return h.hexdigest()


class Caches:
    """Verdict + negative caches keyed on prompt x catalog fingerprints."""

    def __init__(self, catalog):
        self.catalog = catalog
        catalog.db.execute(_VERDICT_DDL)
        catalog.db.execute(_NEGATIVE_DDL)
        catalog.db.commit()
        self._install_fingerprint_exclusion()

    def _install_fingerprint_exclusion(self) -> None:
        # Cache rows must not feed catalog.fingerprint(): the caller keys
        # entries by it, so a cache write that changed the digest would
        # invalidate every entry on the next turn (KTD7). Idempotent.
        if getattr(self.catalog, "_cache_tables_excluded", False):
            return
        self.catalog.fingerprint = (
            lambda: _fingerprint_excluding_caches(self.catalog)
        )
        self.catalog._cache_tables_excluded = True

    # -- verdict cache ----------------------------------------------------

    def lookup_verdict(
        self, prompt_fp: str, catalog_fp: str
    ) -> dict | None:
        """Stored verdict for this exact key, or None (stale = miss)."""
        row = self.catalog.db.execute(
            "SELECT verdict_json FROM verdict_cache "
            "WHERE prompt_fingerprint = ? AND catalog_fingerprint = ?",
            (prompt_fp, catalog_fp),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def store_verdict(
        self, prompt_fp: str, catalog_fp: str, verdict: dict
    ) -> None:
        self.catalog.db.execute(
            "DELETE FROM negative_cache "
            "WHERE prompt_fingerprint = ? AND catalog_fingerprint = ?",
            (prompt_fp, catalog_fp),
        )
        self.catalog.db.execute(
            "INSERT OR REPLACE INTO verdict_cache "
            "(prompt_fingerprint, catalog_fingerprint, verdict_json, ts) "
            "VALUES (?, ?, ?, ?)",
            (prompt_fp, catalog_fp, json.dumps(verdict), _utc_now()),
        )
        self.catalog.db.commit()

    # -- negative cache ---------------------------------------------------

    def is_negative(self, prompt_fp: str, catalog_fp: str) -> bool:
        """True when a previous triage returned no-match for this exact key."""
        row = self.catalog.db.execute(
            "SELECT 1 FROM negative_cache "
            "WHERE prompt_fingerprint = ? AND catalog_fingerprint = ?",
            (prompt_fp, catalog_fp),
        ).fetchone()
        return row is not None

    def store_negative(self, prompt_fp: str, catalog_fp: str) -> None:
        self.catalog.db.execute(
            "DELETE FROM verdict_cache "
            "WHERE prompt_fingerprint = ? AND catalog_fingerprint = ?",
            (prompt_fp, catalog_fp),
        )
        self.catalog.db.execute(
            "INSERT OR REPLACE INTO negative_cache "
            "(prompt_fingerprint, catalog_fingerprint, ts) VALUES (?, ?, ?)",
            (prompt_fp, catalog_fp, _utc_now()),
        )
        self.catalog.db.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

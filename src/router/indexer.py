"""Indexer (U2): configured sources -> deduped typed catalog + precomputed
worker shards + catalog fingerprint.

Dedupe (G18): equal content_hash -> newest mtime wins; older copies stay as
alias rows (id + "-alias", enabled=0) so provenance is not lost.

Shards (R3/R8): enabled rows per type are packed into token-budgeted shards
(~3000 tokens at ~4 chars/token) with ~10% overlap between consecutive
shards, stored ready-to-send in meta key "shards:<type>". The catalog
fingerprint is emitted into meta key "catalog_fingerprint" (computed over
rows + shards, before the fingerprint row itself is written, so unchanged
sources yield an unchanged fingerprint across runs).

Custom types index without code change: declare in the router TOML

    [sources.types.<name>]
    adapter = "skills" | "rules" | "knowledge" | "roster"
           | "plugins" | "agents" | "memories" | "mcp"
    dirs = ["/path", ...]     # or path = "/file.md" for roster

Tuning sidecars (U11/R11): <state_dir>/tuning/*.toml (written by the nightly
judge) override row fields at index time — the catalog stays derived-only and
a recreate migration re-applies them from the files:

    capability_id = "..."
    [[override]]
    field = "description" | "trigger_terms"
    old = "..."   # skipped when it no longer matches the source row
    new = "..."
    rationale = "..."

CLI: python3 -m router.indexer --config <path>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from router import discovery
from router.catalog import Catalog
from router.config import ConfigError, RouterConfig
from router.sources import agents as agents_source
from router.sources import knowledge as knowledge_source
from router.sources import mcp as mcp_source
from router.sources import memories as memories_source
from router.sources import plugins as plugins_source
from router.sources import roster as roster_source
from router.sources import rules as rules_source
from router.sources import skills as skills_source

BUDGET_TOKENS = 3000
CHARS_PER_TOKEN = 4
OVERLAP_FRACTION = 0.10
FINGERPRINT_KEY = "catalog_fingerprint"
DEFAULT_CONFIG = "~/.config/router/router.toml"


class IndexerError(Exception):
    pass


@dataclass
class IndexResult:
    fingerprint: str
    counts: dict[str, int] = field(default_factory=dict)
    alias_counts: dict[str, int] = field(default_factory=dict)
    shard_counts: dict[str, int] = field(default_factory=dict)


# -- source collection --------------------------------------------------------

def collect_rows(config: RouterConfig, custom_sources: dict[str, list[dict]] | None = None
                 ) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if config.skill_dirs:
        out["skill"] = skills_source.iter_rows(config.skill_dirs)
    if config.vault_rules:
        out["rule"] = rules_source.iter_rows(config.vault_rules)
    if config.brain_vaults:
        out["knowledge"] = knowledge_source.iter_rows(config.brain_vaults)
    if config.roster_path:
        out["model"] = roster_source.iter_rows(config.roster_path)
    for type_name, rows in (custom_sources or {}).items():
        out[type_name] = list(rows)
    return out


_ADAPTERS = {
    "skills": lambda spec, t: skills_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
    "rules": lambda spec, t: rules_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
    "knowledge": lambda spec, t: knowledge_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
    "roster": lambda spec, t: roster_source.iter_rows(spec["path"], type_name=t),
    "plugins": lambda spec, t: plugins_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
    "agents": lambda spec, t: agents_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
    "memories": lambda spec, t: memories_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
    "mcp": lambda spec, t: mcp_source.iter_rows(list(spec.get("dirs", [])), type_name=t),
}


def load_custom_sources(config_path: Path | str) -> dict[str, list[dict]]:
    """Read [sources.types.<name>] tables from the router TOML."""
    p = Path(config_path).expanduser()
    if not p.is_file():
        return {}
    raw = tomllib.loads(p.read_text())
    types = (raw.get("sources") or {}).get("types") or {}
    out: dict[str, list[dict]] = {}
    for type_name, spec in types.items():
        adapter = str(spec.get("adapter", "skills"))
        if adapter not in _ADAPTERS:
            raise IndexerError(f"unknown adapter {adapter!r} for custom type {type_name!r}")
        out[type_name] = _ADAPTERS[adapter](spec, type_name)
    return out


# -- tuning sidecar merge (U11/R11) -------------------------------------------------

TUNING_FIELDS = ("description", "trigger_terms")


def load_tuning(tuning_dir: Path | str | None) -> dict[str, list[dict]]:
    """Read tuning/*.toml sidecars -> {capability_id: [override, ...]}."""
    if not tuning_dir:
        return {}
    d = Path(tuning_dir).expanduser()
    if not d.is_dir():
        return {}
    out: dict[str, list[dict]] = {}
    for f in sorted(d.glob("*.toml")):
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            print(f"router index: tuning {f.name} unreadable ({e})", file=sys.stderr)
            continue
        cid = str(data.get("capability_id", "")).strip()
        overrides = data.get("override", [])
        if cid and isinstance(overrides, list):
            out.setdefault(cid, []).extend(o for o in overrides if isinstance(o, dict))
    return out


def apply_tuning(rows: list[dict], overrides: dict[str, list[dict]]) -> int:
    """Apply field overrides to matching rows in place; returns applied count.

    An override whose ``old`` no longer matches the row (source changed since
    the proposal) is skipped — tuning must never clobber a fresh source edit.
    """
    by_id = {r["id"]: r for r in rows}
    applied = 0
    for cid, items in overrides.items():
        row = by_id.get(cid)
        if row is None:
            continue
        for o in items:
            fld = str(o.get("field", ""))
            if fld not in TUNING_FIELDS:
                continue
            old = o.get("old")
            if old is not None and str(old) != str(row.get(fld, "")):
                print(
                    f"router index: tuning override for {cid}.{fld} skipped "
                    "(old value no longer matches source)",
                    file=sys.stderr,
                )
                continue
            row[fld] = str(o.get("new", ""))
            applied += 1
    return applied


# -- dedupe (G18) ---------------------------------------------------------------

def dedupe(rows: list[dict]) -> tuple[list[dict], int]:
    """Equal content_hash: newest mtime wins; losers become disabled aliases."""
    by_hash: dict[str, list[dict]] = {}
    for r in rows:
        by_hash.setdefault(r["content_hash"], []).append(r)
    result: list[dict] = []
    aliases = 0
    for group in by_hash.values():
        if len(group) == 1:
            result.extend(group)
            continue
        group.sort(key=lambda r: (r.get("_mtime", 0.0), str(r.get("path", ""))), reverse=True)
        winner = group[0]
        result.append(winner)
        used = {winner["id"]}
        for loser in group[1:]:
            new_id = f"{loser['id']}-alias"
            n = 2
            while new_id in used:
                new_id = f"{loser['id']}-alias-{n}"
                n += 1
            used.add(new_id)
            result.append({**loser, "id": new_id, "enabled": 0})
            aliases += 1
    return result, aliases


def unique_ids(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        rid = r["id"]
        if rid in seen:
            n = 2
            while f"{rid}-{n}" in seen:
                n += 1
            rid = f"{rid}-{n}"
            r = {**r, "id": rid}
        seen.add(rid)
        out.append(r)
    return out


# -- shard packing (R3/R8) --------------------------------------------------------

def descriptor(row: dict) -> str:
    name = " ".join((row.get("name") or row["id"]).split())
    desc = " ".join((row.get("description") or "").split())
    if len(desc) > 240:
        desc = desc[:237] + "..."
    line = f"{row['id']} | {name} | {desc}"
    trig = " ".join((row.get("trigger_terms") or "").split())
    if trig and trig != desc:
        line += f" | kw: {trig[:120]}"
    return line


def pack_shards(rows: list[dict], budget_tokens: int = BUDGET_TOKENS,
                chars_per_token: int = CHARS_PER_TOKEN,
                overlap_fraction: float = OVERLAP_FRACTION) -> dict:
    """Pack option descriptors into token-budgeted shards with ~10% overlap.

    Overlap carries the trailing ~10% of the previous shard's items (at least
    one, never all — every shard adds at least one new item).
    """
    budget_chars = budget_tokens * chars_per_token
    items = [(r["id"], descriptor(r)) for r in rows]
    shards: list[dict] = []
    prev: list[tuple[str, str]] = []
    i = 0
    while i < len(items):
        ids: list[str] = []
        descs: list[str] = []
        size = 0
        if len(prev) >= 2:
            n_overlap = min(len(prev) - 1, max(1, math.ceil(len(prev) * overlap_fraction)))
            for rid, d in prev[-n_overlap:]:
                ids.append(rid)
                descs.append(d)
                size += len(d) + 1
        while i < len(items):
            rid, d = items[i]
            if descs and size + len(d) + 1 > budget_chars:
                break
            ids.append(rid)
            descs.append(d)
            size += len(d) + 1
            i += 1
        shards.append({
            "i": len(shards),
            "ids": ids,
            "text": "\n".join(descs),
            "chars": size,
            "est_tokens": (size + chars_per_token - 1) // chars_per_token,
        })
        prev = list(zip(ids, descs))
    return {
        "budget_tokens": budget_tokens,
        "chars_per_token": chars_per_token,
        "overlap_fraction": overlap_fraction,
        "count": len(items),
        "shards": shards,
    }


# -- orchestration ----------------------------------------------------------------

def run_index(config: RouterConfig, catalog: Catalog | None = None,
              custom_sources: dict[str, list[dict]] | None = None,
              budget_tokens: int = BUDGET_TOKENS,
              chars_per_token: int = CHARS_PER_TOKEN,
              overlap_fraction: float = OVERLAP_FRACTION,
              tuning_dir: Path | str | None = None) -> IndexResult:
    rows_by_type = collect_rows(config, custom_sources)
    # U11 tuning sidecars (default <state_dir>/tuning): applied before dedupe
    # so overrides flow into rows, descriptors and the fingerprint.
    overrides = load_tuning(
        config.state_path("tuning") if tuning_dir is None else tuning_dir
    )
    if overrides:
        for type_rows in rows_by_type.values():
            apply_tuning(type_rows, overrides)
    own = catalog is None
    if own:
        state = config.state_path("catalog.db")
        state.parent.mkdir(parents=True, exist_ok=True)
        catalog = Catalog(state)
    assert catalog is not None
    result = IndexResult(fingerprint="")
    for type_name in sorted(rows_by_type):
        rows, n_alias = dedupe(rows_by_type[type_name])
        rows = unique_ids(rows)
        catalog.ensure_type(type_name)
        catalog.db.execute(f"DELETE FROM {type_name}")  # catalog is derived-only
        for r in rows:
            catalog.upsert(type_name, r)
        enabled = sorted((r for r in rows if r.get("enabled", 1)), key=lambda r: r["id"])
        packed = pack_shards(enabled, budget_tokens=budget_tokens,
                             chars_per_token=chars_per_token, overlap_fraction=overlap_fraction)
        catalog.db.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"shards:{type_name}", json.dumps(packed, ensure_ascii=False)),
        )
        result.counts[type_name] = len(rows)
        result.alias_counts[type_name] = n_alias
        result.shard_counts[type_name] = len(packed["shards"])
    # Fingerprint over rows + shards; the previous fingerprint row must not
    # feed its own successor, so drop it before hashing.
    catalog.db.execute("DELETE FROM meta WHERE key=?", (FINGERPRINT_KEY,))
    catalog.db.commit()
    result.fingerprint = catalog.fingerprint()
    catalog.db.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (FINGERPRINT_KEY, result.fingerprint),
    )
    catalog.db.commit()
    # Roster auto-discovery (U9/R10): additive, after the fingerprint so it
    # never affects the catalog itself.
    try:
        discovery.scan(config)
    except Exception as e:  # scan() never raises; belt and braces
        print(f"router index: discovery failed ({type(e).__name__}: {e})", file=sys.stderr)
    if own:
        catalog.close()
    return result


# -- CLI --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router.indexer",
        description="Index configured sources into the typed routing catalog.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="router TOML config path")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    try:
        config = RouterConfig.load(config_path)
        custom_sources = load_custom_sources(config_path)
        result = run_index(config, custom_sources=custom_sources)
    except (ConfigError, IndexerError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    detail = ", ".join(
        f"{t}={result.counts[t]}"
        + (f" (+{result.alias_counts[t]} alias)" if result.alias_counts.get(t) else "")
        for t in sorted(result.counts)
    )
    print(f"indexed {detail or 'nothing'}")
    print("shards " + ", ".join(f"{t}={n}" for t, n in sorted(result.shard_counts.items())))
    print(f"fingerprint {result.fingerprint}")
    print(f"catalog {config.state_path('catalog.db')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

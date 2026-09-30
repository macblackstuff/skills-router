"""Router CLI (U5/KTD5): router off|on|index|status|hook-config.

`off`/`on` flip routing_enabled in the TOML by rewriting the one line in
place (every other line preserved byte-for-byte); if the key is absent it is
inserted before the first table header so it stays top-level. Both commands
verify the edited file still parses and the flip took before reporting.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from router import indexer
from router.catalog import Catalog
from router.config import ConfigError, RouterConfig
from router.hook import DEFAULT_CONFIG, print_zcode_hook_config

_ROUTING_KEY = re.compile(r"^([ \t]*)routing_enabled[ \t]*=[ \t]*.*$")
_TABLE_HEADER = re.compile(r"^\[[^\]]+\]\s*$")


def set_routing_enabled(config_path: Path, enabled: bool) -> None:
    """Flip routing_enabled in the TOML, preserving every other line (KTD5)."""
    text = config_path.read_text(encoding="utf-8")
    value = "true" if enabled else "false"
    lines = text.splitlines()
    flipped = False
    for i, line in enumerate(lines):
        match = _ROUTING_KEY.match(line)
        if match:
            lines[i] = f"{match.group(1)}routing_enabled = {value}"
            flipped = True
            break
    if not flipped:
        # absent key: insert top-level, before the first [table] header
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if _TABLE_HEADER.match(line.strip()):
                insert_at = i
                break
        lines.insert(insert_at, f"routing_enabled = {value}")
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cmd_toggle(config_path: Path, enabled: bool) -> int:
    try:
        RouterConfig.load(config_path)  # refuse to edit a config that won't parse
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        set_routing_enabled(config_path, enabled)
        after = RouterConfig.load(config_path)
    except (ConfigError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if after.routing_enabled != enabled:
        print("error: routing_enabled flip failed verification", file=sys.stderr)
        return 2
    print(
        "routing enabled"
        if enabled
        else "routing disabled — turns proceed unrouted"
    )
    return 0


def _cmd_index(config_path: Path, rest: list[str]) -> int:
    argv = list(rest)
    if "--config" not in argv:
        argv = ["--config", str(config_path)] + argv
    return indexer.main(argv)


def _catalog_tables(catalog: Catalog) -> list[str]:
    skip = {"relations", "meta"}
    names = [
        row[0]
        for row in catalog.rows(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return [n for n in names if n not in skip]


def _cmd_status(config: RouterConfig, config_path: Path) -> int:
    print(f"config {config_path}")
    print(f"routing {'enabled' if config.routing_enabled else 'disabled'}")
    catalog_path = config.state_path("catalog.db")
    print(f"catalog {catalog_path}")
    if not catalog_path.is_file():
        print("fingerprint none (no catalog — run: python3 -m router.cli index)")
        print("rows none")
        return 0
    catalog = Catalog(catalog_path)
    try:
        rows = catalog.rows("SELECT value FROM meta WHERE key = 'catalog_fingerprint'")
        print(f"fingerprint {rows[0][0] if rows else 'none (not indexed)'}")
        counts = sorted(
            (t, c) for t, c in ((t, catalog.count(t)) for t in _catalog_tables(catalog)) if c
        )
        detail = ", ".join(f"{t}={c}" for t, c in counts) or "none"
        print(f"rows {detail}")
    finally:
        catalog.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router.cli",
        description="Routing-layer control: override, index, status, hooks.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="router TOML config path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("off", help="disable routing; turns proceed unrouted (override)")
    sub.add_parser("on", help="re-enable routing")
    p_index = sub.add_parser("index", help="rebuild the catalog from configured sources")
    sub.add_parser("status", help="show routing_enabled, catalog fingerprint, row counts")
    sub.add_parser("hook-config", help="print the ZCode hook registration JSON block")
    args, extras = parser.parse_known_args(argv)
    config_path = Path(args.config).expanduser()

    if args.command in ("off", "on"):
        if extras:
            parser.error(f"unrecognized arguments: {' '.join(extras)}")
        return _cmd_toggle(config_path, args.command == "on")
    if args.command == "index":
        return _cmd_index(config_path, extras)
    if args.command in ("status", "hook-config"):
        try:
            config = RouterConfig.load(config_path)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if args.command == "status":
            return _cmd_status(config, config_path)
        print_zcode_hook_config(config, config_path)
        return 0
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())

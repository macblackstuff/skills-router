#!/usr/bin/env python3
"""ZCode hook registration — merge the router block into ~/.zcode/cli/config.json.

Importable despite the filename dash (bootstrap loads it via importlib). The
block shape comes verbatim from router.hook.zcode_hook_config (KTD4): one
entry under hooks.events.UserPromptSubmit carrying the command and a
timeoutMs >= the Jev timeout. Router-managed entries are identified by the
command containing `router.hook`; everything else in the config is preserved
byte-for-value and edits are atomic (temp file + os.replace).

CLI:
    python3 scripts/install-hooks-zcode.py --print-block   # show the block
    python3 scripts/install-hooks-zcode.py --register      # merge block in
    python3 scripts/install-hooks-zcode.py --unregister    # strip router entries
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if (REPO_SRC / "router" / "hook.py").is_file():
    sys.path.insert(0, str(REPO_SRC))

ROUTER_COMMAND_MARKER = "router.hook"
DEFAULT_ZCODE_CONFIG = "~/.zcode/cli/config.json"


class HookConfigError(Exception):
    pass


def load_config(config_path: Path | str) -> dict:
    path = Path(config_path).expanduser()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise HookConfigError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise HookConfigError(f"{path} must contain a JSON object")
    return raw


def is_router_entry(entry: object) -> bool:
    return isinstance(entry, dict) and ROUTER_COMMAND_MARKER in str(
        entry.get("command", "")
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _diff(before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="config.json (before)", tofile="config.json (after)",
    ))


def _render(config: dict) -> str:
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def _strip_router_entries(config: dict) -> dict:
    events = config.get("hooks", {}).get("events", {})
    for event, entries in list(events.items()):
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not is_router_entry(e)]
        if kept:
            events[event] = kept
        else:
            events.pop(event, None)
    return config


def _merge_router_block(config: dict, block: dict) -> dict:
    block_events = block.get("hooks", {}).get("events", {})
    events = config.setdefault("hooks", {}).setdefault("events", {})
    for event, entries in block_events.items():
        existing = [e for e in events.get(event, []) if not is_router_entry(e)]
        events[event] = existing + list(entries)
    return config


def register(block: dict, config_path: Path | str) -> tuple[dict, str]:
    """Merge `block` into the ZCode config; returns (config, unified diff)."""
    path = Path(config_path).expanduser()
    before_text = path.read_text() if path.exists() else ""
    config = load_config(path) if before_text else {}
    _merge_router_block(config, block)
    after_text = _render(config)
    _atomic_write(path, after_text)
    return config, _diff(before_text, after_text)


def unregister(config_path: Path | str) -> tuple[dict, str]:
    """Remove router-managed hook entries; returns (config, unified diff)."""
    path = Path(config_path).expanduser()
    if not path.exists():
        return {}, ""
    before_text = path.read_text()
    config = _strip_router_entries(load_config(path))
    after_text = _render(config)
    _atomic_write(path, after_text)
    return config, _diff(before_text, after_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install-hooks-zcode",
        description="Register/unregister the router hook block in the ZCode config.",
    )
    parser.add_argument("--config", default=DEFAULT_ZCODE_CONFIG,
                        help="ZCode config.json path")
    parser.add_argument("--router-config", default=None,
                        help="router TOML path (for --print-block/--register)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-block", action="store_true",
                      help="print the hook block from hook.zcode_hook_config")
    mode.add_argument("--register", action="store_true")
    mode.add_argument("--unregister", action="store_true")
    args = parser.parse_args(argv)
    zcode_config = Path(args.config).expanduser()

    if args.print_block:
        from router.config import RouterConfig  # noqa: PLC0415
        from router.hook import DEFAULT_CONFIG, zcode_hook_config  # noqa: PLC0415

        cfg = RouterConfig.load(
            Path(args.router_config).expanduser() if args.router_config
            else Path(DEFAULT_CONFIG).expanduser()
        )
        print(json.dumps(zcode_hook_config(cfg, args.router_config), indent=2))
        return 0

    try:
        if args.register:
            from router.config import RouterConfig  # noqa: PLC0415
            from router.hook import DEFAULT_CONFIG, zcode_hook_config  # noqa: PLC0415

            cfg = RouterConfig.load(
                Path(args.router_config).expanduser() if args.router_config
                else Path(DEFAULT_CONFIG).expanduser()
            )
            _, diff = register(zcode_hook_config(cfg, args.router_config), zcode_config)
        else:
            _, diff = unregister(zcode_config)
    except Exception as e:  # noqa: BLE001 — CLI boundary
        print(f"error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(diff or "config unchanged\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

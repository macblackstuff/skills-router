#!/usr/bin/env python3
"""skills-router bootstrap (KTD9) — one command install for a clean clone.

    python3 scripts/bootstrap.py [--nightly {auto,yes,no}] [--no-load]
                                 [--config PATH] [--zcode-config PATH]
    python3 scripts/bootstrap.py --remove

Install:
 1. snapshot ~/.zcode/cli/config.json before any edit (restored by --remove);
 2. register the UserPromptSubmit hook block via install-hooks-zcode.py,
    reusing hook.zcode_hook_config (block shape + timeoutMs >= Jev timeout,
    KTD4) — prints the config diff;
 3. write a default router TOML when none exists, then run the first index;
 4. register the nightly launchd job com.skills-router.judge
    (python3 -m router.judge, then python3 -m router.cli capture) with the
    plist in ~/Library/LaunchAgents, loaded via launchctl. Skipped entirely
    with --nightly no; `auto` (default) registers only when interactive.

--remove restores the snapshot (falling back to stripping router hook
entries), removes the plist and unloads the job.
"""
from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
SRC = REPO_ROOT / "src"
if (SRC / "router" / "cli.py").is_file():
    sys.path.insert(0, str(SRC))

SNAPSHOT_SUFFIX = ".router-snapshot"
DEFAULT_ZCODE_CONFIG = "~/.zcode/cli/config.json"
LAUNCHD_LABEL = "com.skills-router.judge"
LAUNCHD_HOUR = 3  # nightly judge + capture drain, 03:00 local


class BootstrapError(Exception):
    pass


def _load_install_hooks():
    """Import scripts/install-hooks-zcode.py (dash in filename -> importlib)."""
    import importlib.util

    mod_path = SCRIPTS_DIR / "install-hooks-zcode.py"
    spec = importlib.util.spec_from_file_location("install_hooks_zcode", mod_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise BootstrapError(f"cannot load {mod_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_router_toml() -> str:
    return (
        'routing_enabled = true\n'
        'capture_mode = "review"          # review | auto (KTD11)\n'
        'timeout_ms = 30000\n'
        'credential_ref = "ROUTER_JEV_API_KEY"  # env var name or op:// path\n'
        '\n'
        '[sources]\n'
        'skill_dirs = ["~/.zcode/skills"]\n'
    )


def ensure_router_config(config_path: Path) -> bool:
    """Create the default TOML when absent. Returns True when created."""
    if config_path.is_file():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(default_router_toml())
    return True


def snapshot_zcode_config(zcode_config: Path) -> bool:
    """Save the pre-router state next to it; only ever the first time.

    A zero-byte snapshot records "no config.json existed before bootstrap" so
    --remove can restore that exact state.
    """
    snap = Path(str(zcode_config) + SNAPSHOT_SUFFIX)
    if snap.exists():
        return False
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(zcode_config.read_text() if zcode_config.exists() else "")
    return True


def register_nightly(
    config_path: Path, repo_root: Path, agents_dir: Path | None = None,
    load: bool = True,
) -> Path:
    """Write the com.skills-router.judge plist; optionally launchctl-load it."""
    agents_dir = agents_dir or Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / f"{LAUNCHD_LABEL}.plist"
    chain = (
        f"python3 -m router.judge --config {config_path}; "
        f"python3 -m router.cli capture --config {config_path}"
    )
    plist = {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": ["/bin/sh", "-c", chain],
        "WorkingDirectory": str(repo_root),
        "EnvironmentVariables": {"PYTHONPATH": str(repo_root / "src")},
        "RunAtLoad": False,
        "StartCalendarInterval": {"Hour": LAUNCHD_HOUR, "Minute": 0},
        "StandardErrorPath": str(repo_root / ".router-judge.err.log"),
        "StandardOutPath": str(repo_root / ".router-judge.out.log"),
    }
    with plist_path.open("wb") as fh:
        plistlib.dump(plist, fh)
    if load:
        rc = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True, text=True,
        )
        print(f"launchctl load rc={rc.returncode} {rc.stdout.strip()} {rc.stderr.strip()}")
    return plist_path


def remove_nightly(agents_dir: Path | None = None, load: bool = True) -> bool:
    agents_dir = agents_dir or Path.home() / "Library" / "LaunchAgents"
    plist_path = agents_dir / f"{LAUNCHD_LABEL}.plist"
    if not plist_path.exists():
        return False
    if load and sys.platform == "darwin" and shutil.which("launchctl"):
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True, text=True,
        )
    plist_path.unlink()
    return True


def install(args: argparse.Namespace) -> int:
    from router.config import RouterConfig  # noqa: PLC0415
    from router.hook import zcode_hook_config  # noqa: PLC0415
    from router.indexer import run_index  # noqa: PLC0415

    hooks = _load_install_hooks()
    config_path = Path(args.config).expanduser()
    zcode_config = Path(args.zcode_config).expanduser()

    if ensure_router_config(config_path):
        print(f"router config: created {config_path}")
    config = RouterConfig.load(config_path)

    had_prior = snapshot_zcode_config(zcode_config)
    snap = Path(str(zcode_config) + SNAPSHOT_SUFFIX)
    print(f"snapshot: {snap} ({'written; empty = none existed before' if had_prior else 'already present'})")

    block = zcode_hook_config(config, config_path)  # block shape reused from U5
    _, diff = hooks.register(block, zcode_config)
    sys.stdout.write(diff or "zcode config unchanged\n")

    result = run_index(config)
    counts = ", ".join(f"{t}={n}" for t, n in sorted(result.counts.items())) or "no rows"
    print(f"index: fingerprint {result.fingerprint} ({counts})")

    nightly = args.nightly
    if nightly == "auto":
        nightly = "yes" if (sys.stdin.isatty() and sys.stdout.isatty()) else "no"
    if nightly == "yes":
        plist_path = register_nightly(config_path, REPO_ROOT, load=not args.no_load)
        print(f"nightly: {plist_path} ({'not loaded (--no-load)' if args.no_load else 'loaded'})")
    else:
        print("nightly: skipped (declined)")
    print("bootstrap: done")
    return 0


def remove(args: argparse.Namespace) -> int:
    hooks = _load_install_hooks()
    zcode_config = Path(args.zcode_config).expanduser()
    snap = Path(str(zcode_config) + SNAPSHOT_SUFFIX)
    if snap.exists():
        prior = snap.read_text()
        if prior == "":
            if zcode_config.exists():
                zcode_config.unlink()  # restore "no config existed"
            print(f"snapshot restored: {zcode_config} removed (none existed before)")
        else:
            zcode_config.write_text(prior)  # exact pre-router restore
            print(f"snapshot restored: {zcode_config}")
        snap.unlink()
    else:
        _, diff = hooks.unregister(zcode_config)
        sys.stdout.write(diff or "zcode config unchanged\n")

    if remove_nightly(load=not args.no_load):
        print(f"nightly: removed {LAUNCHD_LABEL}")
    print("bootstrap: removed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap",
        description="skills-router one-command install (hook + first index + nightly judge).",
    )
    parser.add_argument("--config", default="~/.config/router/router.toml",
                        help="router TOML path (created when missing)")
    parser.add_argument("--zcode-config", default=DEFAULT_ZCODE_CONFIG,
                        help="ZCode config.json path to snapshot + edit")
    parser.add_argument("--nightly", choices=("auto", "yes", "no"), default="auto",
                        help="register the nightly launchd judge (auto: only when interactive)")
    parser.add_argument("--no-load", action="store_true",
                        help="write the plist but skip launchctl load/unload")
    parser.add_argument("--remove", action="store_true",
                        help="restore the snapshot and unregister hook + nightly job")
    args = parser.parse_args(argv)
    try:
        return remove(args) if args.remove else install(args)
    except Exception as e:  # noqa: BLE001 — CLI boundary
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

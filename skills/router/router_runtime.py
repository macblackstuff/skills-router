#!/usr/bin/env python3
"""Self-contained router runtime loader (KTD9, symlink-free copy stub).

The ZCode skill directory `skills/router/` travels with `npx skills add`, so
this stub must work as a plain copy with no symlinks back into the repo. It
locates the router package without importing anything router-specific first:

1. repo checkout next to the stub — `<repo>/src` (git clone is the primary
   install path, KTD9);
2. vendored copy inside the skill dir — `skills/router/_vendor` (a real copy
   of `src/router`, never a symlink), for deliveries without a checkout.

Usage: python3 skills/router/router_runtime.py <router.cli args>
       python3 skills/router/router_runtime.py status
       python3 skills/router/router_runtime.py off
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR_PKG = Path(__file__).resolve().parent / "_vendor"


def repo_root() -> Path:
    """Repo root when the stub sits at <repo>/skills/router/router_runtime.py."""
    return Path(__file__).resolve().parents[2]


def module_src() -> Path | None:
    """First existing location holding the `router` package, or None."""
    src = repo_root() / "src"
    if (src / "router" / "cli.py").is_file():
        return src
    if (VENDOR_PKG / "router" / "cli.py").is_file():
        return VENDOR_PKG
    return None


def ensure_sys_path() -> Path | None:
    """Put the package parent on sys.path; return it, or None when absent."""
    src = module_src()
    if src is not None and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return src


def main(argv: list[str] | None = None) -> int:
    src = ensure_sys_path()
    if src is None:
        print(
            "skills-router: router package not found. Clone the repo next to this "
            "skill (src/router must exist) or vendor it at "
            f"{VENDOR_PKG / 'router'} — see skills/router/SKILL.md.",
            file=sys.stderr,
        )
        return 1
    from router import cli  # noqa: PLC0415 — import only after sys.path is set

    return cli.main(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())

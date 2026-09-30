"""Context slim-down (U13): reduce ZCode-scoped static surfaces to skeletons.

The routing layer replaces static dumps: skill bodies and ZCode-scoped
instruction files shrink to skeletons (frontmatter + one pointer line:
"routing layer supplies capabilities on demand"), with originals recorded
under state_dir/slim-backups/<ts>/ for byte-for-byte restore.

Scope boundary (plan R1 / U13): ZCode-scoped surfaces ONLY —
  * SKILL.md of skill directories under the configured skill roots
    (other files in a skill dir are capabilities and stay untouched);
  * instruction files passed via config (``zcode_instruction_files``).
Shared/vault-level AGENTS.md files are OUT of scope until multi-harness
adapters exist — other agents still read them. Any AGENTS.md path that is
not under a ``.zcode/`` directory is refused with an explicit error.

CLI (registered here until cli.py wiring lands):
    python3 -m router.slimdown --config <path> plan
    python3 -m router.slimdown --config <path> apply
    python3 -m router.slimdown --config <path> restore <ts|dir>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from router.config import ConfigError, RouterConfig

POINTER_LINE = "routing layer supplies capabilities on demand"
BACKUP_DIRNAME = "slim-backups"
PLAN_FILENAME = "slim-plan.json"
DEFAULT_CONFIG = "~/.config/router/router.toml"


class SlimError(Exception):
    pass


@dataclass
class SlimTarget:
    path: Path
    kind: str  # "skill" | "instruction"
    bytes_before: int


@dataclass
class SlimPlan:
    targets: list[SlimTarget] = field(default_factory=list)
    generated: str = ""


@dataclass
class ApplyResult:
    backup_dir: Path
    ts: str
    before_bytes: int
    after_bytes: int
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    backup_dir: Path
    restored: list[str] = field(default_factory=list)


# -- config access (RouterConfig attribute or mapping key) ---------------------

def _cfg_get(config, key: str, default):
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _state_dir(config) -> Path:
    raw = _cfg_get(config, "state_dir", DEFAULT_CONFIG_STATE)
    return Path(raw).expanduser()


DEFAULT_CONFIG_STATE = "~/.local/state/router"


# -- skeleton construction ------------------------------------------------------

def _frontmatter_block(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[: i + 1])
    return None


def _skeleton_text(raw: bytes, kind: str, path: Path) -> str:
    text = raw.decode("utf-8", errors="replace")
    if kind == "skill":
        fm = _frontmatter_block(text)
        if fm is None:
            fm = f"---\nname: {path.parent.name}\n---"
        return f"{fm}\n\n{POINTER_LINE}\n"
    return f"{POINTER_LINE}\n"


def _skeleton_for_file(path: Path, kind: str) -> str:
    return _skeleton_text(path.read_bytes(), kind, path)


# -- scope boundary --------------------------------------------------------------

def _ensure_zcode_scoped(p: Path) -> None:
    """Refuse shared/vault-level AGENTS.md files — out of scope for slim-down."""
    try:
        resolved = p.expanduser().resolve()
    except OSError:
        resolved = p.expanduser().absolute()
    if any(part == ".zcode" for part in resolved.parts):
        return
    if p.name == "AGENTS.md":
        raise SlimError(
            f"refusing shared/vault-level AGENTS.md: {p} — out of scope "
            f"(only ZCode-scoped instruction files, i.e. under a .zcode/ "
            f"directory, may be slimmed; other agents still read shared "
            f"AGENTS.md files)"
        )


# -- enumerate -------------------------------------------------------------------

def enumerate(plan_dir, config) -> SlimPlan:  # noqa: A001 - name fixed by U13 ask
    """List ZCode-scoped surfaces: skill SKILL.md files under configured skill
    roots plus ZCode-scoped instruction files passed via config. Writes the
    plan JSON into plan_dir when given."""
    targets: list[SlimTarget] = []
    seen: set[Path] = set()

    for root in _cfg_get(config, "skill_dirs", []) or []:
        rootp = Path(root).expanduser()
        if not rootp.is_dir():
            continue
        for child in sorted(rootp.iterdir(), key=lambda c: c.name):
            if not child.is_dir():
                continue
            sm = child / "SKILL.md"
            if sm.is_file() and sm not in seen:
                seen.add(sm)
                targets.append(SlimTarget(sm, "skill", sm.stat().st_size))

    for f in _cfg_get(config, "zcode_instruction_files", []) or []:
        p = Path(f).expanduser()
        _ensure_zcode_scoped(p)
        if not p.is_file() or p in seen:
            continue
        seen.add(p)
        targets.append(SlimTarget(p, "instruction", p.stat().st_size))

    plan = SlimPlan(targets=targets, generated=_utcnow())
    if plan_dir is not None:
        pd = Path(plan_dir).expanduser()
        pd.mkdir(parents=True, exist_ok=True)
        (pd / PLAN_FILENAME).write_text(json.dumps(plan_to_dict(plan), indent=2) + "\n")
    return plan


def plan_to_dict(plan: SlimPlan) -> dict:
    return {
        "generated": plan.generated,
        "pointer": POINTER_LINE,
        "targets": [
            {"path": str(t.path), "kind": t.kind, "bytes_before": t.bytes_before}
            for t in plan.targets
        ],
    }


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- dry run ----------------------------------------------------------------------

def dry_run(plan: SlimPlan) -> tuple[int, int]:
    """Print before/after byte counts; change nothing. Returns (before, after)."""
    before = sum(t.bytes_before for t in plan.targets)
    after = 0
    rows = []
    for t in plan.targets:
        est = len(_skeleton_for_file(t.path, t.kind).encode("utf-8")) if t.path.is_file() else 0
        after += est
        rows.append((t.kind, str(t.path), t.bytes_before, est))
    print(f"slim-down dry-run: {len(plan.targets)} surface(s), plan generated {plan.generated or 'n/a'}")
    print(f"before: {before} bytes")
    print(f"after:  {after} bytes")
    print(f"saving: {before - after} bytes")
    for kind, path, b, a in rows:
        print(f"  - [{kind}] {path} ({b} -> {a} bytes) {POINTER_LINE}")
    return before, after


# -- apply -------------------------------------------------------------------------

def _backup_rel(p: Path) -> str:
    ap = p.expanduser().absolute()
    parts = list(ap.parts[1:]) if ap.is_absolute() else list(ap.parts)
    return "/".join(parts)


def apply(plan: SlimPlan, config) -> ApplyResult:
    """Move originals to state_dir/slim-backups/<ts>/ (relative paths preserved,
    manifest.json written), then write skeleton files in their place."""
    ts = _utcnow()
    backup_root = _state_dir(config) / BACKUP_DIRNAME
    backup_root.mkdir(parents=True, exist_ok=True)
    bdir = backup_root / ts
    n = 2
    while bdir.exists():
        bdir = backup_root / f"{ts}-{n}"
        n += 1
    files_dir = bdir / "files"

    entries: list[dict] = []
    applied: list[str] = []
    skipped: list[str] = []
    before = after = 0
    for t in plan.targets:
        if not t.path.is_file():
            skipped.append(str(t.path))
            continue
        raw = t.path.read_bytes()
        before += len(raw)
        rel = _backup_rel(t.path)
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(t.path), str(dest))  # original preserved byte-for-byte
        skeleton = _skeleton_text(raw, t.kind, t.path).encode("utf-8")
        t.path.write_bytes(skeleton)
        after += len(skeleton)
        entries.append(
            {"original": str(t.path), "backup": rel, "kind": t.kind, "bytes": len(raw)}
        )
        applied.append(str(t.path))

    manifest = {"created": bdir.name, "pointer": POINTER_LINE, "entries": entries}
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return ApplyResult(bdir, bdir.name, before, after, applied, skipped)


# -- restore ------------------------------------------------------------------------

def restore(backup, config) -> RestoreResult:
    """Reverse an apply: move backed-up originals back to their original paths,
    byte-for-byte. Accepts a backup dir path or a timestamp under
    state_dir/slim-backups. The backup dir is kept as a record."""
    bdir = Path(backup).expanduser()
    if not bdir.is_dir():
        cand = _state_dir(config) / BACKUP_DIRNAME / str(backup)
        if cand.is_dir():
            bdir = cand
        else:
            raise SlimError(f"backup not found: {backup}")
    mf = bdir / "manifest.json"
    if not mf.is_file():
        raise SlimError(f"no manifest.json in backup dir: {bdir}")
    manifest = json.loads(mf.read_text())
    restored: list[str] = []
    for entry in manifest["entries"]:
        src = bdir / "files" / entry["backup"]
        dst = Path(entry["original"])
        if not src.is_file():
            raise SlimError(f"backup file missing: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        restored.append(entry["original"])
    return RestoreResult(bdir, restored)


# -- CLI ------------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="router.slimdown",
        description="Slim ZCode-scoped static surfaces to skeletons; backup + restore.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="router TOML config path")
    parser.add_argument("command", choices=["plan", "apply", "restore"])
    parser.add_argument("backup", nargs="?", help="backup ts or dir (restore only)")
    args = parser.parse_args(argv)

    try:
        config = RouterConfig.load(Path(args.config).expanduser())
        if args.command == "restore":
            if not args.backup:
                parser.error("restore requires a backup ts or dir")
            result = restore(args.backup, config)
            print(f"restored {len(result.restored)} file(s) from {result.backup_dir}")
            return 0
        plan = enumerate(_state_dir(config), config)
        dry_run(plan)
        if args.command == "apply":
            result = apply(plan, config)
            print(f"applied {len(result.applied)} surface(s) -> backup {result.backup_dir}")
            for p in result.skipped:
                print(f"skipped (missing): {p}", file=sys.stderr)
        return 0
    except (ConfigError, SlimError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

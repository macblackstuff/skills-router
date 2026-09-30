# Context slim-down (U13) — runbook

Reduce ZCode-scoped static surfaces to skeletons; routing replaces dumping. Delivers
the plan's byte-drop success criterion. Originals are always recorded for
byte-for-byte restore.

## Scope boundary (R1, ZCode-only)

Slimmed surfaces — ZCode-scoped only:

| Surface | What is slimmed | What stays |
|---|---|---|
| Skill dirs under configured `skill_dirs` | each skill's `SKILL.md` body | other files in the skill dir (scripts etc. — capabilities, not dumps) |
| ZCode-scoped instruction files passed via config (`zcode_instruction_files`) | file body | nothing else |

Out of scope, refused explicitly:

- Shared/vault-level `AGENTS.md` files — any `AGENTS.md` not under a `.zcode/`
  directory. Other agents still read them; they are untouched until multi-harness
  adapters exist (plan boundary). Passing one to `enumerate()` raises
  `SlimError` naming the path and the boundary.

## Skeleton content

- Skill `SKILL.md`: original frontmatter preserved verbatim (name/description stay
  listable) + one pointer line:
  `routing layer supplies capabilities on demand`
- Instruction file: the pointer line only (no synthetic frontmatter — AGENTS.md
  consumers read markdown, not frontmatter).

## Config

Standard router TOML (`--config`, default `~/.config/router/router.toml`). Surfaces
come from config:

- `skill_dirs` — existing source roots (also indexed; slim-down lists their
  `SKILL.md` files).
- `zcode_instruction_files` — list of ZCode-scoped instruction file paths. Read via
  the config object (attribute or mapping key); until `config.py` grows the field,
  set it on the `RouterConfig` instance before calling in (`config.py` is owned by
  another unit this wave). Each path must be ZCode-scoped (under a `.zcode/`
  directory) if named `AGENTS.md`.

## Commands

```sh
python3 -m router.slimdown --config <cfg> plan      # enumerate + dry-run, changes nothing
python3 -m router.slimdown --config <cfg> apply     # backup originals, write skeletons
python3 -m router.slimdown --config <cfg> restore <ts|dir>   # byte-for-byte reversal
```

- `plan` writes `slim-plan.json` (targets, kinds, before-bytes) into the state dir
  and prints before/after byte counts + per-surface estimates. No surface file is
  modified.
- `apply` dry-runs first, then moves originals to
  `<state_dir>/slim-backups/<ts>/files/` preserving the original absolute path
  layout (leading `/` stripped), writes `manifest.json` (original path → backup
  path, kind, byte count), then writes skeletons in place. Files that vanished
  between enumerate and apply are skipped and reported on stderr.
- `restore` accepts the backup timestamp or the backup dir path, reads
  `manifest.json`, and moves each original back byte-for-byte. The backup dir is
  kept as a record. Missing backup dir or manifest → `SlimError`.

Exit codes: 0 ok, 2 on config/slim/OS error (same convention as `router.indexer`).

## Guarantees (tested in `tests/test_slimdown.py`)

1. Dry-run changes nothing (bytes + file set verified unchanged) and reports
   before/after counts.
2. Apply reduces bytes on every slimmed surface and records every original in the
   backup manifest with byte-identical copies.
3. Restore returns originals byte-for-byte.
4. A shared/vault-level `AGENTS.md` path is refused with an explicit out-of-scope
   error; `AGENTS.md` under a `.zcode/` directory is accepted.

## Rollback

Find the backup: `ls <state_dir>/slim-backups/` → restore by timestamp. Skeletons
in place are overwritten by the restored originals; no other cleanup needed.

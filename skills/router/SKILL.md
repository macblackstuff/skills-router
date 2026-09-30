---
name: router
description: Capability router for ZCode — routes each prompt to indexed capabilities (skills, rules, knowledge, models) via Jev-judged triage and injects pointers through the UserPromptSubmit hook, replacing static skill-list dumping. Use when installing, configuring, or troubleshooting skills-router.
---

# skills-router

Jev-decided routing layer above coding agents (Python 3 stdlib only). ZCode calls
`router.hook` on every UserPromptSubmit; the router decides what to inject and
either prints `additionalContext` (exit 0) or blocks with the override notice
(exit 2) — failures fail closed to the block-with-notice path.

## Install (git clone is the primary path)

1. Clone the repo, then run `python3 scripts/bootstrap.py`.
2. Bootstrap: snapshots `~/.zcode/cli/config.json` (restorable via `--remove`),
   registers the UserPromptSubmit hook block (`python3 -m router.hook --config …`,
   `timeoutMs` ≥ the Jev timeout), writes a default config at
   `~/.config/router/router.toml`, runs the first index into
   `~/.local/state/router/catalog.db`, and registers the nightly
   launchd job `com.skills-router.judge` (`python3 -m router.judge` then
   `python3 -m router.cli capture`) — declined with `--nightly no`.
3. Set the Jev credential reference in `~/.config/router/router.toml`
   (`credential_ref` = env var name or `op://` path; never a literal key).

## Runtime entry point

`python3 skills/router/router_runtime.py <command>` — self-contained loader that
adds the repo `src/` (or `skills/router/_vendor`) to `sys.path` and dispatches to
`router.cli`. Works as a symlink-free copy inside the skill directory.

## Commands

| Command | Effect |
|---|---|
| `router_runtime.py status` | routing_enabled, catalog fingerprint, row counts |
| `router_runtime.py off` / `on` | flip `routing_enabled` override |
| `router_runtime.py index` | rebuild catalog (also drains the capture queue) |
| `router_runtime.py hook-config` | print the ZCode hook registration JSON |
| `python3 scripts/bootstrap.py --remove` | restore config snapshot, uninstall hook + nightly job |

Catalog and state are per-device and gitignored — every device rebuilds from
local sources; commits auto-push via the repo post-commit hook script.

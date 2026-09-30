---
status: inbox
tldr: Pass 5 — Work packages
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Pass 5 — Work packages

Baseline: empty repo `projects/startups/skills-router`; estate assets exist (227 skill dirs, zcode+codex hooks live, Jev key in 1Password, vault rules, brain vaults).
Target: the pass 1-3 model — 12 internal components, 35 interfaces.

Externals C13-C20 outside boundary: exempt from packaging (pass-7 checks 1-2 exempt them).

## Packages

| WP | Name | Components | Owner | Inputs | Outputs | Dependencies | Acceptance |
|---|---|---|---|---|---|---|---|
| WP1 | Catalog + indexer | C7 C8 | skills-router maintainer | source dirs (C16-C19 content) | catalog.db with fingerprint, deduped rows | none | indexer run over ~/.zcode/skills yields ~125 rows, dupes merged per G18, fingerprint changes on any source edit |
| WP2 | Router core pipeline | C3 C4 C5 C6 C21 C22 | skills-router maintainer | hook payload (IF1/IF2), catalog rows (IF13), session memory (IF36/IF37), caches (IF38/IF39) | injection set + telemetry JSONL | WP1 | on a 30-prompt golden set: ≥1 correct pointer on skill-relevant prompts, no-match on irrelevant ones, per-turn wall time <1s (repeat prompt <50ms via cache), verdict JSONL written, active-set suppresses duplicate injection on follow-up turn |
| WP3 | Hook adapters | C1 C2 | skills-router maintainer | injection lines (IF9/IF10) | registered hooks, additionalContext in agent turns | WP2 | zcode turn shows injected pointer mid-session; codex same; kill Jev key → turn blocks with notice naming override flag (G4/G5) |
| WP4 | Distribution + sync | C9 C10 | skills-router maintainer | repo | npx-installable package, hook registration, auto-push | WP3 | fresh clone on second machine: `npx skills add` + bootstrap registers hooks, catalog rebuilds, push lands on remote |
| WP5 | Evals + feedback | C11 C12 | skills-router maintainer | verdicts JSONL (IF24), outcomes (IF25 per G3) | hit@1/hit@3 vs harness baseline, nightly Jev Score judge report, tuned descriptors | WP2 | eval report exists with baseline comparison; judge runs over ≥1 week of logs and writes ≥1 descriptor tuning with rationale |

100% rule check: C1-C12, C21 each appear exactly once ✓. C13-C20 external, exempt.

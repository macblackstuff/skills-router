---
status: inbox
tldr: Routing Layer — Interface Matrix Input (2026-09-30)
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Routing Layer — Interface Matrix Input (2026-09-30)

Components and interfaces from `../2026-09-30-routing-layer-findings.md` (cited as S:Lnn). NOT-APPROVED items (§7, S:L70-78) deliberately excluded from scope pending user decision.

## Components

| Component | Kind | Notes |
|---|---|---|
| zcode-hook-adapter | | registers UserPromptSubmit in zcode config, invokes router-core, emits additionalContext (S:L92-99) |
| codex-hook-adapter | | ~/.codex/hooks.json, Claude-schema, same contract as zcode adapter (S:L93-94) |
| router-core | | orchestrates turn: payload → triage → fan → gate → inject; code = I/O only (S:L19-28) |
| jev-triage | | Jev call 1: Noul per type, one call, all 9+ types as parallel questions (S:L21-22) |
| jev-recall-fan | | parallel Jev Choice workers over token-budgeted shards of triage-passed types, ~10% shard overlap (S:L23-24) |
| jev-gate | | Jev call: alignment re-check, trim, cross-type dedupe, no-match override, confidence (S:L25) |
| catalog-db | | SQLite, one table, open-enum type/subtype, JSON extras; storage only — never routing gatekeeper (S:L42) |
| indexer | | builds catalog from sources, dedupes by content hash, emits catalog fingerprint (S:L54) |
| installer-bootstrap | | npx skills add packaging; registers hooks per harness on first run (S:L43) |
| git-sync | | git auto-push keeps repo/catalog in sync across devices (S:L44) |
| eval-harness | | golden set hit@k vs baseline, telemetry, replay, shard-size calibration sweeps (S:L45, S:L85) |
| feedback-loop | | outcome logging → Jev Score judging → descriptor/trigger tuning (S:L45) |
| coding-agent | external | zcode/codex agent; consumer of injected pointers (S:L15-17) |
| user | external | override authority on blocking failure (S:L36) |
| jev-api | external | api.typesafe.ai/v1/systemone (S:L100-102) |
| skill-dirs-source | external | ~/.zcode/skills 125 + ~/.agents/skills 102, dupes suspected (S:L103) |
| vault-rules-source | external | resources/rules/ + AGENTS.md to slim (S:L41) |
| brain-vaults-source | external | wiki vaults, read-only (S:L54) |
| model-roster-source | external | model pointers (S:L54) |
| git-remote | external | synced repo host |

## Interfaces

| Producer | Consumer | Flows | Format | Trigger | Owner | Source | Status |
|---|---|---|---|---|---|---|---|
| zcode-hook-adapter | router-core | hook payload: prompt, session id, transcript path | JSON stdin | every UserPromptSubmit | ? | S:L92 |  |
| codex-hook-adapter | router-core | hook payload: prompt, session id, transcript path | JSON stdin | every UserPromptSubmit | ? | S:L93 |  |
| router-core | jev-triage | prompt state | typesafe request JSON | every turn | ? | S:L21 |  |
| jev-triage | router-core | relevant type set + probabilities | typesafe response JSON | after triage call | ? | S:L22 |  |
| router-core | jev-recall-fan | shard payloads for triage-passed types | request JSON | after triage | ? | S:L23 |  |
| jev-recall-fan | router-core | per-type winners + probabilities | response JSON | parallel completion | ? | S:L24 |  |
| router-core | jev-gate | winners + prompt | request JSON | after fan | ? | S:L25 |  |
| jev-gate | router-core | final injection set + confidence | response JSON | after gate call | ? | S:L25 |  |
| router-core | zcode-hook-adapter | injection pointer lines | additionalContext stdout | gate pass | ? | S:L26 |  |
| router-core | codex-hook-adapter | injection pointer lines | additionalContext stdout | gate pass | ? | S:L26 |  |
| zcode-hook-adapter | coding-agent | pointers into turn context | injected text | hook return | harness | S:L92 |  |
| codex-hook-adapter | coding-agent | pointers into turn context | injected text | hook return | harness | S:L93 |  |
| catalog-db | router-core | option rows for shard building | SQLite rows | every turn | ? | S:L42 |  |
| indexer | catalog-db | upserts, dedupe, fingerprint | SQL writes | index run | ? | S:L54 |  |
| skill-dirs-source | indexer | SKILL.md files | markdown | index run | ? | S:L103 |  |
| vault-rules-source | indexer | rule files + AGENTS.md | markdown | index run | ? | S:L41 |  |
| brain-vaults-source | indexer | wiki pages | markdown | index run | ? | S:L54 |  |
| model-roster-source | indexer | model roster | ? | index run | ? | S:L54 |  |
| installer-bootstrap | zcode-hook-adapter | hook registration | config edit | install / first run | ? | S:L43 |  |
| installer-bootstrap | codex-hook-adapter | hook registration | config edit | install / first run | ? | S:L43 |  |
| catalog-db | git-sync | repo contents incl. catalog | file path | on change | ? | S:L44 |  |
| git-sync | git-remote | push | git | auto-push | ? | S:L44 |  |
| eval-harness | router-core | test prompts + expected outcomes | fixtures | eval run | ? | S:L45 |  |
| router-core | eval-harness | verdicts + telemetry | JSONL | eval run | ? | S:L45 |  |
| coding-agent | feedback-loop | outcome signal | ? | ? | ? | S:L45 |  |
| feedback-loop | catalog-db | descriptor/trigger updates | SQL | tune cadence | ? | S:L45 |  |
| router-core | user | blocking-failure notice | ? | Jev unreachable/timeout | ? | S:L36 |  |
| user | router-core | override | ? | ? | ? | S:L36 |  |
| jev-triage | jev-api | systemone request | HTTPS | every turn | typesafe | S:L21 |  |
| jev-api | jev-triage | typed answers | HTTPS response | after call | typesafe | S:L21 |  |
| jev-recall-fan | jev-api | systemone requests (parallel) | HTTPS | after triage | typesafe | S:L24 |  |
| jev-api | jev-recall-fan | typed answers | HTTPS responses | parallel | typesafe | S:L24 |  |
| jev-gate | jev-api | systemone request | HTTPS | after fan | typesafe | S:L25 |  |
| jev-api | jev-gate | typed answers | HTTPS response | after call | typesafe | S:L25 |  |
| router-core | jev-recall-fan | none (control only via shard payloads row) |  |  |  |  |  |
| eval-harness | feedback-loop | eval results feed tuning | ? | eval run | ? | S:L45 |  |

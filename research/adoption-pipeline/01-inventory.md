---
status: inbox
tldr: Pass 1 — Component inventory
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Pass 1 — Component inventory

Source: `../2026-09-30-routing-layer-findings.md`, lines numbered with `nl -ba` (copy: `SOURCE-numbered.md`).

## Components

| Id | Type | Purpose | Source |
|---|---|---|---|
| C1 | adapter | zcode hook adapter: registers UserPromptSubmit in zcode config, invokes router core, emits additionalContext | S:L21, S:L26, S:L98 |
| C2 | adapter | codex hook adapter: ~/.codex/hooks.json Claude-schema, same contract | S:L21, S:L99 |
| C3 | agent | router core: orchestrates turn payload → triage → fan → gate → inject; code = I/O only | S:L21-28 |
| C4 | policy | Jev triage: Noul per type, one call, all types as parallel questions | S:L22 |
| C5 | policy | Jev recall fan: parallel Choice workers over token-budgeted shards, ~10% overlap, all target options | S:L24 |
| C6 | policy | Jev gate: alignment re-check, trim, cross-type dedupe, no-match override, confidence | S:L25 |
| C7 | store | catalog: SQLite one file, one table PER TYPE (typed columns, custom types auto-create) + relations table; storage only, never routing gatekeeper | S:L42 (revised 2026-09-30, G10 ruling) |
| C8 | agent | indexer: builds catalog from sources, dedupes by content hash, emits catalog fingerprint | S:L54 |
| C9 | command | installer-bootstrap: npx skills add packaging; registers hooks per harness | S:L43 |
| C10 | agent | git-sync: automatic push keeps repo/catalog synced across devices | S:L44 |
| C11 | agent | eval-harness: golden set hit@k vs baseline, telemetry, replay, calibration sweeps | S:L45, S:L85 |
| C12 | policy | feedback-loop: outcome logging → Jev Score judging → descriptor/trigger tuning | S:L45 |
| C21 | store | session-memory: per-session rolling summary + active-set of routed capabilities with decay; in v1 (D14) | S:L77-78 approved 2026-09-30, S:L88 |
| C22 | store | caches: verdict cache (prompt+catalog fingerprint → replay), negative cache (triage-all-no skip), index-time precomputed worker payloads (D15, in v1) | S:L74-76 approved 2026-09-30 |
| C13 | actor (external) | coding agent (zcode/codex), consumer of injected pointers | S:L17 |
| C14 | actor (external) | user: override authority on blocking failure | S:L36 |
| C15 | external system | Jev API: api.typesafe.ai/v1/systemone | S:L101 |
| C16 | external system | skill dirs source: ~/.zcode/skills 125 + ~/.agents/skills 102 | S:L54, S:L102 |
| C17 | external system | vault rules source: resources/rules/ + AGENTS.md | S:L41, S:L54 |
| C18 | external system | brain vaults source: wiki vaults, read-only | S:L54 |
| C19 | external system | model roster source | S:L54 |
| C20 | external system | git remote: synced repo host | S:L44 |

## Hot spots

| Id | What is uncertain | Source |
|---|---|---|
| HS1 | Verdict cache (prompt+catalog fingerprint → replay) — proposed, NOT approved | S:L74 |
| HS2 | Negative cache (triage-all-no → skip repeats) — NOT approved | S:L75 |
| HS3 | Index-time precompute (shard packing, ready-to-send payloads) — NOT approved | S:L76 |
| HS4 | Multi-turn session memory — user concern: per-prompt judging too narrow, false positives; NOT approved | S:L77, S:L88 |
| HS5 | Transcript read (last-K turns as Jev state) — capability confirmed, design NOT approved | S:L78 |
| HS6 | Worker shard size — calibrate empirically | S:L85 |
| HS7 | Jev seed/temperature — unknown; resample N=3 pending docs check | S:L86 |
| HS8 | Catalog schema final fields | S:L87 |
| HS9 | Knowledge type: pointer-only vs Jev-navigated knowledge map (qmd rejected) | S:L90 |
| HS10 | Capability relations/wiring: flat vs relations table | S:L91 |
| HS11 | Feedback-loop mechanics: outcome signal, cadence, who tunes | S:L89 |
| HS12 | Final scope confirmation (brainstorm Q12) | S:L84 |
| HS13 | Model roster source: no location or format stated | S:L54 |
| HS14 | Runtime telemetry destination — router per-turn verdict log path unmodelled (found by pass-3 matrix run 2026-09-30) | matrix report §7 |
| HS15 | First-run index trigger — installer never invokes indexer (found by pass-3 matrix run) | matrix report §7 |
| HS16 | Eval reproducibility — eval vs catalog snapshot unstated (found by pass-3 matrix run) | matrix report §7 |

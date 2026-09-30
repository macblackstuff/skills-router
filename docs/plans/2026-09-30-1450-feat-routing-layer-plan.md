---
title: Routing Layer Above Coding Agents - Plan
type: feat
date: 2026-09-30
topic: routing-layer
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---
# Routing Layer Above Coding Agents - Plan

## Goal Capsule

- **Objective:** Coding agents (zcode, codex) receive, at every turn, only the capabilities, knowledge, models, file locations, and rules their current task needs — delivered by a Jev-decided routing layer outside agent context — so agent context stays lean and agent inference stays on the task.
- **Product authority:** Full v1 scope confirmed by owner 2026-09-30 (findings doc `research/2026-09-30-routing-layer-findings.md` §5). No area deferred.
- **Open blockers:** None. Two research items (shard calibration, Jev seed/temperature) resolve inside planning/build.

## Product Contract

### Summary

An open-source routing layer above coding agents. A harness hook fires every turn; Jev decides what the agent needs; pointers (and knowledge section text) are injected into the turn. Static skill lists and AGENTS.md slim to skeletons. Installable via the Vercel skills method (`npx skills add`).

### Problem Frame

Today 227 skill directories sit across `~/.zcode/skills` and `~/.agents/skills`, all competing for agent attention via static skill lists. Agents ignore or mis-pick skills, cannot reach vault rules or brain knowledge at all, and burn context on administrative material. The verified vault learning (`2026-06-24-skill-prose-is-not-enforcement`) confirms prose in a SKILL.md enforces nothing; only hooks are true harness gates. Meanwhile the Jev fact sheet documents a decision model that returns typed choices at ~0.3s and ~$0.0003/call — fast and cheap enough to run per turn. The routing layer moves capability selection out of agent context and into a Jev-decided hook.

### Key Decisions

- **General routing layer, not a skills router** (session-settled: user-directed — chosen over skills-only tool: offloads all admin/context work, not just skills). Governs R1.
- **Jev as decision model; code = I/O only** (session-settled: user-directed — chosen over local/hybrid and code prefilter: fast, near-free, typed decisions; prefilter was rejected as offloading decisions). Governs R2, R3.
- **Parallel Jev worker architecture: triage → sharded recall fan → gate** (session-settled: user-directed — chosen over single call and layered trees: full-catalog coverage, every relevance decision Jev's). Governs R2, R3.
- **Blocking failure until fixed or user override** (session-settled: user-directed — chosen over fail-open: agent is blind without routing; silent degradation hides a load-bearing failure). Override = notice in agent turn + `router off` / `router on` command. Governs R9.
- **Pointer-only injection; knowledge excepted** (session-settled: user-directed — chosen over execution path: loose coupling, speed. Knowledge type amended 19A: Jev picks sections from outline, section text injected verbatim by hook). Governs R5, R6.
- **Typed storage: one SQLite file, one table per capability type + relations table** (session-settled: user-directed — chosen over single flat table: "nightmare if everything dumped into 1 table"; custom types auto-create tables). Governs R4.
- **Full capability framework day one: nine types + custom, all equally** (session-settled: user-directed — chosen over thin skills slice: layer identity). Governs R4.
- **Multi-turn context in v1** (session-settled: user-directed — "did not give permission to defer anything": transcript read, session memory, active-set decay). Governs R7.
- **All three caches in v1** (session-settled: user-directed — verdict cache, negative cache, index-time precompute). Governs R8.
- **Distribution: Vercel skills method** (session-settled: user-directed — `npx skills add` + bootstrap registers hooks). Governs R12.
- **Git auto-push sync** (session-settled: user-directed — chosen over Syncthing: versioned, estate pattern). Governs R12.
- **Feedback loop: transcript usage scan + nightly Jev Score judge** (session-settled: user-directed, 17A). Governs R11.
- **Model roster covers all models including non-harness** (session-settled: user-directed — Jev, Voyager, subscriptions; hook auto-discovers unnamed models in prompts and flags roster addition). Governs R10.
- **Evals full depth 1-3 with self-improving loop** (session-settled: user-directed). Governs R11.
- **Harnesses v1: zcode + codex** (session-settled: user-directed — Claude and Kimi adapters later). Governs R1.

### Actors

- A1. Coding agent (zcode, codex) — consumes injected pointers/knowledge; executes capabilities.
- A2. User — override authority (`router off`/`router on`); roster maintainer.
- A3. Jev API (external) — all routing decisions.
- A4. Indexer (scheduled/on-demand) — builds typed catalog, dedupes, precomputes payloads.

### Key Flows

- F1. Turn routing
  - **Trigger:** UserPromptSubmit hook fires with prompt, session id, transcript path.
  - **Actors:** A1, A3
  - **Steps:** Hook adapter passes payload to router core → session memory loaded (rolling summary + active-set) → caches checked (verdict/negative) → Jev triage (Noul per type, one call) → parallel recall workers (Choice over token-budgeted shards of triage-passed types, ~10% overlap) → Jev gate (alignment re-check, trim, dedupe, no-match, confidence) → injection via `additionalContext` stdout → telemetry JSONL + session memory updated.
  - **Outcome:** Agent turn contains pointers (or knowledge section text) Jev selected; nothing else changes.
  - **Covers R2, R3, R5, R6, R7, R8.**
- F2. Blocking failure and override
  - **Trigger:** Jev unreachable or exceeds timeout.
  - **Actors:** A1, A2
  - **Steps:** Turn blocks → notice lands in agent turn naming `router off` → user runs `router off` → turns proceed unrouted → `router on` restores.
  - **Outcome:** No silent degradation; user always knows routing state.
  - **Covers R9.**
- F3. Indexing
  - **Trigger:** Index run (manual CLI or first-run bootstrap).
  - **Actors:** A4
  - **Steps:** Sources read (skill dirs, vault rules, AGENTS.md, brain vaults, model roster) → content-hash dedupe (newest wins, aliases kept) → typed tables + relations written → knowledge outlines built → worker payloads precomputed → catalog fingerprint emitted → git auto-push.
  - **Outcome:** Catalog current, deduped, ready to route.
  - **Covers R4, R10, R12.**
- F4. Self-improvement
  - **Trigger:** Nightly judge run.
  - **Actors:** A3
  - **Steps:** Telemetry + transcripts scanned for pointer usage → Jev Score judges outcomes → descriptor/trigger tuning written to catalog → results logged with rationale.
  - **Outcome:** Routing quality improves without manual retuning.
  - **Covers R11.**

### Requirements

**Pipeline and decisions**

- R1. The layer runs on zcode and codex via their native hook mechanisms (zcode `~/.zcode/cli/config.json` events; codex `~/.codex/hooks.json`, Claude-schema), with a shared core and thin per-harness adapters. Claude and Kimi adapters are follow-up work.
- R2. Every routing decision is Jev's: type triage (Noul per type), recall (parallel Choice workers over token-budgeted shards covering all options of triage-passed types), and gate (final selection, trim, cross-type dedupe, no-match, confidence). Code performs no relevance filtering.
- R3. Worker sharding packs options by state token budget (~2-4k tokens per worker) with ~10% overlap; shard size is calibrated empirically, not assumed.

**Catalog and types**

- R4. Capabilities live in one SQLite file with one table per type — skill, rule, knowledge, model, file_location, plugin, agent, memory, MCP — plus user-defined custom types (auto-created tables) and a relations table (from, to, kind). Core columns per type: id, subtype, name, description, trigger_terms, path, source, version, content_hash, last_verified, enabled, JSON extras. Indexer dedupes by content hash.
- R5. Injection for capability types is pointer-only: `- [type] name — one-line why (path)`.
- R6. Injection for the knowledge type is content: Jev selects sections from a page→section→summary outline and the section text lands verbatim in the turn (no summarizer between source and agent).

**Failure, memory, caching**

- R7. Multi-turn context: router reads last-K transcript turns, maintains a per-session rolling summary and an active-set of routed capabilities with decay; follow-up prompts resolve via memory; active capabilities are not re-injected.
- R8. Three caches ship in v1: verdict cache (prompt + catalog fingerprint match → replay, zero Jev calls), negative cache (triage-all-no → skip on repeat), and index-time precomputed worker payloads.
- R9. Jev unreachable or slow past timeout → the turn blocks; the notice lands in the agent turn and names `router off`; the command restores unrouted operation until `router on`.

**Sources and roster**

- R10. Sources: 227 local skill dirs, vault rules (`resources/rules/` + AGENTS.md skeleton), brain vaults (read-only), and a model roster covering all models including non-harness ones (Jev, Voyager, subscriptions). The hook detects models named in prompts but absent from the roster and flags roster addition.

**Distribution and sync**

- R11. Evals cover depth 1-3: golden set (hit@1/hit@3 vs harness-triggering baseline, majority-of-3 sampling), per-turn telemetry (latency, cost, injection size), and session-trace replay; a nightly Jev Score judge turns outcome logs into descriptor tuning.
- R12. Install via `npx skills add <owner/repo>` (Vercel Agent Skills Directory layout); bootstrap registers hooks per harness and triggers first index run; the repo (catalog included) syncs across devices by git with automatic push.

### Acceptance Examples

- AE1. **Covers R2, R5.** Given a prompt naming a pricing task, When the turn starts, Then the agent turn contains a pointer to the pricing skill and no other capability.
- AE2. **Covers R6.** Given a prompt about competitor pricing with a matching brain-vault page, When Jev selects the section, Then the competitor-pricing section text appears verbatim in the turn.
- AE3. **Covers R7.** Given turn 1 routed to a capability and turn 2 says "continue", Then turn 2 resolves through session memory and does not re-inject the active capability.
- AE4. **Covers R8.** Given an identical prompt repeated with an unchanged catalog, Then the second turn routes from cache in under 50ms with zero Jev calls.
- AE5. **Covers R9.** Given the Jev API is unreachable, When a turn fires, Then the turn blocks, the agent turn shows the blocking notice naming `router off`, and after `router off` turns proceed unrouted.
- AE6. **Covers R10.** Given a prompt naming a model absent from the roster, When indexing next runs, Then the roster flags the addition.

### Success Criteria

- Agent-context bytes drop: static skill lists and AGENTS.md reduce to skeletons; routing replaces dumping.
- Routing accuracy beats harness-native triggering on the golden set (hit@1, majority-of-3).
- Per-turn added latency under ~1s uncached, under ~50ms cached; cost under ~$0.001/turn.
- Same core runs on zcode and codex unchanged.
- Fewer agent steps per task (routing removes capability-hunting turns).

### Scope Boundaries

Deferred for later: Claude and Kimi adapters; capreg as optional source; marketplace/hosting; skills.sh distribution beyond the install method; productization packaging.
Outside this product's identity: skill execution by the router (pointer-only, R5); brain writes (router reads and flags; writer systems act); skill authoring/management UI; capreg-sized governance build (explicit anti-goal).

### Dependencies / Assumptions

- Jev API contract as verified 2026-09-30 (Choice ≤255, ~0.3s/call, $0.042/1M input, output free, 1,200 req/min; key in 1Password).
- zcode and codex hook layers stay live (verified 2026-09-28/29).
- Assumption: Jev exposes no seed/temperature (fact sheet silent) — evals resample N=3 with majority vote pending docs.typesafe.ai check.
- Adoption-pipeline decomposition (22 components, 39 interfaces, 5 work packages, 14 wave-1 steps) is the build-order authority: `research/adoption-pipeline/`.

### Outstanding Questions

Deferred to planning: shard-size calibration sweep design (budgets × {25, 50, 80, 150}); Jev seed/temperature verification against docs.typesafe.ai; relations-table kind vocabulary.

### Sources / Research

- Jev fact sheet: `projects/agentic-os/company-brain/research/llm-wiki-jev/reports/02-jev-typesafe.md`
- Findings and decisions: `research/2026-09-30-routing-layer-findings.md`
- Interface matrix: `research/interface-matrix/2026-09-30-matrix-output.md`
- Adoption pipeline: `research/adoption-pipeline/01-inventory.md` … `07-verification.md`
- Grounding dossier: `/tmp/compound-engineering-501/ce-brainstorm/skills-router-022714/grounding.md`
- TypeSafe cookbooks: skill suggestion (rank + re-check), hierarchical classification (beam search)

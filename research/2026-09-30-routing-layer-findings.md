---
status: inbox
tldr: Routing layer above coding agents — Jev decides per turn, pointers injected; findings + decisions from 2026-09-30 brainstorm
area: '[[agentic-infrastructure]]'
project: '[[skills-router]]'
para: project
type: note
focus: false
---

# Routing Layer Above Coding Agents — Findings (2026-09-30)

Session record. Three provenance classes: **SETTLED** (user chose, alternatives shown), **REJECTED** (explored, user said no), **NOT APPROVED** (explored, awaiting decision), **OPEN** (unresolved).

## 1. Product vision (SETTLED)

General routing layer above coding agents — not a skills router. Hook fires every turn; Jev decides what the agent needs (capabilities, knowledge, models, file locations, rules); compact pointers injected into the turn. Coding-agent context shrinks; agent inference stays on the task. Open source, installable via Vercel skills method (`npx skills add`), productize later. Anti-goal: capreg-sized build.

## 2. Pipeline (SETTLED)

1. Prompt submit → hook captures payload
2. Jev triage: Noul per type ("relevant to prompt?"), one call
3. Route: code fires recall workers for triage-passed types only
4. Jev recall fan: parallel workers, Choice over token-budgeted shards (~2-4k state tokens), ALL target options covered, slight shard overlap ~10% as recall insurance
5. Jev gate: winners + prompt — alignment re-check, trim, cross-type dedupe, no-match override, confidence
6. Inject: hook stdout `additionalContext` → pointers into turn

Injection = hook mechanism (user's Claude precedent: rule-router.py → additionalContext). Code = I/O only; every relevance decision Jev's.

## 3. Settled decisions

| # | Decision | Over | Reason |
|---|---|---|---|
| D1 | General routing layer, not skills-only tool | skills router | offloads all admin/context work |
| D2 | Jev = decision model | local/hybrid | fast, near-free, typed decisions |
| D3 | Blocking failure until fixed/user override | fail-open | agent blind without routing |
| D4 | Pointer-only injection for capabilities; EXCEPTION: knowledge type injects section text verbatim (map — 19A, 2026-09-30) | execution path | loose coupling, speed; knowledge needs arrival not directions |
| D15 | All three caches in v1: verdict cache, negative cache, index-time precompute (20A, 2026-09-30) | partial/no caching | user ruling |
| D5 | Full capability framework, all types equally v1 | thin skills slice | layer identity |
| D6 | Parallel Jev recall workers + gate layer above | code prefilter, single call | full-catalog coverage, Jev-only decisions |
| D7 | Worker sizing by token budget, calibrated empirically | fixed max options | unequal option context; no published optimal-N |
| D8 | Rules injected too; AGENTS.md slims to skeleton | rules-as-static-dump | vault rules actionable on demand |
| D9 | Storage = one SQLite FILE, one TABLE PER TYPE (typed columns per type, custom types auto-create tables) + relations table (from, to, kind) | single flat table ("nightmare if everything dumped into 1 table" — user 2026-09-30); markdown tables; per-type DBs | typed structure + one file to sync |
| D14 | Multi-turn context IN v1: transcript read (last-K turns) + session memory file + active-set decay (user 2026-09-30: "we need this in v1. I did not give permission to defer anything") | post-v1 deferral | user ruling |
| D10 | Install via Vercel skills method (`npx skills add`) + bootstrap registers hooks | bespoke installer | distribution solved, ~20 platforms |
| D11 | Repo synced by git with automatic push | Syncthing | versioned, estate pattern |
| D12 | Evals full depth 1-3 + self-improving feedback loop | partial evals | loop covers replay (L3) |
| D13 | Harnesses v1: ZCode ONLY; more harnesses (codex, claude, kimi) after success (user 2026-09-30: "for v1, we will only focus on ZCode") | zcode + codex both in v1 | user ruling — prove on one first |

## 4. v1 types (SETTLED — full coverage)

skill, rule, knowledge, model, file_location, plugin, agent, memory, MCP + user-defined custom types (open enum, zero code change).

## 5. Scope

IN: zcode + codex adapters, shared core; all types; sources = 227 local skill dirs + vault rules + AGENTS.md + brain vaults (read-only) + model roster (ALL models incl. non-harness: Jev, Voyager, subscriptions — user 2026-09-30; PLUS roster auto-discovery: hook detects model named in prompt but absent from roster → flags addition); SQLite catalog (typed tables + relations) + indexer (dedupe by content hash); multi-turn context (transcript read + session memory + active-set — D14); blocking failure with override (`router off`/`router on` CLI — G4 recommended); feedback = transcript usage scan + nightly Jev Score judge (G3, 17A); install method; git auto-push; evals 1-3 + feedback loop. SCOPE CONFIRMED 2026-09-30 (user).

OUT: skill execution, brain writes, authoring/management UI, marketplace/hosting, capreg dependency (optional source later, maybe never), Kimi + Claude adapters (later).

## 6. Rejected designs

| Design | Why rejected |
|---|---|
| FTS5/code prefilter before Jev | code filtering = offloading decisions; recall misses blind Jev to right capability — "not my vision" |
| Jev-navigable taxonomy tree | parallel-shard fan covers same ground flatter |
| Markdown tables as catalog storage | parse every turn, no index, sync conflicts |
| SQLite per capability type | N files to sync |
| Sidecar daemon | OSS story heavier, daemon-down = blocking failure mode |
| Capability bus / middleware standard | capreg-heaviness; months to v1 |
| Layered/nested Jev beyond fan+gate | fan covers full range without extra layers |

## 7. NOT APPROVED — explored, awaiting user decision

| Item | Status |
|---|---|
| Verdict cache (prompt fingerprint + catalog fingerprint → replay) | proposed 2026-09-30, not approved |
| Negative cache (triage-all-no → skip repeats) | proposed, not approved |
| Index-time precompute (shard packing, ready-to-send worker payloads) | proposed, not approved |
| Multi-turn session memory (rolling summary + active-set + decay) | APPROVED into v1 2026-09-30 (D14) |
| Transcript read (last-K turns as Jev state) | APPROVED into v1 2026-09-30 (D14) |

## 8. Open questions

| # | Question |
|---|---|
| Q1 | Final scope confirmation (brainstorm Q12 pending) |
| Q2 | Worker shard size — calibrate: golden-set sweep budgets × {25,50,80,150} |
| Q3 | Jev seed/temperature — not in fact sheet; resample N=3 majority for evals pending docs.typesafe.ai check |
| Q4 | Catalog schema final fields (sketch: id, type, subtype, name, description, trigger_terms, path, source, version, content_hash, last_verified, enabled, JSON extras) |
| Q5 | Multi-turn context design (see §7) |
| Q6 | Feedback-loop mechanics: what outcome signal, what cadence, who applies descriptor tuning |
| Q7 | Knowledge type: pointer-only injection (current D4) vs content injection. qmd REJECTED as retrieval base — loses context (user ruling 2026-09-30). Candidate: Jev-navigated knowledge map — index = page→section→summary outline, routed like catalog; Jev picks sections with structure visible; full section text injected verbatim. NOT APPROVED |
| Q8 | Capability relations/wiring: flat catalog (current) vs relations table (from, to, kind — enables dependency bundles, conflict detection; Obsidian links free for knowledge). Raised 2026-09-30 — NOT APPROVED |
| Q9 | RAG-as-catalog-prefilter: REJECTED — same class as FTS5 prefilter (D6 stands); scale escape = parallel sharded fan |

## 9. Verified facts (2026-09-30, claim-verifier run)

| Fact | Status |
|---|---|
| ZCode hooks live: `~/.zcode/cli/config.json`, 5 events (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop), injects via `additionalContext` (hook-chain.py L135); scripts at `/Users/work/.zcode/hooks/` | confirmed |
| Codex: `~/.codex/hooks.json`, Claude-schema compatible, same hook-chain runs | confirmed (config-level) |
| rule-router.py injection precedent (341 lines, parses gate table live, emits additionalContext L189-204) — code-confirmed, NOT live-wired in any settings today | confirmed |
| Jev: Choice ≤255 options; 13 questions one call 0.27s; $0.042/1M input, output free; 1,200 req/min | confirmed |
| 227 skill dirs: `~/.zcode/skills` 125 + `~/.agents/skills` 102 (dupes suspected: synced/ + cross-dir) | confirmed |
| capreg production (214 artifacts, exporter skill→zcode/claude/codex/kimi) | confirmed — NOT used, reference only |
| skills.sh = Vercel Agent Skills Directory, `npx skills add`, ~20 platforms | confirmed |
| capabilities.md "ZCode no hooks" line | stale — machine evidence newer |
| Jev no seed/temperature | unverifiable from fact sheet |

## 10. Key sources

- Jev fact sheet: `projects/agentic-os/company-brain/research/llm-wiki-jev/reports/02-jev-typesafe.md`
- Grounding dossier: `/tmp/compound-engineering-501/ce-brainstorm/skills-router-022714/grounding.md`
- Company-brain adjacent plan: `projects/agentic-os/jev-implementations/` (jev-core.py + hook adapters Phase 4)
- TypeSafe cookbooks: skill suggestion (rank + re-check), hierarchical classification (beam search)

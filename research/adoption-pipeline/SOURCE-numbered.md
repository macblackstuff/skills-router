---
status: inbox
tldr: 1 ---
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
     1	---
     2	status: inbox
     3	tldr: Routing layer above coding agents — Jev decides per turn, pointers injected; findings + decisions from 2026-09-30 brainstorm
     4	area: '[[agentic-infrastructure]]'
     5	project: '[[skills-router]]'
     6	para: project
     7	type: note
     8	focus: false
     9	---
    10	
    11	# Routing Layer Above Coding Agents — Findings (2026-09-30)
    12	
    13	Session record. Three provenance classes: **SETTLED** (user chose, alternatives shown), **REJECTED** (explored, user said no), **NOT APPROVED** (explored, awaiting decision), **OPEN** (unresolved).
    14	
    15	## 1. Product vision (SETTLED)
    16	
    17	General routing layer above coding agents — not a skills router. Hook fires every turn; Jev decides what the agent needs (capabilities, knowledge, models, file locations, rules); compact pointers injected into the turn. Coding-agent context shrinks; agent inference stays on the task. Open source, installable via Vercel skills method (`npx skills add`), productize later. Anti-goal: capreg-sized build.
    18	
    19	## 2. Pipeline (SETTLED)
    20	
    21	1. Prompt submit → hook captures payload
    22	2. Jev triage: Noul per type ("relevant to prompt?"), one call
    23	3. Route: code fires recall workers for triage-passed types only
    24	4. Jev recall fan: parallel workers, Choice over token-budgeted shards (~2-4k state tokens), ALL target options covered, slight shard overlap ~10% as recall insurance
    25	5. Jev gate: winners + prompt — alignment re-check, trim, cross-type dedupe, no-match override, confidence
    26	6. Inject: hook stdout `additionalContext` → pointers into turn
    27	
    28	Injection = hook mechanism (user's Claude precedent: rule-router.py → additionalContext). Code = I/O only; every relevance decision Jev's.
    29	
    30	## 3. Settled decisions
    31	
    32	| # | Decision | Over | Reason |
    33	|---|---|---|---|
    34	| D1 | General routing layer, not skills-only tool | skills router | offloads all admin/context work |
    35	| D2 | Jev = decision model | local/hybrid | fast, near-free, typed decisions |
    36	| D3 | Blocking failure until fixed/user override | fail-open | agent blind without routing |
    37	| D4 | Pointer-only injection | execution path | loose coupling, speed |
    38	| D5 | Full capability framework, all types equally v1 | thin skills slice | layer identity |
    39	| D6 | Parallel Jev recall workers + gate layer above | code prefilter, single call | full-catalog coverage, Jev-only decisions |
    40	| D7 | Worker sizing by token budget, calibrated empirically | fixed max options | unequal option context; no published optimal-N |
    41	| D8 | Rules injected too; AGENTS.md slims to skeleton | rules-as-static-dump | vault rules actionable on demand |
    42	| D9 | Storage = SQLite, one table, open-enum type column | markdown tables; per-type DBs | parse-once, syncable, no N-file sync |
    43	| D10 | Install via Vercel skills method (`npx skills add`) + bootstrap registers hooks | bespoke installer | distribution solved, ~20 platforms |
    44	| D11 | Repo synced by git with automatic push | Syncthing | versioned, estate pattern |
    45	| D12 | Evals full depth 1-3 + self-improving feedback loop | partial evals | loop covers replay (L3) |
    46	| D13 | Harnesses v1: zcode + codex | + claude, kimi | user pick; Kimi adapters exist (context-mode plugin), later |
    47	
    48	## 4. v1 types (SETTLED — full coverage)
    49	
    50	skill, rule, knowledge, model, file_location, plugin, agent, memory, MCP + user-defined custom types (open enum, zero code change).
    51	
    52	## 5. Scope
    53	
    54	IN: zcode + codex adapters, shared core; all types; sources = 227 local skill dirs + vault rules + AGENTS.md + brain vaults (read-only) + model roster; SQLite catalog + indexer (dedupe by content hash — synced/ dir dupes + cross-dir dupes suspected, ~227 → ~180 unique est.); transcript/turn visibility question raised (see §7); blocking failure; install method; git auto-push; evals 1-3 + feedback loop.
    55	
    56	OUT: skill execution, brain writes, authoring/management UI, marketplace/hosting, capreg dependency (optional source later, maybe never), Kimi + Claude adapters (later).
    57	
    58	## 6. Rejected designs
    59	
    60	| Design | Why rejected |
    61	|---|---|
    62	| FTS5/code prefilter before Jev | code filtering = offloading decisions; recall misses blind Jev to right capability — "not my vision" |
    63	| Jev-navigable taxonomy tree | parallel-shard fan covers same ground flatter |
    64	| Markdown tables as catalog storage | parse every turn, no index, sync conflicts |
    65	| SQLite per capability type | N files to sync |
    66	| Sidecar daemon | OSS story heavier, daemon-down = blocking failure mode |
    67	| Capability bus / middleware standard | capreg-heaviness; months to v1 |
    68	| Layered/nested Jev beyond fan+gate | fan covers full range without extra layers |
    69	
    70	## 7. NOT APPROVED — explored, awaiting user decision
    71	
    72	| Item | Status |
    73	|---|---|
    74	| Verdict cache (prompt fingerprint + catalog fingerprint → replay) | proposed 2026-09-30, not approved |
    75	| Negative cache (triage-all-no → skip repeats) | proposed, not approved |
    76	| Index-time precompute (shard packing, ready-to-send worker payloads) | proposed, not approved |
    77	| Multi-turn session memory (rolling summary + active-set + decay) | user raised concern "per-prompt judging too narrow, false positives"; designs proposed, NOT approved — open |
    78	| Transcript read (last-K turns as Jev state) | answers user question "can Jev see turns before last?" — capability confirmed, design not approved |
    79	
    80	## 8. Open questions
    81	
    82	| # | Question |
    83	|---|---|
    84	| Q1 | Final scope confirmation (brainstorm Q12 pending) |
    85	| Q2 | Worker shard size — calibrate: golden-set sweep budgets × {25,50,80,150} |
    86	| Q3 | Jev seed/temperature — not in fact sheet; resample N=3 majority for evals pending docs.typesafe.ai check |
    87	| Q4 | Catalog schema final fields (sketch: id, type, subtype, name, description, trigger_terms, path, source, version, content_hash, last_verified, enabled, JSON extras) |
    88	| Q5 | Multi-turn context design (see §7) |
    89	| Q6 | Feedback-loop mechanics: what outcome signal, what cadence, who applies descriptor tuning |
    90	| Q7 | Knowledge type: pointer-only injection (current D4) vs content injection. qmd REJECTED as retrieval base — loses context (user ruling 2026-09-30). Candidate: Jev-navigated knowledge map — index = page→section→summary outline, routed like catalog; Jev picks sections with structure visible; full section text injected verbatim. NOT APPROVED |
    91	| Q8 | Capability relations/wiring: flat catalog (current) vs relations table (from, to, kind — enables dependency bundles, conflict detection; Obsidian links free for knowledge). Raised 2026-09-30 — NOT APPROVED |
    92	| Q9 | RAG-as-catalog-prefilter: REJECTED — same class as FTS5 prefilter (D6 stands); scale escape = parallel sharded fan |
    93	
    94	## 9. Verified facts (2026-09-30, claim-verifier run)
    95	
    96	| Fact | Status |
    97	|---|---|
    98	| ZCode hooks live: `~/.zcode/cli/config.json`, 5 events (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop), injects via `additionalContext` (hook-chain.py L135); scripts at `/Users/work/.zcode/hooks/` | confirmed |
    99	| Codex: `~/.codex/hooks.json`, Claude-schema compatible, same hook-chain runs | confirmed (config-level) |
   100	| rule-router.py injection precedent (341 lines, parses gate table live, emits additionalContext L189-204) — code-confirmed, NOT live-wired in any settings today | confirmed |
   101	| Jev: Choice ≤255 options; 13 questions one call 0.27s; $0.042/1M input, output free; 1,200 req/min | confirmed |
   102	| 227 skill dirs: `~/.zcode/skills` 125 + `~/.agents/skills` 102 (dupes suspected: synced/ + cross-dir) | confirmed |
   103	| capreg production (214 artifacts, exporter skill→zcode/claude/codex/kimi) | confirmed — NOT used, reference only |
   104	| skills.sh = Vercel Agent Skills Directory, `npx skills add`, ~20 platforms | confirmed |
   105	| capabilities.md "ZCode no hooks" line | stale — machine evidence newer |
   106	| Jev no seed/temperature | unverifiable from fact sheet |
   107	
   108	## 10. Key sources
   109	
   110	- Jev fact sheet: `projects/agentic-os/company-brain/research/llm-wiki-jev/reports/02-jev-typesafe.md`
   111	- Grounding dossier: `/tmp/compound-engineering-501/ce-brainstorm/skills-router-022714/grounding.md`
   112	- Company-brain adjacent plan: `projects/agentic-os/jev-implementations/` (jev-core.py + hook adapters Phase 4)
   113	- TypeSafe cookbooks: skill suggestion (rank + re-check), hierarchical classification (beam search)

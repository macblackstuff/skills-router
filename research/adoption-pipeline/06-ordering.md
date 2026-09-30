---
status: inbox
tldr: Pass 6 — Ordering
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Pass 6 — Ordering

## Walking skeleton

One harness (zcode), one type (skill), catalog seeded manually if needed: hook fires (C1) → router core (C3) reads catalog (C7) → triage single call (C4) → one recall worker over one shard (C5) → gate (C6) → pointer injected via additionalContext (IF9/IF11).
Proves the data contracts pass 3 left open and pass 4 defaulted: hook payload shape (IF1), Jev request/response (IF29/IF30), injection pointer format (G19), catalog row shape (G8), telemetry path (G13), blocking notice (G5).

## Waves

| Wave | Packages | Detail |
|---|---|---|
| 1 | WP1, WP2, WP3 (zcode half) | atomic steps below |
| 2 | WP3 (codex half), sources: rules + AGENTS.md (IF16), remaining types incl. knowledge per G9 ruling, model roster per G2 | package level |
| 3 | WP4, WP5, calibration sweep G6 | package level |

## Wave 1 steps

| Step | Wave | Action | Components | Interfaces | Gaps | Blocked | Acceptance |
|---|---|---|---|---|---|---|---|
| S1 | 1 | Scaffold repo, git init, README | C3 |  |  | no | repo exists, first commit pushed |
| S2 | 1 | Create catalog schema — typed tables per capability type + relations table (G8/G10) + empty SQLite | C7 | IF13 | G8 | no | catalog.db opens; per-type tables + relations table exist; custom type auto-creates table |
| S3 | 1 | Build indexer over ~/.zcode/skills with content-hash dedupe | C8 | IF14, IF15 | G18 | no | ~125 rows, dupes merged, fingerprint emitted |
| S4 | 1 | Implement Jev client + triage call (Noul per type) | C4 | IF29, IF30 | G7 | no | 10 prompts → typed Noul answers, latency logged |
| S5 | 1 | Build token-budget shard builder | C3 | IF5 | G6 | no | shards ≤4k tokens each, all skill options covered |
| S6 | 1 | Implement recall fan (async parallel workers) | C5 | IF31, IF32 | G6 | no | parallel Choice winners + probabilities returned |
| S7 | 1 | Implement gate call | C6 | IF33, IF34 |  | no | winners trimmed, no-match verdict on irrelevant prompt |
| S8 | 1 | Wire zcode hook adapter + additionalContext output | C1 | IF1, IF9, IF11 | G19 | no | live zcode turn shows injected pointer |
| S9 | 1 | Add telemetry JSONL logging | C3 | IF24 | G13 | no | per-turn verdict log written under logs/ |
| S10 | 1 | Implement blocking-failure path + `router off`/`router on` override (G4 resolved 18) | C3 | IF27, IF28 | G4, G5 | no | killed key → turn blocks, notice in agent turn names `router off`, command unblocks |
| S11 | 1 | Golden set: 30 prompts, hit@1/hit@3 logged | C11 | IF23 | G20 | no | eval report file with baseline comparison row |
| S12 | 1 | Implement session memory: transcript read (last-K), rolling summary file, active-set decay | C21 | IF36, IF37 |  | no | follow-up turn ("continue") resolves via memory; same capability not re-injected while active |
| S13 | 1 | Implement verdict + negative caches keyed on prompt+catalog fingerprint | C22 | IF38 |  | no | repeat prompt returns cached verdict <50ms, no Jev call logged |
| S14 | 1 | Indexer emits precomputed worker payloads | C8 | IF39 |  | no | index run writes ready-to-send shards; router reads blob without packing |

## Feedback loops the order respects

C13→C12→C7→C3 routing loop: closes at recurring review (nightly judge), not a build-order dependency — WP5 last, after baseline routing stable (wave 3).
Jev-state↔outcome loop inside WP2: telemetry (S9) must precede feedback (WP5) — respected.

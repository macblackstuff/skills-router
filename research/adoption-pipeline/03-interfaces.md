---
status: inbox
tldr: Pass 3 — Interface matrix
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Pass 3 — Interface matrix

Matrix input: `../interface-matrix/2026-09-30-matrix-input.md` · report: `../interface-matrix/2026-09-30-matrix-output.md` · run exits 0, 0 missing-component candidates, 1 intended feedback loop. Human review of report sections 2/3/4/7: done 2026-09-30 (session) — boundary finding "installer-bootstrap nothing feeds it" explained: source-like entry, triggered by install event, no upstream producer needed. Boundary finding accepted as explained. Name→id map: C1 zcode-hook-adapter, C2 codex-hook-adapter, C3 router-core, C4 jev-triage, C5 jev-recall-fan, C6 jev-gate, C7 catalog-db, C8 indexer, C9 installer-bootstrap, C10 git-sync, C11 eval-harness, C12 feedback-loop, C13 coding-agent, C14 user, C15 jev-api, C16 skill-dirs-source, C17 vault-rules-source, C18 brain-vaults-source, C19 model-roster-source, C20 git-remote.

## Interfaces

| Id | Producer | Consumer | Flows | Format | Trigger | Owner | Source |
|---|---|---|---|---|---|---|---|
| IF1 | C1 | C3 | hook payload: prompt, session id, transcript path | JSON stdin | every UserPromptSubmit | C1 | S:L21,L98 |
| IF2 | C2 | C3 | hook payload | JSON stdin | every UserPromptSubmit | C2 | S:L99 |
| IF3 | C3 | C4 | prompt state | request JSON | every turn | C3 | S:L22 |
| IF4 | C4 | C3 | relevant type set + probabilities | response JSON | after triage | C4 | S:L22 |
| IF5 | C3 | C5 | shard payloads for passed types | request JSON | after triage | C3 | S:L23-24 |
| IF6 | C5 | C3 | per-type winners + probabilities | response JSON | parallel completion | C5 | S:L24 |
| IF7 | C3 | C6 | winners + prompt | request JSON | after fan | C3 | S:L25 |
| IF8 | C6 | C3 | final injection set + confidence | response JSON | after gate | C6 | S:L25 |
| IF9 | C3 | C1 | injection pointer lines | additionalContext stdout | gate pass | C3 | S:L26 |
| IF10 | C3 | C2 | injection pointer lines | additionalContext stdout | gate pass | C3 | S:L26 |
| IF11 | C1 | C13 | pointers into turn context | injected text | hook return | C1 | S:L98 |
| IF12 | C2 | C13 | pointers into turn context | injected text | hook return | C2 | S:L99 |
| IF13 | C7 | C3 | option rows for shard building | SQLite rows | every turn | C7 | S:L42 |
| IF14 | C8 | C7 | upserts, dedupe, fingerprint | SQL writes | index run | C8 | S:L54 |
| IF15 | C16 | C8 | SKILL.md files | markdown | index run | C16 | S:L102 |
| IF16 | C17 | C8 | rule files + AGENTS.md | markdown | index run | C17 | S:L41 |
| IF17 | C18 | C8 | wiki pages | markdown | index run | C18 | S:L54 |
| IF18 | C19 | C8 | model roster | GAP | index run | C19 | S:L54 |
| IF19 | C9 | C1 | hook registration | config edit | install / first run | C9 | S:L43 |
| IF20 | C9 | C2 | hook registration | config edit | install / first run | C9 | S:L43 |
| IF21 | C7 | C10 | repo contents incl. catalog | file path | on change | C7 | S:L44 |
| IF22 | C10 | C20 | push | git | auto-push | C10 | S:L44 |
| IF23 | C11 | C3 | test prompts + expected outcomes | fixtures | eval run | C11 | S:L45 |
| IF24 | C3 | C11 | verdicts + telemetry | JSONL | eval run | C3 | S:L45 |
| IF25 | C13 | C12 | outcome signal | GAP | GAP | C13 | S:L45 |
| IF26 | C12 | C7 | descriptor/trigger updates | SQL | tune cadence | C12 | S:L45 |
| IF27 | C3 | C14 | blocking-failure notice | GAP | Jev unreachable/timeout | C3 | S:L36 |
| IF28 | C14 | C3 | override | GAP | GAP | C14 | S:L36 |
| IF29 | C4 | C15 | systemone request | HTTPS | every turn | C4 | S:L22 |
| IF30 | C15 | C4 | typed answers | HTTPS response | after call | C15 | S:L22 |
| IF31 | C5 | C15 | systemone requests (parallel) | HTTPS | after triage | C5 | S:L24 |
| IF32 | C15 | C5 | typed answers | HTTPS responses | parallel | C15 | S:L24 |
| IF33 | C6 | C15 | systemone request | HTTPS | after fan | C6 | S:L25 |
| IF34 | C15 | C6 | typed answers | HTTPS response | after call | C15 | S:L25 |
| IF35 | C11 | C12 | eval results feed tuning | GAP | eval run | C11 | S:L45 |
| IF36 | C3 | C21 | rolling summary delta + active-set updates | JSONL append | every turn | C3 | S:L77-78 (D14) |
| IF37 | C21 | C3 | session context: rolling summary + active capabilities | JSONL read | every turn | C21 | S:L77-78 (D14) |
| IF38 | C22 | C3 | cached verdicts / negative skips | SQLite rows | every turn pre-call | C22 | S:L74-75 (D15) |
| IF39 | C8 | C22 | precomputed ready-to-send worker payloads | blob write | index run | C8 | S:L76 (D15) |

## Findings carried to pass 4

| Finding | Id | What is missing |
|---|---|---|
| interface gap | IF18 | format (model roster source) |
| interface gap | IF25 | format, trigger (outcome signal) |
| interface gap | IF27 | format (blocking notice) |
| interface gap | IF28 | format, trigger (override) |
| interface gap | IF35 | format (eval→feedback) |
| boundary finding | C9 | nothing feeds installer-bootstrap — accepted: entry-point, install-event triggered |

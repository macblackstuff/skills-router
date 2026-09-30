---
status: inbox
tldr: Pass 2 — Component completion
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Pass 2 — Component completion

Externals (C13-C20) record purpose + interfaces only; other cells N/A. Agent components have no job-spec template in source → purpose/inputs/outputs/owner/acceptance fields.

## Other components

| Id | Purpose | Inputs | Outputs | Owner | Acceptance |
|---|---|---|---|---|---|
| C1 | SOURCE S:L21,L26 | SOURCE S:L21 (payload) | SOURCE S:L26 (additionalContext) | SILENT | SILENT |
| C2 | SOURCE S:L99 | SOURCE S:L21 | SOURCE S:L26 | SILENT | SILENT |
| C3 | SOURCE S:L21-28 | SOURCE S:L21,L22,L25 | SOURCE S:L23,L26 | SILENT | SILENT |
| C4 | SOURCE S:L22 | SOURCE S:L21 (prompt state) | SOURCE S:L22 (type relevance) | SILENT | SILENT |
| C5 | SOURCE S:L24 | SOURCE S:L23 (shards) | SOURCE S:L24 (winners + probabilities) | SILENT | SILENT |
| C6 | SOURCE S:L25 | SOURCE S:L25 (winners + prompt) | SOURCE S:L25 (final injection set + confidence) | SILENT | SILENT |
| C7 | SOURCE S:L42 | SOURCE S:L54 (indexer writes) | SOURCE S:L42 (option rows) | SILENT | SILENT |
| C8 | SOURCE S:L54 | SOURCE S:L54 (sources) | SOURCE S:L54 (catalog, fingerprint) | SILENT | SILENT |
| C9 | SOURCE S:L43 | SILENT | SOURCE S:L43 (hook registration) | SILENT | SILENT |
| C10 | SOURCE S:L44 | SOURCE S:L44 (repo contents) | SOURCE S:L44 (push) | SILENT | SILENT |
| C11 | SOURCE S:L45,L85 | SILENT | SILENT | SILENT | SILENT |
| C12 | SOURCE S:L45 | SILENT (outcome signal HS11) | SILENT | SILENT | SILENT |
| C13 | SOURCE S:L17 | N/A | N/A | N/A | N/A |
| C14 | SOURCE S:L36 | N/A | N/A | N/A | N/A |
| C15 | SOURCE S:L101 | N/A | N/A | N/A | N/A |
| C16 | SOURCE S:L54,L102 | N/A | N/A | N/A | N/A |
| C17 | SOURCE S:L41 | N/A | N/A | N/A | N/A |
| C18 | SOURCE S:L54 | N/A | N/A | N/A | N/A |
| C19 | SOURCE S:L54 | N/A | N/A | N/A | N/A |
| C20 | SOURCE S:L44 | N/A | N/A | N/A | N/A |

## SILENT count

fields 100 · SILENT 33 · SOURCE 67 · N/A 40 (8 externals × 5 fields)

SILENT breakdown: Owner ×12, Acceptance ×12, C9/C11/C12 inputs+outputs, C12 inputs/outputs (HS11).

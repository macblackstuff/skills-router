---
status: inbox
tldr: Pass 4 — Gap register
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Pass 4 — Gap register

Updated 2026-09-30 after user rulings: G2, G10, G11, G16 resolved; G3, G4, G9 explained, awaiting pick.

## Gap register

| Id | Gap | Class | Disposition | Status |
|---|---|---|---|---|
| G1 | `Owner` of every interface | DEFAULT | producer owns what it emits; revisit if a harness contract forces consumer ownership | resolved |
| G2 | Model roster source location + format (IF18, HS13) | USER | RESOLVED 2026-09-30: roster = ALL models incl. non-harness (Jev, Voyager, subscriptions); owner-maintained markdown source file the indexer reads; PLUS auto-discovery — hook detects model named in prompt but absent from roster, flags addition | resolved |
| G3 | Outcome signal for feedback loop (IF25, HS11) | USER | RESOLVED 2026-09-30 (17A): transcript usage scan + nightly Jev Score judge | resolved |
| G4 | Override mechanism on blocking failure (IF28) | USER | RESOLVED 2026-09-30 (18): blocking notice communicated to coding agent turn + `router off` / `router on` command | resolved |
| G5 | Blocking-failure notice format (IF27) | DEFAULT | one additionalContext line + stderr line: "routing blocked: <cause>; override: <flag path>"; revisit if a harness suppresses stderr | resolved |
| G6 | Shard size calibration (HS6, S:L85) | RESEARCH | what token budget / options-per-shard maximizes hit@1 on the golden set? sweep {25,50,80,150} × {2k,4k} | open |
| G7 | Jev seed/temperature (HS7, S:L86) | RESEARCH | does api.typesafe.ai systemone expose seed/temperature? (docs check; fact sheet silent) | open |
| G8 | Catalog schema (HS8, S:L87) | DEFAULT | REVISED per G10 ruling: one SQLite file, one table per type (typed columns, custom types auto-create tables), relations table (from, to, kind); shared core columns preserved per table | resolved |
| G9 | Knowledge: pointer-only vs Jev-navigated map (HS9, S:L90) | USER | RESOLVED 2026-09-30 (19A): map — Jev picks sections from outline, section text injected verbatim by hook | resolved |
| G10 | Relations/wiring table (HS10, S:L91) | USER | RESOLVED 2026-09-30: IN v1 — typed tables + relations table; user rejected flat single table ("nightmare if everything dumped into 1 table") | resolved |
| G11 | Multi-turn context (HS4, HS5, S:L77-78, S:L88) | USER | RESOLVED 2026-09-30: IN v1 (D14) — transcript read (last-K) + session memory file + active-set decay; user: "did not give permission to defer anything" | resolved |
| G12 | Caching trio: verdict cache, negative cache, index-time precompute (HS1-3, S:L74-76) | USER | RESOLVED 2026-09-30 (20A): ALL THREE in v1 | resolved |
| G13 | Runtime telemetry destination (HS14) | DEFAULT | per-session JSONL under repo `logs/`, git-synced; revisit if query needs outgrow grep | resolved |
| G14 | First-run index trigger (HS15) | DEFAULT | installer-bootstrap runs indexer once after hook registration; revisit: never (harmless) | resolved |
| G15 | Eval reproducibility (HS16) | DEFAULT | eval run pins catalog fingerprint; verdicts logged with it; revisit: never | resolved |
| G16 | Final scope confirmation (HS12, S:L84) | USER | RESOLVED 2026-09-30: scope confirmed by user (with corrections: typed tables, multi-turn in v1, full model roster) | resolved |
| G17 | Eval→feedback format (IF35) | DEFAULT | JSONL results file the judge reads; revisit: never | resolved |
| G18 | Dedupe rule for indexer (S:L54) | DEFAULT | content_hash equal → newest version wins, older kept as alias row disabled; revisit: alias confusion reported | resolved |
| G19 | Injection pointer format (S:L26, S:L37) | DEFAULT | markdown line per capability: `- [type] name — one-line why (path)`; revisit: agent confusion observed in evals | resolved |
| G20 | Acceptance fields SILENT ×12 (pass 2) | DEFAULT | per-package acceptance checks defined in pass 5 (canonical fill); revisit: pass-5 review | resolved |
| G21 | Owner fields SILENT ×12 (pass 2) | DEFAULT | single-owner OSS repo, all internal components owner = skills-router maintainer; revisit: contributors arrive | resolved |
| G22 | RAG-as-prefilter (S:L92) | SOURCE | rejected in source (S:L62, D6); closed | resolved |

## USER questions

All USER gaps resolved 2026-09-30: G2 (roster + auto-discovery), G3 (17A transcript scan + Jev judge), G4 (18: agent-turn notice + `router off`), G9 (19A knowledge map, hook-injected), G10 (typed tables + relations), G11 (multi-turn in v1), G12 (20A all three caches), G16 (scope confirmed). Open: G6, G7 RESEARCH only.

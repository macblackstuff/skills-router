---
status: inbox
tldr: Interface matrix report
project: '[[startups]]'
para: project
type: note
focus: false
needs-review: true
---
# Interface matrix report

## 1. Summary

- components: 20 (12 internal, 8 external)
- specified interfaces: 8
- interfaces with gaps: 28
- explicit none: 0
- missing-component candidates: 0
- unstated pairs: 289
- feedback loops: 1
- self-dependencies: 0
- superseded rows: 0 (interfaces 0, components 0)

## 2. Missing-component candidates

None.

## 3. Interface gaps

| line | producer | consumer | missing |
|---|---|---|---|
| line 43 | zcode-hook-adapter | router-core | Owner |
| line 44 | codex-hook-adapter | router-core | Owner |
| line 45 | router-core | jev-triage | Owner |
| line 46 | jev-triage | router-core | Owner |
| line 47 | router-core | jev-recall-fan | Owner |
| line 48 | jev-recall-fan | router-core | Owner |
| line 49 | router-core | jev-gate | Owner |
| line 50 | jev-gate | router-core | Owner |
| line 51 | router-core | zcode-hook-adapter | Owner |
| line 52 | router-core | codex-hook-adapter | Owner |
| line 55 | catalog-db | router-core | Owner |
| line 56 | indexer | catalog-db | Owner |
| line 57 | skill-dirs-source | indexer | Owner |
| line 58 | vault-rules-source | indexer | Owner |
| line 59 | brain-vaults-source | indexer | Owner |
| line 60 | model-roster-source | indexer | Format, Owner |
| line 61 | installer-bootstrap | zcode-hook-adapter | Owner |
| line 62 | installer-bootstrap | codex-hook-adapter | Owner |
| line 63 | catalog-db | git-sync | Owner |
| line 64 | git-sync | git-remote | Owner |
| line 65 | eval-harness | router-core | Owner |
| line 66 | router-core | eval-harness | Owner |
| line 67 | coding-agent | feedback-loop | Format, Trigger, Owner |
| line 68 | feedback-loop | catalog-db | Owner |
| line 69 | router-core | user | Format, Owner |
| line 70 | user | router-core | Format, Trigger, Owner |
| line 77 | router-core | jev-recall-fan | Format, Trigger, Owner |
| line 78 | eval-harness | feedback-loop | Format, Owner |

## 4. Boundary check

External components are exempt.

- nothing feeds (internal): installer-bootstrap
- output nothing consumes (internal): none
- isolated (internal): none

## 5. Feedback loops

- loop 1 (12 members): zcode-hook-adapter, codex-hook-adapter, router-core, jev-triage, jev-recall-fan, jev-gate, catalog-db, eval-harness, feedback-loop, coding-agent, user, jev-api

Self-dependencies: none

## 6. Partitioned order

1. installer-bootstrap
2. skill-dirs-source
3. vault-rules-source
4. brain-vaults-source
5. model-roster-source
6. indexer
7. zcode-hook-adapter (loop)
8. codex-hook-adapter (loop)
9. router-core (loop)
10. jev-triage (loop)
11. jev-recall-fan (loop)
12. jev-gate (loop)
13. catalog-db (loop)
14. eval-harness (loop)
15. feedback-loop (loop)
16. coding-agent (loop)
17. user (loop)
18. jev-api (loop)
19. git-sync
20. git-remote

## 7. Unstated pairs

showing 289 of 289 (neither an interface nor `none`; external-to-external excluded)

- zcode-hook-adapter -> codex-hook-adapter
- zcode-hook-adapter -> jev-triage
- zcode-hook-adapter -> jev-recall-fan
- zcode-hook-adapter -> jev-gate
- zcode-hook-adapter -> catalog-db
- zcode-hook-adapter -> indexer
- zcode-hook-adapter -> installer-bootstrap
- zcode-hook-adapter -> git-sync
- zcode-hook-adapter -> eval-harness
- zcode-hook-adapter -> feedback-loop
- zcode-hook-adapter -> user
- zcode-hook-adapter -> jev-api
- zcode-hook-adapter -> skill-dirs-source
- zcode-hook-adapter -> vault-rules-source
- zcode-hook-adapter -> brain-vaults-source
- zcode-hook-adapter -> model-roster-source
- zcode-hook-adapter -> git-remote
- codex-hook-adapter -> zcode-hook-adapter
- codex-hook-adapter -> jev-triage
- codex-hook-adapter -> jev-recall-fan
- codex-hook-adapter -> jev-gate
- codex-hook-adapter -> catalog-db
- codex-hook-adapter -> indexer
- codex-hook-adapter -> installer-bootstrap
- codex-hook-adapter -> git-sync
- codex-hook-adapter -> eval-harness
- codex-hook-adapter -> feedback-loop
- codex-hook-adapter -> user
- codex-hook-adapter -> jev-api
- codex-hook-adapter -> skill-dirs-source
- codex-hook-adapter -> vault-rules-source
- codex-hook-adapter -> brain-vaults-source
- codex-hook-adapter -> model-roster-source
- codex-hook-adapter -> git-remote
- router-core -> catalog-db
- router-core -> indexer
- router-core -> installer-bootstrap
- router-core -> git-sync
- router-core -> feedback-loop
- router-core -> coding-agent
- router-core -> jev-api
- router-core -> skill-dirs-source
- router-core -> vault-rules-source
- router-core -> brain-vaults-source
- router-core -> model-roster-source
- router-core -> git-remote
- jev-triage -> zcode-hook-adapter
- jev-triage -> codex-hook-adapter
- jev-triage -> jev-recall-fan
- jev-triage -> jev-gate
- jev-triage -> catalog-db
- jev-triage -> indexer
- jev-triage -> installer-bootstrap
- jev-triage -> git-sync
- jev-triage -> eval-harness
- jev-triage -> feedback-loop
- jev-triage -> coding-agent
- jev-triage -> user
- jev-triage -> skill-dirs-source
- jev-triage -> vault-rules-source
- jev-triage -> brain-vaults-source
- jev-triage -> model-roster-source
- jev-triage -> git-remote
- jev-recall-fan -> zcode-hook-adapter
- jev-recall-fan -> codex-hook-adapter
- jev-recall-fan -> jev-triage
- jev-recall-fan -> jev-gate
- jev-recall-fan -> catalog-db
- jev-recall-fan -> indexer
- jev-recall-fan -> installer-bootstrap
- jev-recall-fan -> git-sync
- jev-recall-fan -> eval-harness
- jev-recall-fan -> feedback-loop
- jev-recall-fan -> coding-agent
- jev-recall-fan -> user
- jev-recall-fan -> skill-dirs-source
- jev-recall-fan -> vault-rules-source
- jev-recall-fan -> brain-vaults-source
- jev-recall-fan -> model-roster-source
- jev-recall-fan -> git-remote
- jev-gate -> zcode-hook-adapter
- jev-gate -> codex-hook-adapter
- jev-gate -> jev-triage
- jev-gate -> jev-recall-fan
- jev-gate -> catalog-db
- jev-gate -> indexer
- jev-gate -> installer-bootstrap
- jev-gate -> git-sync
- jev-gate -> eval-harness
- jev-gate -> feedback-loop
- jev-gate -> coding-agent
- jev-gate -> user
- jev-gate -> skill-dirs-source
- jev-gate -> vault-rules-source
- jev-gate -> brain-vaults-source
- jev-gate -> model-roster-source
- jev-gate -> git-remote
- catalog-db -> zcode-hook-adapter
- catalog-db -> codex-hook-adapter
- catalog-db -> jev-triage
- catalog-db -> jev-recall-fan
- catalog-db -> jev-gate
- catalog-db -> indexer
- catalog-db -> installer-bootstrap
- catalog-db -> eval-harness
- catalog-db -> feedback-loop
- catalog-db -> coding-agent
- catalog-db -> user
- catalog-db -> jev-api
- catalog-db -> skill-dirs-source
- catalog-db -> vault-rules-source
- catalog-db -> brain-vaults-source
- catalog-db -> model-roster-source
- catalog-db -> git-remote
- indexer -> zcode-hook-adapter
- indexer -> codex-hook-adapter
- indexer -> router-core
- indexer -> jev-triage
- indexer -> jev-recall-fan
- indexer -> jev-gate
- indexer -> installer-bootstrap
- indexer -> git-sync
- indexer -> eval-harness
- indexer -> feedback-loop
- indexer -> coding-agent
- indexer -> user
- indexer -> jev-api
- indexer -> skill-dirs-source
- indexer -> vault-rules-source
- indexer -> brain-vaults-source
- indexer -> model-roster-source
- indexer -> git-remote
- installer-bootstrap -> router-core
- installer-bootstrap -> jev-triage
- installer-bootstrap -> jev-recall-fan
- installer-bootstrap -> jev-gate
- installer-bootstrap -> catalog-db
- installer-bootstrap -> indexer
- installer-bootstrap -> git-sync
- installer-bootstrap -> eval-harness
- installer-bootstrap -> feedback-loop
- installer-bootstrap -> coding-agent
- installer-bootstrap -> user
- installer-bootstrap -> jev-api
- installer-bootstrap -> skill-dirs-source
- installer-bootstrap -> vault-rules-source
- installer-bootstrap -> brain-vaults-source
- installer-bootstrap -> model-roster-source
- installer-bootstrap -> git-remote
- git-sync -> zcode-hook-adapter
- git-sync -> codex-hook-adapter
- git-sync -> router-core
- git-sync -> jev-triage
- git-sync -> jev-recall-fan
- git-sync -> jev-gate
- git-sync -> catalog-db
- git-sync -> indexer
- git-sync -> installer-bootstrap
- git-sync -> eval-harness
- git-sync -> feedback-loop
- git-sync -> coding-agent
- git-sync -> user
- git-sync -> jev-api
- git-sync -> skill-dirs-source
- git-sync -> vault-rules-source
- git-sync -> brain-vaults-source
- git-sync -> model-roster-source
- eval-harness -> zcode-hook-adapter
- eval-harness -> codex-hook-adapter
- eval-harness -> jev-triage
- eval-harness -> jev-recall-fan
- eval-harness -> jev-gate
- eval-harness -> catalog-db
- eval-harness -> indexer
- eval-harness -> installer-bootstrap
- eval-harness -> git-sync
- eval-harness -> coding-agent
- eval-harness -> user
- eval-harness -> jev-api
- eval-harness -> skill-dirs-source
- eval-harness -> vault-rules-source
- eval-harness -> brain-vaults-source
- eval-harness -> model-roster-source
- eval-harness -> git-remote
- feedback-loop -> zcode-hook-adapter
- feedback-loop -> codex-hook-adapter
- feedback-loop -> router-core
- feedback-loop -> jev-triage
- feedback-loop -> jev-recall-fan
- feedback-loop -> jev-gate
- feedback-loop -> indexer
- feedback-loop -> installer-bootstrap
- feedback-loop -> git-sync
- feedback-loop -> eval-harness
- feedback-loop -> coding-agent
- feedback-loop -> user
- feedback-loop -> jev-api
- feedback-loop -> skill-dirs-source
- feedback-loop -> vault-rules-source
- feedback-loop -> brain-vaults-source
- feedback-loop -> model-roster-source
- feedback-loop -> git-remote
- coding-agent -> zcode-hook-adapter
- coding-agent -> codex-hook-adapter
- coding-agent -> router-core
- coding-agent -> jev-triage
- coding-agent -> jev-recall-fan
- coding-agent -> jev-gate
- coding-agent -> catalog-db
- coding-agent -> indexer
- coding-agent -> installer-bootstrap
- coding-agent -> git-sync
- coding-agent -> eval-harness
- user -> zcode-hook-adapter
- user -> codex-hook-adapter
- user -> jev-triage
- user -> jev-recall-fan
- user -> jev-gate
- user -> catalog-db
- user -> indexer
- user -> installer-bootstrap
- user -> git-sync
- user -> eval-harness
- user -> feedback-loop
- jev-api -> zcode-hook-adapter
- jev-api -> codex-hook-adapter
- jev-api -> router-core
- jev-api -> catalog-db
- jev-api -> indexer
- jev-api -> installer-bootstrap
- jev-api -> git-sync
- jev-api -> eval-harness
- jev-api -> feedback-loop
- skill-dirs-source -> zcode-hook-adapter
- skill-dirs-source -> codex-hook-adapter
- skill-dirs-source -> router-core
- skill-dirs-source -> jev-triage
- skill-dirs-source -> jev-recall-fan
- skill-dirs-source -> jev-gate
- skill-dirs-source -> catalog-db
- skill-dirs-source -> installer-bootstrap
- skill-dirs-source -> git-sync
- skill-dirs-source -> eval-harness
- skill-dirs-source -> feedback-loop
- vault-rules-source -> zcode-hook-adapter
- vault-rules-source -> codex-hook-adapter
- vault-rules-source -> router-core
- vault-rules-source -> jev-triage
- vault-rules-source -> jev-recall-fan
- vault-rules-source -> jev-gate
- vault-rules-source -> catalog-db
- vault-rules-source -> installer-bootstrap
- vault-rules-source -> git-sync
- vault-rules-source -> eval-harness
- vault-rules-source -> feedback-loop
- brain-vaults-source -> zcode-hook-adapter
- brain-vaults-source -> codex-hook-adapter
- brain-vaults-source -> router-core
- brain-vaults-source -> jev-triage
- brain-vaults-source -> jev-recall-fan
- brain-vaults-source -> jev-gate
- brain-vaults-source -> catalog-db
- brain-vaults-source -> installer-bootstrap
- brain-vaults-source -> git-sync
- brain-vaults-source -> eval-harness
- brain-vaults-source -> feedback-loop
- model-roster-source -> zcode-hook-adapter
- model-roster-source -> codex-hook-adapter
- model-roster-source -> router-core
- model-roster-source -> jev-triage
- model-roster-source -> jev-recall-fan
- model-roster-source -> jev-gate
- model-roster-source -> catalog-db
- model-roster-source -> installer-bootstrap
- model-roster-source -> git-sync
- model-roster-source -> eval-harness
- model-roster-source -> feedback-loop
- git-remote -> zcode-hook-adapter
- git-remote -> codex-hook-adapter
- git-remote -> router-core
- git-remote -> jev-triage
- git-remote -> jev-recall-fan
- git-remote -> jev-gate
- git-remote -> catalog-db
- git-remote -> indexer
- git-remote -> installer-bootstrap
- git-remote -> git-sync
- git-remote -> eval-harness
- git-remote -> feedback-loop

## 8. Matrix

Row feeds column. Legend: `X` specified, `g` gap, `-` none, blank unstated, `S` self.

```
                       1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 
  1 installer-bootstrap .                 g  g                                     
  2 skill-dirs-source      .           g                                           
  3 vault-rules-source        .        g                                           
  4 brain-vaults-source          .     g                                           
  5 model-roster-source             .  g                                           
  6 indexer                            .                    g                      
  7 zcode-hook-adapter                    .     g                    X             
  8 codex-hook-adapter                       .  g                    X             
  9 router-core                           g  g  .  g  g  g     g        g          
 10 jev-triage                                  g  .                       X       
 11 jev-recall-fan                              g     .                    X       
 12 jev-gate                                    g        .                 X       
 13 catalog-db                                  g           .                 g    
 14 eval-harness                                g              .  g                
 15 feedback-loop                                           g     .                
 16 coding-agent                                                  g  .             
 17 user                                        g                       .          
 18 jev-api                                        X  X  X                 .       
 19 git-sync                                                                  .  g 
 20 git-remote                                                                   . 
```

below-diagonal check: every below-diagonal mark lies inside a loop block.

## 10. Source coverage

`/Users/work/agentic-local/Vaults/local-para/projects/startups/skills-router/research/2026-09-30-routing-layer-findings.md`: 110 lines (24 blank), 33 cited, 57 uncited (non-blank).

Nothing cites these spans — unmodelled components and interfaces hide here.

| lines | first line |
|---|---|
| L1-13 | --- |
| L30-35 | ## 3. Settled decisions |
| L37-40 | \| D4 \| Pointer-only injection \| execution path \| loose coupling, speed \| |
| L46-52 | \| D13 \| Harnesses v1: zcode + codex \| + claude, kimi \| user pick; Kimi adapters  |
| L56-84 | OUT: skill execution, brain writes, authoring/management UI, marketplace/hosting |
| L86-91 | \| Q3 \| Jev seed/temperature — not in fact sheet; resample N=3 majority for evals |
| L105-110 | ## 10. Key sources |

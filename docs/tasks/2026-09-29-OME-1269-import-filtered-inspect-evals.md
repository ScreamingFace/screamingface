---
id: OME-1269
linear_url: https://linear.app/openmined/issue/OME-1269/import-onet-m6-pubmedqa-and-xstest-with-exactly-the-questions-inspect
status: Done
type: task
priority: Medium
labels: [screamingface-engine, human]
created: 2026-09-23
closed: 2026-09-29
---

# Import `onet_m6`, `pubmedqa` and `xstest` with exactly the questions inspect keeps

Parent epic: `OME-1299`. Absorbs `OME-1270` (marked Duplicate).

Delivered as a 3-PR stack:

1. The task-route mechanism plus the `onet_m6` board (391 questions, a named deviation from
   inspect's 397) — this mirror's first PR.
2. The `pubmedqa` board.
3. CI token wiring plus the `xstest_safe` board (the unsafe half waits for `OME-1400`).

Spec: ../spec/2026-09-29-inspect-task-route-bake.md
Plan: ../plan/2026-09-29-inspect-task-route-bake.md
Ledger (PR 1): ../work/2026-09-29-inspect-task-route-bake.md
Ledger (PR 2): ../work/2026-09-29-pubmedqa-board.md
Ledger (PR 3): ../work/2026-09-29-xstest-ci-token.md

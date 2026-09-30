---
id: OME-1071
linear_url: https://linear.app/openmined/issue/OME-1071
status: done
type: task
priority: 3
labels: [client-sf, agentic, autonomous]
parent: OME-1016
created: 2026-09-28
closed: 2026-09-29
---

# SDK cancel_active() sweep stops healthy sibling runs when one candidate's run fails

Unit 1 of 3 in the sdk-run-isolation stack (transport half). The runner half (evaluation outcome with a partial report) is NOT in this unit and waits for owner decisions Q1–Q5 in the spec. This issue stays open until that lands.

Spec: ../spec/2026-09-28-sdk-run-isolation.md
Plan: ../plan/2026-09-28-sdk-run-isolation.md
Ledger: ../work/2026-09-28-sdk-run-isolation-stop-one.md

## Close (2026-09-29)

Landed on `main` in #1105 (the per-run stop and the abort-flag fix) and #1121 (`762d9285`, the runner half: one failed candidate no longer stops its siblings). Closed in Linear with the close comment.

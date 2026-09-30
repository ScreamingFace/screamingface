---
id: OME-1067
linear_url: https://linear.app/openmined/issue/OME-1067
status: done
type: task
priority: 2
labels: [client-sf, agentic, autonomous]
parent: OME-1064
created: 2026-09-28
closed: 2026-09-29
---

# Cancel only the affected run when a stream disconnects

Unit 2 of 3 in the sdk-run-isolation stack. Builds on unit 1 (OME-1071). The sweep from the runner's except arm is unchanged until the runner half of OME-1071 lands.

Spec: ../spec/2026-09-28-sdk-run-isolation.md
Plan: ../plan/2026-09-28-sdk-run-isolation.md
Ledger: ../work/2026-09-28-sdk-run-isolation-disconnect.md

## Close (2026-09-29)

Landed on `main` in #1109 (a lost stream stops only its own run) and #1121 (`762d9285`, the evaluation half). Closed in Linear with the close comment.

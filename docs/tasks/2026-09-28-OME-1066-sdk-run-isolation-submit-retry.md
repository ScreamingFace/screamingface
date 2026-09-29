---
id: OME-1066
linear_url: https://linear.app/openmined/issue/OME-1066
status: done
type: task
priority: 2
labels: [client-sf, agentic, autonomous]
parent: OME-1064
created: 2026-09-28
closed: 2026-09-29
---

# Retry run submission on 503 Retry-After instead of failing the candidate

Unit 3 of 3 in the sdk-run-isolation stack. Builds on unit 2 (OME-1067).

Spec: ../spec/2026-09-28-sdk-run-isolation.md
Plan: ../plan/2026-09-28-sdk-run-isolation.md
Ledger: ../work/2026-09-28-sdk-run-isolation-submit-retry.md

## Close (2026-09-29)

Landed on `main` in #1115 (the 503 retry) and #1121 (`762d9285`, a failed run start no longer stops the siblings). Closed in Linear with the close comment.

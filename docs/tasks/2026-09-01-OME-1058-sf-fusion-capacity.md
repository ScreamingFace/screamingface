---
id: OME-1058
linear_url: https://linear.app/openmined/issue/OME-1058/size-sf-fusion-capacity-for-concurrent-evaluations-ns-ceiling-quota
status: planned
type: task
priority: 2
labels: [repo, human, deferred]
created: 2026-09-01
closed:
---

# Size sf-fusion capacity for concurrent evaluations

Lands in `OpenMined/infrastructure`, not this monorepo. Parent: `OME-1064`.

With the namespace LimitRange applied, each Runner Pod charges `requests 200m/256Mi`.
Against 310m standing usage, `requests.cpu: 2` fits **exactly 8 runners** — precisely
`_MAX_CANDIDATES_IN_FLIGHT`. The 2026-08-25 resize raised the `limits.*` ceilings and left
requests alone, which moved the bottleneck onto `requests.cpu` at exactly the client's
fan-out.

Raising the quota alone is not a fix: `Insufficient cpu` and `exceeded quota` both appeared
in the same incident, so the single non-autoscaled user node is co-binding. Recommendation
on the issue is to enable user-pool autoscaling and bound demand via `OME-1065`, treating a
second node as a later throughput decision.

Blocked on an owner decision between the three options. Also needs the `docs/ledger.md`
deferral trigger restated in CPU terms — it currently gates on node memory, while both real
signals were CPU.

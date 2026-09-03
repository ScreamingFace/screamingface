---
id: OME-944
linear_url: https://linear.app/openmined/issue/OME-944/split-scoreboard-readiness-from-liveness-with-a-db-aware-readyz
status: backlog
type: improvement
priority: 3
labels: [scoreboard, agentic, autonomous]
created: 2026-08-22
closed:
---

# Split scoreboard readiness from liveness with a DB-aware readyz

Both probes hit the static `/healthz`, so a DB-dead pod stays Ready and 503s every
submission. Add a cheap DB-checking `/readyz`, keep `/healthz` as pure liveness (never
DB-coupled — restart-loop hazard), point the chart's readinessProbe at the new endpoint.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`

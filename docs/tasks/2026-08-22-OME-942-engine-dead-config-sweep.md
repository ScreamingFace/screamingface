---
id: OME-942
linear_url: https://linear.app/openmined/issue/OME-942/sweep-engine-dead-observability-config-log-level-chart-readyz-rbac
status: backlog
type: improvement
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-22
closed:
---

# Sweep engine dead observability config (log-level chart, readyz, RBAC, active_count)

Chart `URL4_CLOUD_LOG_LEVEL` (no deployed pod can reach DEBUG today); call
`logs.configure()` from `create_app`, not only `cli.main`; make `/readyz` NATS-aware and
probe it (or delete `/livez`+`/readyz`); drop the unused `pods/log` RBAC grant; register or
delete `InProcessJobRunner.active_count`. No scrape endpoint on the run-mode Job.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`

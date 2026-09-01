---
id: OME-1065
linear_url: https://linear.app/openmined/issue/OME-1065/refuse-a-run-when-the-namespace-resourcequota-has-no-headroom
status: in_progress
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
  - task
created: 2026-09-01
closed:
---

# Refuse a run when the namespace ResourceQuota has no headroom

`K8sJobRunner.schedule()` creates a Job unconditionally. The `sf-fusion` namespace
carries a `ResourceQuota` (`ns-ceiling`) that refuses Pod creation asynchronously,
after `create_namespaced_job` has already returned 201. On 2026-09-01 this
produced 23 minutes of silent non-execution (OME-1064).

Make the K8s adapter raise the existing `JobRunnerAtCapacity` — which the REST
edge already maps to 503 + `Retry-After` — when one more Runner Pod does not fit
the namespace quota. Read the quota's `status.used` vs `status.hard` (cached
~2s), account for LimitRange defaults in the Pod's charge, hold a local
in-flight reservation counter to close the read-modify-write race, and degrade
to today's behaviour when the quota cannot be read. The Engine's Role gains
`get`/`watch` on `resourcequotas` (plus `limitranges` for the charge).

Spec: `docs/spec/2026-09-01-OME-1065-quota-admission.md`
Plan: `docs/plan/2026-09-01-OME-1065-quota-admission.md`
Work: `docs/work/2026-09-01-OME-1065-quota-admission.md`

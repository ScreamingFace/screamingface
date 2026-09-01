---
id: OME-1065
linear_url: https://linear.app/openmined/issue/OME-1065/refuse-a-run-when-the-namespace-resourcequota-has-no-headroom
status: planned
type: bug
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-01
closed:
---

# Refuse a run when the namespace ResourceQuota has no headroom

Parent: `OME-1064`. Blocks `OME-1066` and `OME-908`.

`K8sJobRunner.schedule()` creates a Job unconditionally. The port documents this as
deliberate — "a cluster-backed runner lets the scheduler absorb the load and never raises" —
but a namespace with a ResourceQuota does not absorb load, it refuses Pod creation
asynchronously after `create_namespaced_job` has returned 201.

The 503 + `Retry-After` path already exists at `rest/routes.py:198-208`. Make the K8s adapter
raise `JobRunnerAtCapacity` by reading the namespace ResourceQuota's `status.used` vs
`status.hard`, accounting for LimitRange defaults, with a local reservation counter to close
the read-modify-write race. Requires `get`/`watch` on `resourcequotas` in the Engine Role.

Spec §4.2. Plan unit 3.

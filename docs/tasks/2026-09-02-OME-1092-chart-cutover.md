---
id: OME-1092
linear_url: https://linear.app/openmined/issue/OME-1092/cut-over-the-chart-to-the-worker-pool-and-retire-the-job-adapter-and
status: planned
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-02
closed:
---

# Cut over the chart to the worker pool and retire the Job adapter and its RBAC

The cutover, blocked by OME-1093. Adds the runner pool Deployment with its drain configuration and disruption budget, and deletes `adapters/k8s.py`, the `batch/jobs` Role and RoleBinding, and the settings only the Job path read. The control plane loses the ability to create Pods, which is a least-privilege win falling out of the design. The commit body must state that queue-depth admission supersedes OME-1065, or the next reader will restore the deleted quota code.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`

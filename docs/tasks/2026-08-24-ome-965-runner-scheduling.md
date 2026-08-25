---
id: OME-965
linear_url: https://linear.app/openmined/issue/OME-965
status: in_review
type: Bug
priority: High
labels: [screamingface-engine, autonomous, agentic]
created: 2026-08-24
closed:
---

# Apply Engine scheduling to Runner Jobs

## Goal

Make each Kubernetes Runner Job inherit the Engine deployment's node selector
and tolerations. This lets Preview Runner Pods pass admission and schedule on
the isolated Preview node pool.

## Acceptance

- Runner Jobs use configured node selectors and tolerations.
- Deployments with empty scheduling values keep the current Job shape.
- Runner Jobs continue to disable ServiceAccount token automount.
- Engine and Helm contract tests pass.

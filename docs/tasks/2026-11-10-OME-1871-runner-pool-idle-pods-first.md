---
id: OME-1871
linear_url: https://linear.app/openmined/issue/OME-1871/make-the-runner-pool-remove-idle-pods-first-on-scale-down
status: backlog
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-10
closed:
---

# Make the runner pool remove idle pods first on scale-down

On scale-down Kubernetes picks the pod to remove without knowing which pods are busy. The kind
walkthrough of `OME-1870` saw it remove a pod with 2 running runs while idle pods existed. The
worker should annotate its own pod with `controller.kubernetes.io/pod-deletion-cost` = its busy
slot count (needs a ServiceAccount token plus RBAC to patch its own pod).

- 2026-11-10: filed as the follow-up recorded in `docs/spec/2026-11-10-runner-pool-autoscaling.md`.

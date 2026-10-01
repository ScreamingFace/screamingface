---
id: OME-1417
linear_url: https://linear.app/openmined/issue/OME-1417
status: In Progress
type: fix
priority: Medium
labels: [client-sf, agentic, autonomous]
created: 2026-09-30
closed:
---

# Drop the stale kubernetes requirement from the SDK runtime

Leaf under epic `OME-1308` (E18 · A local app).

The Engine's Kubernetes Job adapter was retired in #822, yet the SDK's `runtime` extra and its
startup probe still required `kubernetes`. The frozen Studio sidecar doesn't bundle it, so it
exited at startup and the installed app crashed (found while verifying `OME-1415`).

Ledger: ../work/2026-09-30-sdk-drop-kubernetes-runtime.md

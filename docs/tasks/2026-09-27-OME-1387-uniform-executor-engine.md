---
id: OME-1387
linear_url: https://linear.app/openmined/issue/OME-1387
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1086
created: 2026-09-27
closed:
---

# OME-1387 — Run every engine request on the worker pool and remove the node tier

The worker pool becomes the engine's only executor: sync `GET /?q=`, mount calls
(`shape=direct` runs) and ensembles all run on the NATS run queue in the same kind of child
process, with one shared events stream. The node tier is removed after the parity gate.

- Spec: `apps/screamingface-engine/docs/plans/uniform-executor/`
- Ledger: `docs/work/2026-09-27-uniform-executor.md`
- Sibling leaf: `OME-1388` (url4 direct-call API), same PR.

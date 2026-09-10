---
id: OME-1161
linear_url: https://linear.app/openmined/issue/OME-1161/stream-safe-model-call-activity-to-notebook-consumers
status: In Review
type: feature
priority: High
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed:
---

# Stream safe model-call activity

Implement the Engine slice of the [approved spec](../spec/2026-09-09-OME-887-evaluation-activity.md) and [plan](../plan/2026-09-09-OME-887-evaluation-activity.md), merged in PR #885. [Work ledger](../work/2026-09-10-OME-1161-model-activity.md).

Full/off policy; shared bounded helper; model-call observations and fixed 60-second heartbeats; producer timestamps; structured closing bridge-loss reporting. Client and benchmark-stage producers remain separate.

Implementation is in [draft PR #897](https://github.com/ScreamingFace/screamingface/pull/897), commit `378fade9`. Full local/pre-push Engine gates, 43 new tests, independent review and 112 chart-wiring checks passed. Awaiting PR review/CI/merge; delivery remains open.

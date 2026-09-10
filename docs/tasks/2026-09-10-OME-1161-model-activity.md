---
id: OME-1161
linear_url: https://linear.app/openmined/issue/OME-1161/stream-safe-model-call-activity-to-notebook-consumers
status: In Review
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed:
---

# Stream safe model-call activity

PR 897 delivers observation ports/dispatch only; it does not yet enable activity.
Subsequent main-based PRs deliver execution integration, activity and deployment policy.
Hard cap: 500 added plus deleted lines per PR, including tests/docs. No stacked PRs.
Keep this feature open until all deliveries land. Client/benchmark work remains separate.

[Spec](../spec/2026-09-10-OME-1161-observation-seam.md) ·
[Plan](../plan/2026-09-10-OME-1161-observation-seam.md) ·
[Ledger](../work/2026-09-10-OME-1161-observation-split.md).

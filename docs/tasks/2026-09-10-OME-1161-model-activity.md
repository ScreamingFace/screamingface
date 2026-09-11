---
id: OME-1161
linear_url: https://linear.app/openmined/issue/OME-1161/stream-safe-model-call-activity-to-notebook-consumers
status: In Review
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed:
---

# Stream safe model-call activity

Docs PR 897 merged at af58b5c1. The first code unit adds observation interfaces/dispatch
and unit tests in PR 899. Execution integration is temporarily stacked on it with owner
approval (2026-09-11); rebase onto main after 899 merges. Integration retains the 500-line cap.
The first code PR supplies observation interfaces; later units integrate execution, activity
and deployment policy. Keep this overall feature open until delivery is complete.
Client rendering, benchmark-stage producers and provisional scores remain separate.

Update these same four shared artifacts across the deliveries; do not create one set per PR.
[Spec](../spec/2026-09-10-OME-1161-observation-seam.md) ·
[Plan](../plan/2026-09-10-OME-1161-observation-seam.md) ·
[Ledger](../work/2026-09-10-OME-1161-observation-split.md).

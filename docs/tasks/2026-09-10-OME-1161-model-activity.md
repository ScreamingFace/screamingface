---
id: OME-1161
linear_url: https://linear.app/openmined/issue/OME-1161/stream-safe-model-call-activity-to-notebook-consumers
status: In Review
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed:
---

# Stream safe model-call activity

PRs 897, 899 and 915 merged the design, interfaces and generic execution integration.
Owner update (2026-09-15): PR 931 contains the plugin and direct tests, ready for review.
Deployment registration, settings/Helm and integration tests are a dependent stacked draft.
Keep all review fixes, including sink accounting, interrupted cleanup, disabled bookkeeping
and explicit local Settings precedence. Rebase the child onto main after 931 merges.
The feature stays In Review until both land. Client rendering, benchmark-stage producers
and provisional scores remain separate.

[Spec](../spec/2026-09-10-OME-1161-observation-seam.md) ·
[Plan](../plan/2026-09-10-OME-1161-observation-seam.md) ·
[Ledger](../work/2026-09-10-OME-1161-observation-split.md).

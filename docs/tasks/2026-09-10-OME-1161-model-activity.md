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

PR931 cleanup (2026-09-16): removed unused heartbeat callback, named unchanged admission constants, clamped bridge loss to nonnegative safe integers, and clarified reserved vocabulary. 60 direct tests and full Engine gates pass, coverage 93.26%. Ledger: `docs/work/2026-09-16-OME-1161-plugin-cleanup.md`. Deployment remains separate in PR935.

Deployment follow-up approved 2026-09-17: rebase PR935 onto main, correct ambient/injected Settings precedence, add regression coverage and commit. Ledger: docs/work/2026-09-17-OME-1161-deployment-review.md.

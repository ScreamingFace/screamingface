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

Delivery is split into two sequential main-based PRs; the owner explicitly requested no stack.

1. [PR 897](https://github.com/ScreamingFace/screamingface/pull/897): generic Engine observation
   interfaces, explicit composition injection and tests. Nothing is registered by default;
   this PR alone does not emit researcher activity.
2. After PR 897 merges: a fresh main-based PR for the activity adapter, schema, sessions,
   rate limits, heartbeat, full/off policy, Helm wiring and activity-specific tests.

Full implementation preserved at 01b3a0f1 on local branch `OME-1161-activity-preserved`.
The issue stays open until the second delivery lands. Client rendering and benchmark-stage
producers remain separate.

[Foundation spec](../spec/2026-09-10-OME-1161-observation-seam.md) ·
[Delivery plan](../plan/2026-09-10-OME-1161-observation-seam.md) ·
[Split ledger](../work/2026-09-10-OME-1161-observation-split.md).

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
PR 931 now combines the complete activity producer with owner approval (2026-09-15):
record contract, admission, operation lifecycle/adapter, fixed heartbeats, deployment full/off
registration and end-to-end verification. The larger combined diff replaces the earlier split.
Keep the sink-accounting correction and current tests; extract deferred code from 2bc435bb.
This feature remains In Review until merge. Client rendering, benchmark-stage producers
and provisional scores remain separate.

[Spec](../spec/2026-09-10-OME-1161-observation-seam.md) ·
[Plan](../plan/2026-09-10-OME-1161-observation-seam.md) ·
[Ledger](../work/2026-09-10-OME-1161-observation-split.md).

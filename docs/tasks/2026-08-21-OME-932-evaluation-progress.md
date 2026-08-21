---
id: OME-932
linear_url: https://linear.app/openmined/issue/OME-932/publish-benchmark-native-evaluation-progress
status: in_progress
type: improvement
priority: 2
labels: [screamingface-engine, agentic, deferred]
created: 2026-08-21
closed:
---

# Publish terminal Benchmark progress and provisional scores

Emit privacy-minimal `screamingface.evaluation-progress.v1` structured Log snapshots after
terminal Cases through OME-934's generic run-scoped Log seam. Benchmarks retain `grade_case` and
scoring authority; the final Candidate Result remains authoritative.

Hard requirements:

- no additional model, judge, network, or paid calls;
- no Client scoring or URL4 parsing;
- no generated URL4, protocol/revision/cache identity, or `packages/url4` change;
- no Answering/Grading/current-Case phase contract;
- exact completed/total progress under out-of-order completion;
- exact existing Case envelopes and final results remain unchanged;
- progress failures are nonfatal;
- built-in Benchmarks share registry-wired, pure Case/scoring seams.

Blocked only by OME-934 for production code. OME-931 is independent.

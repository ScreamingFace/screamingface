---
id: OME-932
linear_url: https://linear.app/openmined/issue/OME-932/publish-benchmark-native-evaluation-progress
status: pick_immediately
type: improvement
priority: 2
labels: [screamingface-engine, agentic, deferred]
created: 2026-08-21
closed:
---

# Publish benchmark-native Evaluation progress

Emit privacy-minimal `screamingface.evaluation-progress.v1` structured Log snapshots from
shared Engine semantic boundaries. Benchmarks retain `grade_case` and scoring authority;
the final Candidate Result remains authoritative.

Hard requirements:

- no additional model, judge, network, or paid calls;
- no Client scoring or URL4 parsing;
- no `packages/url4` change;
- exact existing Case envelopes and final results remain unchanged;
- progress failures are nonfatal;
- built-in Benchmarks share registry-wired, pure Case/scoring seams.

Blocked by OME-931. Canonical spec, plan, and ledger will be created in this worktree before
implementation begins.

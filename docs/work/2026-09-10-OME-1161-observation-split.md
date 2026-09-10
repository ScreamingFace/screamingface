---
ticket: OME-1161
stack: screamingface-engine
status: done
started: 2026-09-10
finished: 2026-09-10
---

# Split delivery into reviewable units

## Intent and plan

Owner requires sequential main-based PRs, each at most 500 added plus deleted lines
including tests/docs. Preserve complete work locally; PR 897 keeps only observation
ports/dispatch and unit tests. Execution integration and activity follow after merge.

## Verification and acceptance

Keep callback faults, context isolation, cancellation and loss-validation coverage.
Relocate integration/activity tests with their implementation; owner authorized the split.
Pre-PR tests stay unchanged. Require full Engine gates and verify the final PR line count.
Known-consumer implementations remain at 1344cb62 (foundation) and 01b3a0f1 (activity),
on local `OME-1161-foundation-preserved` and `OME-1161-activity-preserved` branches.

## Outcome

Standalone Engine gates pass; ports and 16 focused tests fit in a 494-line full diff.
Preserve this code checkpoint locally before making PR 897 docs-only, as the owner
subsequently requested. No later PR is open; OME-1161 remains open.

---
ticket: OME-1135
status: completed
started: 2026-09-24
finished: 2026-09-24
---
# Reject cyclic activity ancestry

## Intent and plan
Owner requested all three review follow-ups. Preserve existing behavior, fix the Client
cycle defect, and refresh Engine branches onto current main without merging PRs.
Existing specs remain authoritative; no new product behavior or dependencies.

## Test plan and acceptance
Append regression tests before cycle fix. Preserve nearest valid stage, reject cyclic
ancestry without hiding stage summaries. Integrate upstream async grading without losing
judge transport or activity scope. Full affected-stack gates and focused actual transport
tests. Push with explicit leases; preserve PR review status. No paid calls or merges.

## Outcome
Added regression tests reproducing three cyclic parentage failures before implementation. Validate the entire parent chain before assigning a model call to its nearest stage; cyclic or missing ancestry stays unassigned and cannot hide stage summaries. Valid nested ownership remains intact. New and existing group tests passed; independent review passed 16 focused tests. Full Client gates passed, including 95% coverage, notebook checks, build and distribution validation. Local real Engine HTTP smoke verified two numbered grading rows. Hosted fake-provider acceptance was not rerun and remains explicitly outstanding in the PR; no paid calls or merge performed.

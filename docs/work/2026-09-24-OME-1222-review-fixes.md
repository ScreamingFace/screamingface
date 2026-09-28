---
ticket: OME-1222
status: completed
started: 2026-09-24
finished: 2026-09-24
---
# Integrate stage events with upstream Inspect grading

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
Restacked on refreshed #988. Preserved upstream board_aggregate_async and judged-scoring transport while retaining all four activity stages and async imported-board aggregation. Migrated three stage-test imports to the world candidate adapter. Full Engine gates passed with Inspect installed. Independent review passed 39 focused tests and a real Inspect scorer/URL4 sink probe covering success, failure, context, pinned judge parameters and scores. Local two-case HTTP smoke verified numbered grading rows without paid calls. Restacking on the base import commit preserved the exact tested Engine tree. No merge performed.

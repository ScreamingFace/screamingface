---
ticket: OME-1228
status: completed
started: 2026-09-24
finished: 2026-09-24
---
# Refresh case attribution onto current main

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
Rebased onto main 37a9e644 and migrated four test imports to the upstream world candidate adapter. Behavioral assertions unchanged. Full Engine gates passed with Inspect installed (lint, format, typing, layering, tests and coverage). The approved append-only exception covers the import migration. No product behavior changed; no merge performed.

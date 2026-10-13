---
id: OME-1221
linear_url: https://linear.app/openmined/issue/OME-1221
status: in_review
type: bug
priority: high
labels: [bug, aigateway, agentic]
created: 2026-09-17
---

# Make snapshot merge serving and degradation telemetry concurrency-honest

A cache hit on a key that an open snapshot merge was replacing waited for the whole merge. The
merge's `metadata_degraded` count could also blame the load for a block that a concurrent writer
had cleared.

Ledger: `docs/work/2026-10-08-snapshot-merge-concurrency.md`.

- 2026-09-17: filed from the PR #930 review (parent context OME-951).
- 2026-10-08: owner chose option A2. While a merge runs, a hit's `hit_count` bump skips a locked
  row instead of waiting, and concurrent hits still all count. The degradation count now locks
  the rows it counts, so "at least" is true. Implemented; gates and the PG lane are green; PR opened.

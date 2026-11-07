---
id: OME-1763
linear_url: https://linear.app/openmined/issue/OME-1763
status: in_progress
type: task
priority: 3
labels: [scoreboard]
created: 2026-10-29
closed:
---

# Load the benchmark catalog with one compact summary

Implements option C from the ticket's 2026-10-29 recommendation, approved by the
owner on 2026-11-03: alphabetical, Has scores on by default, include-unscored
control, search before nine-card paging. Includes the coordinated OME-1383 search.
No caching. Two fixed backend reads, one browser request.

Ledger: `docs/work/2026-11-03-benchmark-catalog-summary.md`.

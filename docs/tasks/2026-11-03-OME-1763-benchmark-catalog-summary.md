---
id: OME-1763
linear_url: https://linear.app/openmined/issue/OME-1763
status: done
type: task
priority: 3
labels: [scoreboard]
created: 2026-10-29
closed: 2026-11-06
---

# Load the benchmark catalog with one compact summary

Implements option C from the ticket's 2026-10-29 recommendation, approved by the
owner on 2026-11-03: alphabetical, Has scores on by default, include-unscored
control, search before nine-card paging. Includes the coordinated OME-1383 search.
No caching. Two fixed backend reads, one browser request.

Ledger: `docs/work/2026-11-03-benchmark-catalog-summary.md`.

Merged [PR #1659](https://github.com/ScreamingFace/screamingface/pull/1659)
on 2026-11-06, commit `f4f03ab30f25889f60fdcfdee13df50cac1b29a0`. Linear is Done for OME-1763 and OME-1383
(the catalogue search shipped in the same PR).

---
id: OME-1869
linear_url: https://linear.app/openmined/issue/OME-1869/count-only-unclaimed-runs-in-the-run-queues-depth-and-oldest-age
status: done
type: bug
priority: medium
labels: [bug, screamingface-engine, agentic]
parent:
created: 2026-11-10
closed: 2026-11-11
---

# Count only unclaimed runs in the run queue's depth and oldest age

`RunQueue.depth()` returned the run-queue stream's message count. The stream uses WORK_QUEUE
retention and a worker acks a run only at its end, so the count included running runs.
`oldest_age()` read the stream's first message, which is often a running run. The queue-depth
gauges, the `Retry-After` drain estimate and the depth ceiling inherited both errors.

The fix reads the per-bucket consumers: depth is the sum of `num_pending`, and the oldest age is
the first undelivered message's age. `held()` keeps the old stream count.

- 2026-11-10: filed as a `bug` (Triage, unassigned, Irina + Kevin tagged); fix on branch
  `OME-1869-queue-depth-unclaimed`. Owner approved deleting 4 tests that pinned the old reading.
- Ledger: `docs/work/2026-11-10-queue-depth-unclaimed.md`
- 2026-11-11: PR #1737 merged as `5bdaa8569`; Linear Done with the close-comment.

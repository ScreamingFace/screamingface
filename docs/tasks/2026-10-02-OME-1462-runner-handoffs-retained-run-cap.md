---
id: OME-1462
linear_url: https://linear.app/openmined/issue/OME-1462/cover-the-runner-hand-offs-from-12151216-and-decide-the-failed-run
status: in_review
type: task
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1129
created: 2026-10-02
closed:
---

# Cover the runner hand-offs from #1215/#1216 and decide the failed-run stream budget

Tests for the two hand-offs in `runner/main.py::_run_process` that survived mutation
(`SpanRelay(traceparent=)`, the no-pool `retain=` wiring). The owner's decision on the stream
budget: a per-subject cap (messages and bytes) for retained failed/timed-out runs on the
shared `url4-events` stream, enforced by a trim at reclaim time. The duplicated span-sink
loader moves into `tracing/`. The three unconfirmed minors are triaged in the ledger.

- 2026-10-02: ticket filed by the owner; decision comment (per-subject cap) by the owner;
  work started on branch `bershadsky/ome-1462-cover-the-runner-hand-offs-from-12151216-and-decide-the`,
  ledger `docs/work/2026-10-02-OME-1462-runner-handoffs-retained-run-cap.md`.

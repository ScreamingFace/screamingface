---
id: OME-1924
linear_url: https://linear.app/openmined/issue/OME-1924/show-who-owns-each-queued-run-and-when-it-will-start-and-give-the
status: in_progress
type: task
priority: 3
labels: [screamingface-engine, agentic, design-session]
parent: OME-1314
created: 2026-11-15
closed:
---

# Show who owns each queued run and when it will start, and give the longest-waiting run the next slot

Part 1 (this PR): the App logs `run created` (owner key, Run facts) and names the owner key, Run
and Candidate on `run scheduled`; the runner logs `run claimed` (queue wait) and `run finished`
(outcome); the 300 s notice's operator line carries `waiting=` and `running=`, the user's frame
`run.queue_waiting`. Parts 2 (admin queue view) and 3 (wait-aware rotation) follow in their own
units. Spec: `docs/spec/2026-11-16-OME-1924-queue-visibility-logs.md`. Ledger:
`docs/work/2026-11-16-queue-visibility-logs.md`.

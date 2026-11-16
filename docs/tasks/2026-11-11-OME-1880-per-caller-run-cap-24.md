---
id: OME-1880
linear_url: https://linear.app/openmined/issue/OME-1880/raise-the-per-caller-run-cap-to-24-and-apply-queue-consumer-caps-at
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1314
created: 2026-11-11
closed:
---

# Raise the per-caller run cap to 24 and apply queue consumer caps at worker start

One user could have 8 runs in flight and 4 executing. The admission cap default is now 24, with a
chart value. A starting worker updates each queue consumer's `max_ack_pending` in place, so a new
`runnerPool.maxAckPending` reaches existing consumers. `GET /v1/limits` returns the enforced cap.

- 2026-11-11: filed under epic `OME-1314` (E23) at PR-open. SDK half: `OME-1881`.
- Spec: `docs/spec/2026-11-10-per-user-parallel-runs.md`
- Ledger: `docs/work/2026-11-10-per-user-parallel-runs.md`

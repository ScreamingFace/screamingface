---
id: OME-1142
linear_url: https://linear.app/openmined/issue/OME-1142/make-the-runner-pools-max-ack-pending-an-explicit-per-caller-allowance
status: in_progress
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-08
closed:
---

# Make the runner pool's max_ack_pending an explicit per-caller allowance

The chart renders `URL4_CLOUD_RUN_QUEUE_MAX_ACK_PENDING` as `replicas x workerSlots`, claiming
the value is a fleet-wide bound. Since the bucket split (OME-1091) the queue creates one
durable consumer per bucket subject and a caller hashes to exactly one bucket, so the value is
a per-caller allowance. Deriving it from fleet size therefore sets every caller's personal cap
to the whole fleet's slot count, letting one caller saturate the pool at any replica count.

Add an optional `runnerPool.maxAckPending` values key (unset keeps the derived product),
register it in the chart schema (`runnerPool` is `additionalProperties: false`), and correct
the comments in the template and in `runner_queue.py` that assert the fleet-bound premise.

Blocks the infra-side change to run the pool at `replicas: 2` with the per-caller cap pinned
at 4.

Spec: `docs/spec/2026-09-08-OME-1142-maxackpending-per-caller.md`
Plan: `docs/plan/2026-09-08-OME-1142-maxackpending-per-caller.md`
Ledger: `docs/work/2026-09-08-OME-1142-maxackpending-per-caller.md`

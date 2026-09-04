---
id: OME-1090
linear_url: https://linear.app/openmined/issue/OME-1090/derive-run-status-from-the-event-stream-and-make-cancellation-queue
status: planned
type: task
priority: high
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-02
closed:
---

# Derive run status from the event stream and make cancellation queue-aware

With no Job to read, status becomes a pure function of the run's own event stream plus capability validity: terminal frame means its outcome, `StartedEvent` without one means running, neither means queued or not-found. This needs no new store, is correct across App replicas, and retires OME-1059's conflation structurally. Cancellation of a queued run writes `Terminated(stopped)` so the worker later claims, sees it, and never executes; a running run is reached over a control subject.

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`
Plan: `docs/plan/2026-09-02-OME-1086-queue-worker-pool-runner.md`

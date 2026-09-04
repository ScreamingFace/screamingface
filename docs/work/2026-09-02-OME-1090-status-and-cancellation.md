---
ticket: OME-1090
stack: screamingface-engine
status: in_progress
started: 2026-09-02
finished:
---

# OME-1090 — Derive run status from the event stream and make cancellation queue-aware

## Intent

Status and cancellation currently read and mutate a Kubernetes Job. With no Job,
both need a new source of truth — and the honest one already exists: the run's
own event stream. Status becomes a pure function of the event stream plus
capability validity (terminal frame → its outcome; `StartedEvent` without one →
running; neither, capability unexpired → scheduled; neither, capability expired
→ not_found). No new store, correct across App replicas, and it retires
OME-1059's conflation structurally. Cancellation of a queued run writes
`Terminated(stopped)` so the worker later claims, sees it, and never executes; a
running run is reached over a control subject.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py`
  (new) — `QueueJobRunner(IdentityAwareJobRunner)`: `schedule()` publishes;
  `stop()` writes the tombstone and sends the control request; `status()` /
  `exists()` derive from the event stream plus capability validity.
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py`
  (modify) — select it.
- `apps/screamingface-engine/src/screamingface_engine/worker/loop.py` (modify) —
  control subscription (`url4.runctl.*`; only the owner replies).
- `apps/screamingface-engine/src/screamingface_engine/app.py` (modify) —
  subscribe to `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.*` and publish a
  named terminal failure for a run the queue gave up on.
- `apps/screamingface-engine/src/screamingface_engine/ws/bridge.py` (modify) —
  queue-position notice through the existing `add_notifier` path.
- Tests: `tests/unit/test_queue_runner_*.py` (new).

## Test plan

- RED: the spec's status truth table, one test per row, including the
  capability-expiry boundary between `scheduled` and `not_found`.
- RED: cancel-before-claim — `DELETE /` writes `Terminated(stopped)`; the worker
  then claims, skips, and acks exactly once.
- RED: cancel-while-running — the control request reaches only the owning
  worker; the child is terminated; `Terminated(stopped)` appears once.
- RED: `stop()` on an unknown topic stays idempotent and `DELETE /` still
  returns 204.
- RED: `RunReaper` audience loss cancels a queued run.
- RED: the queue-position notice reaches an attached socket and is superseded
  once `StartedEvent` arrives.

## Acceptance

- `QueueJobRunner` implements `IdentityAwareJobRunner` with no port changes.
- Status is a pure function of the event stream; no new store.
- Engine stack gates green (cov >= 80).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - New: `src/screamingface_engine/adapters/queue_runner.py` (`QueueJobRunner` +
    `ControlClient`), `src/screamingface_engine/adapters/max_deliveries.py`
    (`MaxDeliveriesAdvisor`), `tests/unit/test_queue_runner_status.py`,
    `tests/unit/test_queue_runner_cancel.py`, `tests/unit/test_queue_position_notice.py`,
    `tests/unit/test_max_deliveries_advisory.py`.
  - Modified: `adapters/factory.py` (selects the queue backend), `adapters/jetstream.py`
    (`stream_exists`), `app.py` (advisor installer + queue-runner `aclose` wiring),
    `config.py` (`RunnerBackend` gains `"queue"`), `notices.py` (`info`),
    `rest/routes.py` (queue-position notice), `subjects.py` (`url4.runctl`),
    `worker/loop.py` (control subscription), `worker/supervisor.py` (`CANCELLED`,
    `children_by_topic`, `cancelled`), `tests/unit/test_worker_claim.py`,
    `tests/unit/test_reaper.py`, `tests/unit/test_runners_factory.py`.
- **Commits:** <sha — message>
- **Gates:** ruff check/format clean, pyright 0 errors, layering OK, pytest
  `2333 passed, 8 skipped` at 90.96% coverage (floor 80%).
- **Deviations:**
  - `exists()` answers True only for `scheduled`/`running` (a terminal run does not
    exist) — the reaper's contract, which keeps an audience-loss stop from landing a
    second terminal frame on a finished run. This matches the in-process runner and
    differs from k8s (where a finished Job exists until TTL).
  - The capability-validity input is an in-memory schedule-time record (like
    `InProcessJobRunner._tasks`), not a durable store; the terminal/running rows are
    cross-replica correct, the scheduled/not_found boundary is local (documented in the
    adapter docstring).
  - `_build_artifact_reader` now refuses filesystem storage for `runner="queue"` too
    (the run executes in a worker pod, not this App's disk).

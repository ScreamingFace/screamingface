---
ticket: OME-1091
stack: screamingface-engine
status: in_progress
started: 2026-09-02
finished:
---

# OME-1091 — Admit runs on queue depth and fair-schedule them per caller

## Intent

Admission moves from namespace quota headroom to queue depth, keeping the
reservation counter OME-1065 built because the read-modify-write race survives
the change of resource. `Retry-After` becomes a drain estimate instead of a
hard-coded 1. Fairness lands as per-caller subjects with round-robin pull plus a
per-caller in-flight cap — the run-level half of OME-908 — and a spawn-time io
budget; dynamic rebalancing via a parent-held gate stays a declared follow-up.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py`
  (modify) — depth-based admission raising `JobRunnerAtCapacity`; per-caller
  in-flight cap.
- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (modify)
  — per-caller buckets (stable hash of the identity, not the raw address),
  round-robin pull.
- `apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py`
  (modify) — spawn-time io budget `worker_io_capacity / max(1, active_children)`
  via `URL4_CLOUD_IO_CONCURRENCY`.
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` (modify)
  — derived `Retry-After` from a drain estimate.
- Tests: `tests/unit/test_queue_admission.py`, `tests/unit/test_queue_fairness.py`
  (new).

## Test plan

- RED: depth at ceiling raises `JobRunnerAtCapacity`, and the REST edge answers
  503 with a `Retry-After` derived from depth and throughput, not the constant 1.
- RED: two admissions racing the last slot inside one refresh window cannot both
  pass — the reservation counter carried over from OME-1065.
- RED: a per-caller in-flight cap refuses caller A's N+1 run while caller B is
  still admitted.
- RED: round-robin pull interleaves two callers' runs instead of draining one
  caller first.
- RED: the spawn-time io budget equals `worker_io_capacity / active_children`
  and appears in the child env as `URL4_CLOUD_IO_CONCURRENCY`.

## Acceptance

- Admission has one authority (queue depth); `Retry-After` is derived.
- One caller's 9-candidate evaluation cannot occupy every slot.
- Engine stack gates green (cov >= 80).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (modify) — per-caller
    buckets (`url4-runq.<bucket>`, stable hash of the identity value), wildcard stream
    declaration with on-exists subject migration, round-robin pull (one message per bucket per
    cycle, bounded total timeout), per-bucket durable consumers.
  - `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py` (modify) —
    depth-based admission raising `JobRunnerAtCapacity` with a derived `retry_after_s`; the
    OME-1065 reservation counter carried over; per-caller in-flight cap with
    observed-terminal + capability-expiry release.
  - `apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py` (modify) —
    spawn-time io budget `worker_io_capacity / max(1, active_children)` via
    `URL4_CLOUD_IO_CONCURRENCY`.
  - `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` (modify) — derived
    `Retry-After` from the exception's drain estimate, constant 1 as fallback.
  - `apps/screamingface-engine/src/screamingface_engine/config.py` (modify) —
    `run_queue_bucket_count`, `run_queue_caller_inflight_cap`.
  - `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py`,
    `worker/loop.py` (modify) — wire the new settings.
  - `apps/screamingface-engine/src/screamingface_engine/adapters/max_deliveries.py` (modify) —
    advisory subject wildcard for per-bucket consumers.
  - `apps/screamingface-engine/src/screamingface_engine/subjects.py` (modify) — comment only.
  - `packages/url4/src/url4/streaming/interfaces/jobs.py` (modify) — `JobRunnerAtCapacity`
    gains optional `retry_after_s`.
  - Tests: `tests/unit/test_queue_admission.py`, `tests/unit/test_queue_fairness.py` (new);
    fakes updated in `test_queue_runner_status.py`, `test_queue_runner_cancel.py`,
    `test_reaper.py`; stream-config and advisory tests updated.
  - `docs/tasks/2026-08-26-OME-908-fair-run-scheduling.md` (modify) — comment stating which
    half OME-1091 closes and which remains (dynamic rebalancing).
- **Commits:** feat(engine): admit runs on queue depth and fair-schedule them per caller
  (branch tip; squash-merge sha recorded in the Linear close, per the repo's ledger pattern)
- **Gates:** ruff check clean; ruff format clean; pyright 0 errors; layering OK;
  pytest 2344 passed, 8 skipped (NATS-dependent integration), coverage 90.93% (>= 80).
- **Deviations:**
  - The per-caller in-flight count is released when the runner OBSERVES a terminal frame
    (reaper polls, re-schedule pre-checks) or the capability expires — the runner cannot
    observe a finish any other way; a run that finishes while its client stays attached
    counts until the next observation. Documented in the code.
  - The drain estimate is `(depth - ceiling) / (depth / oldest_age)`, floored at 1 — the
    pool's throughput inferred from the oldest message's wait; no separate throughput
    counter was added.
  - `JobRunnerAtCapacity` (shared package) gained an optional `retry_after_s` field so the
    estimate travels with the refusal.

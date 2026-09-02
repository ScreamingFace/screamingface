---
ticket: OME-1088
stack: screamingface-engine
status: in_progress
started: 2026-09-02
finished:
---

# OME-1088 — Add the durable run queue

## Intent

The run queue is the new substrate of OME-1086. It must be durable (an accepted
run may not be lost), deduplicating (a retried submission is not a second run),
and it must not collide with the per-run event streams that already live in the
same broker. A dedicated JetStream stream with `retention=WorkQueue`, file
storage, and 3 replicas, consumed by a durable pull consumer. Publishing with
`Nats-Msg-Id` set to the topic makes the broker dedupe a resubmission itself,
preserving today's `JobAlreadyExists` meaning with no lookup table.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (new) —
  stream declaration, dedupe publish, durable pull consumer, depth/oldest-age
  signal, message codec through `job_env`.
- `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py`
  (modify) — split `_consumer_config()` into two named builders; explicit queue
  exclusion in `owns_stream()`.
- `apps/screamingface-engine/src/screamingface_engine/config.py` (modify) — queue
  settings with defaults.
- Tests: `tests/unit/test_run_queue_stream_config.py`,
  `tests/unit/test_run_queue_sweeper_exclusion.py`,
  `tests/unit/test_jetstream_consumer_config_split.py`,
  `tests/integration/test_run_queue_roundtrip.py` (new).

## Test plan

- RED: queue stream declared with `retention=WorkQueue`, `storage=file`,
  `num_replicas=3`, name not starting with `url4-cloud_`.
- RED: `owns_stream()` refuses the queue name; a sweep with the queue present
  leaves it alive (Trap 1 — the most important test in the epic).
- RED: event-stream consumer config still returns `AckPolicy.NONE` after the
  split; the queue's returns `EXPLICIT` with `max_deliver=2`, `ack_wait`,
  `max_ack_pending` (Trap 2).
- RED: a duplicate publish of one topic yields exactly one message
  (`Nats-Msg-Id` dedupe).
- RED: a queue message round-trips to the identical env mapping the Job path
  produces (no second encoding).

## Acceptance

- The queue stream is declared with the spec's properties and survives a sweep.
- The event-stream consumer config is unchanged (`AckPolicy.NONE`).
- Engine stack gates green (cov >= 80), `check_layering.py` satisfied.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
  - `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (new) — `RunQueue`
    (stream declaration, dedupe publish, durable pull, depth/oldest-age with a ~2s cache),
    the message codec through `job_env`, and the work-queue consumer-config builder.
  - `apps/screamingface-engine/src/screamingface_engine/subjects.py` — `RUN_QUEUE_STREAM` /
    `RUN_QUEUE_SUBJECT` naming + explicit queue exclusion in `owns_stream()`.
  - `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py` —
    `_consumer_config` renamed to `_broadcast_consumer_config` (Trap 2 split, first half).
  - `apps/screamingface-engine/src/screamingface_engine/config.py` — queue settings with
    defaults (stream name, subject prefix, duplicate window, max_age backstop, ack_wait,
    max_deliver, worker_slots, max_ack_pending, depth ceiling).
  - Tests: `tests/unit/test_run_queue_stream_config.py`, `tests/unit/test_run_queue_sweeper_exclusion.py`,
    `tests/unit/test_jetstream_consumer_config_split.py`, `tests/unit/test_run_queue_codec.py`,
    `tests/integration/test_run_queue_roundtrip.py` (all new);
    `tests/unit/test_jetstream_subscribe_ensures_stream.py` and `tests/unit/test_local_app.py`
    updated for the rename / precise probe.
  - `.github/workflows/screamingface-engine-tests.yml` — the roundtrip test added to the
    real-NATS conformance job.
- **Commits:** 4eceb651 — feat(engine): add the durable run queue (OME-1088)
- **Gates:** ruff check ✓ · ruff format --check ✓ · pyright 0 errors ✓ ·
  check_layering.py LAYERING OK ✓ · pytest 2296 passed / 7 skipped (real-NATS-gated),
  coverage 91.55% (>= 80) ✓. Integration roundtrip verified against a real single-node
  NATS broker (replicas=1 there; the 3-replica property is pinned by the unit suite).
- **Deviations:**
  - `RunQueue` takes a `replicas` constructor parameter (default 3): a single-node broker
    (local dev, the CI conformance job) refuses `replicas > 1`, so the real-broker tests
    declare the stream with one replica. The spec's 3 is the production default and is pinned
    by `test_run_queue_stream_config.py`.
  - The work-queue consumer-config builder lives in `runner_queue.py` (the module that owns
    the queue) rather than beside the broadcast builder in `jetstream.py`; the split is still
    two named builders with no branch in the event-stream one.
  - `depth()`/`oldest_age()` read the raw `STREAM.INFO` response via `js._api_request`
    (nats-py's `StreamState` drops `first_ts`); documented in `runner_queue._state`.
  - `tests/unit/test_local_app.py`'s run-mode probe made precise (dot-suffixed) because the
    new shared leaf `runner_queue` starts with `runner`.

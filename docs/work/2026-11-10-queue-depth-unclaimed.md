---
ticket: OME-1869
stack: screamingface-engine
status: done      # planned | in_progress | done | blocked
started: 2026-11-10
finished: 2026-11-10
---

# queue-depth-unclaimed — queue depth counts unclaimed runs, not held messages

## Intent

`RunQueue.depth()` says "how many runs are queued but not yet started". It returns the
stream message count. The queue stream uses WorkQueue retention and a worker acks a run
only at the run's end. Thus the count is queued + running. `oldest_age()` reads the
stream's `first_ts`, which is often a RUNNING run. The App uses these two values for the
`/metrics` gauges `screamingface_engine_queue_depth` and
`screamingface_engine_queue_oldest_unclaimed_age_s`, for the depth ceiling at admission, and
for the `Retry-After` drain estimate. All three are wrong when runs are running. This unit
measures UNCLAIMED runs exactly from the per-bucket durable consumers, and it keeps the
stream count under the honest name `held()`. Spec:
`docs/spec/2026-11-10-queue-depth-unclaimed.md`. Plan:
`docs/plan/2026-11-10-queue-depth-unclaimed.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` — `BucketReading`,
  `RunQueue.bucket_readings()`, `RunQueue.held()`; `depth()` and `oldest_age()` read
  unclaimed runs; docstrings.
- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py` —
  docstrings only (depth ceiling = unclaimed backlog; drain estimate inputs).
- `apps/screamingface-engine/src/screamingface_engine/metrics.py` — oldest-age help text.
- `apps/screamingface-engine/src/screamingface_engine/config.py` — ceiling comment.
- `apps/screamingface-engine/deploy/helm/README.md` — admission paragraph.
- NEW `apps/screamingface-engine/tests/unit/test_run_queue_unclaimed_depth.py`
- NEW `apps/screamingface-engine/tests/unit/test_queue_drain_estimate_unclaimed.py`
- NEW `apps/screamingface-engine/tests/integration/test_queue_unclaimed_depth_nats.py`
- `.github/workflows/screamingface-engine-tests.yml` — add the integration file to the
  `conformance` job (run list and skip-check list).

## Test plan

- Unit (fake JetStream with `consumer_info` / `get_msg` / `stream_info`): reading order and
  mapping, `None` fields, consumer not found, unclaimed sum, cold-start fallback to the
  subject count, oldest unclaimed head per bucket, races (`get_msg` not found), cache, no
  consumer bind from the App, broker errors propagate, `held()`.
- Adapter (real `RunQueue` over the fake): running runs do not count to the ceiling; the
  refusal's `Retry-After` uses unclaimed depth and oldest unclaimed age; the `/metrics`
  gauges show unclaimed values.
- Integration (real NATS 2.10): 2 bucket consumers `max_ack_pending=4`; 6 to A, 2 to C;
  fetch 4 from A, no ack → unclaimed 4, held 8, oldest unclaimed = A's 5th message; a NAK
  keeps the run in "running".

## Acceptance

- `depth()` = undelivered runs; `held()` = stream messages; `oldest_age()` = age of the
  oldest undelivered run.
- The App never creates or binds a consumer.
- Gates green; no prior test edited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (runner_queue.py, adapters/queue_runner.py docstrings,
  metrics.py help text, config.py comment, deploy/helm/README.md, the workflow's
  `conformance` run list AND skip-check list, the three new test files, spec, plan).
- **Commits:** `5bdaa8569` fix(screamingface-engine): count only unclaimed runs in queue depth and
  oldest age (#1737), squash-merged 2026-11-11 01:01 UTC. Linear `OME-1869` Done with the close-comment.
- **Resolution (2026-11-10):** the owner approved deleting the four prior tests below. They and
  the fake's unused `api_calls` / `_state` / `_prefix` / `_api_request` are removed; approval
  `.claude/test-change-approvals/OME-1869.json` pins the file's blob pair. Issue `OME-1869`
  filed as a `bug` (Triage, unassigned, Irina + Kevin tagged); mirror
  `docs/tasks/2026-11-10-OME-1869-queue-depth-unclaimed.md`. The two "recommended" integration
  retargets below were NOT approved and are left as they are.
- **Gates (final):** `run_gates.py screamingface-engine` with the append-only check — all
  green (see the commit's run). First run, before the approval: ruff, ruff format, pyright,
  check_layering green; pytest `4 failed, 8686 passed, 351 skipped`, coverage 96.36 %.
  The 4 failures were the prior tests listed below and nothing else. New tests: 17 unit
  (`test_run_queue_unclaimed_depth.py`), 3 adapter (`test_queue_drain_estimate_unclaimed.py`),
  2 integration (`test_queue_unclaimed_depth_nats.py`, green against a local nats-server
  v2.10.22; the conformance file list is 56 passed against it).
- **BLOCKED — prior tests encode the old semantics (append-only rule; owner approval needed).**
  `tests/unit/test_run_queue_stream_config.py` pins `depth()` / `oldest_age()` to one raw
  `STREAM.INFO` request through a fake with no `consumer_info`:
  1. `test_depth_and_oldest_age_come_from_one_stream_info_round_trip`
  2. `test_depth_is_cached_within_the_ttl`
  3. `test_the_cache_expires_after_the_ttl`
  4. `test_an_empty_queue_reports_no_age_even_though_the_server_sends_a_zero_time`
  Proposed change: delete the four tests (and the fake's now-unused `_api_request` /
  `_state`). Their invariants are re-pinned against the new reading in
  `test_run_queue_unclaimed_depth.py` (1 → `test_depth_and_oldest_age_share_one_cached_reading`
  + `test_held_is_the_stream_message_count_queued_plus_running`; 2 → the same cache test;
  3 → `test_the_unclaimed_reading_expires_after_the_ttl`; 4's empty-queue half →
  `test_nothing_unclaimed_has_no_age_and_reads_no_message`). 4's Go-zero-time guard has no
  target any more: the age comes from a real message's timestamp, never from `first_ts`.
  Needs a `.claude/test-change-approvals/<OME-N>.json` entry for that file.
- **Recommended, not failing:** `tests/integration/test_run_queue_roundtrip.py`
  (`_wait_for_depth`, line 109) and `tests/integration/test_worker_spine.py`
  (`_wait_for_depth`) assert "the ack removed the message" through `depth()`. They still
  pass, but now prove less (depth reaches 0 at delivery). Retarget to `queue.held()`.
  `tests/unit/test_nats_private_api_surface.py` pins a private-API dependency
  (`_api_request` for `first_ts`) the queue no longer has; retire it.
- **Deviations:** none from the spec. `runner_queue.py` is 1347 lines (was 1248; over the
  450-line guide before this unit). `test_worker_spine.py` fails locally on macOS on base and
  on this branch alike (`RLIMIT_AS`: "current limit exceeds maximum limit"); not in CI's
  conformance list.

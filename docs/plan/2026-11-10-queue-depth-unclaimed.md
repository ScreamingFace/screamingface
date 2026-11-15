# queue-depth-unclaimed — Implementation plan

## Frame

Make `RunQueue.depth()` and `RunQueue.oldest_age()` measure unclaimed runs from the
per-bucket durable consumers. Add `BucketReading`, `RunQueue.bucket_readings()` and
`RunQueue.held()`. Correct every docstring and help text that describes the values. The
`QueueJobRunner` logic does not change; its inputs become correct (spec D5–D7).

## Changes

1. `src/screamingface_engine/runner_queue.py`
   - `BucketReading` (frozen, slotted dataclass; spec D1). Export it.
   - `RunQueue.bucket_readings()` — `asyncio.gather` of `js.consumer_info(self._stream,
     _consumer_for(s))` over `bucket_subjects()`; `NotFoundError` → `None`.
   - `RunQueue._read_unclaimed()` — readings + `delivered.stream_seq` (needs the raw
     `ConsumerInfo`, so a private `_consumer_infos()` feeds both `bucket_readings` and this),
     the cold-start subject counts (one `stream_info(subjects_filter="<prefix>.>")` only when
     a reading is `None`), and the head timestamps (`get_msg(..., next=True)` per bucket with
     a backlog, concurrent; `NotFoundError` → skip). Returns `(unclaimed, oldest_ts)`.
   - `RunQueue._unclaimed()` — the cached wrapper (`state_cache_ttl_s`).
   - `depth()`, `oldest_age()` read `_unclaimed()`.
   - `held()` — `js.stream_info(self._stream).state.messages`, uncached.
   - Remove `_state` and `_state_cache` (private `first_ts` path; spec D5).
   - Module and constant docstrings that describe depth.
2. `src/screamingface_engine/adapters/queue_runner.py` — docstrings: `_Queue.depth` /
   `oldest_age`, the `depth_ceiling` comment (unclaimed backlog, spec D6), `queue_depth`,
   `queue_snapshot`, `_refresh_if_stale`, `_drain_estimate_s` (spec D7).
3. `src/screamingface_engine/metrics.py` — oldest-age help text: "Seconds since the oldest
   unclaimed run was published to the queue."; class docstring.
4. `src/screamingface_engine/config.py` — `run_queue_depth_ceiling` comment.
5. `deploy/helm/README.md` — the Admission paragraph names unclaimed runs.
6. `.github/workflows/screamingface-engine-tests.yml` — add
   `tests/integration/test_queue_unclaimed_depth_nats.py` to the `conformance` job's run
   list AND to its skip-check list.

## Test plan (RED first; new files only)

`tests/unit/test_run_queue_unclaimed_depth.py` — a fake JetStream with `consumer_info`,
`get_msg`, `stream_info`, and a `pull_subscribe` / `add_consumer` that FAIL the test:

- readings are in bucket order, map `num_ack_pending` / `num_pending` /
  `config.max_ack_pending`, and ask for `url4-runners-<bb>` on the queue stream;
- server `None` fields → `0`, `max_ack_pending` `None` → `-1`;
- consumer not found → `None`; another broker error propagates;
- `depth()` sums `queued` and excludes `running`;
- cold start: a missing consumer contributes its subject count; no `stream_info` when all
  consumers exist;
- `oldest_age()` reads `seq = delivered + 1` with `next=True` on the bucket subject, takes
  the minimum, skips buckets with no backlog, reads from seq 1 for a missing consumer;
- `get_msg` not found (race) skips that bucket; all raced → `None`;
- nothing unclaimed → `None` and no `get_msg`;
- `depth()` + `oldest_age()` inside the TTL = one fan-out; TTL 0 = a new read;
- the App never binds or creates a consumer;
- `held()` = stream messages.

`tests/unit/test_queue_drain_estimate_unclaimed.py` — `QueueJobRunner` over a REAL `RunQueue`
and the fake JetStream:

- held ≥ ceiling but unclaimed < ceiling → admitted (spec D6);
- unclaimed ≥ ceiling → `JobRunnerAtCapacity` whose `Retry-After` comes from unclaimed depth
  and the oldest UNCLAIMED age, not the running head (spec D7);
- `queue_snapshot()` and the two `/metrics` gauges show unclaimed values; the help text says
  "unclaimed".

`tests/integration/test_queue_unclaimed_depth_nats.py` — real NATS, own stream and prefix,
3 buckets (A = 00, B = 01 with no consumer, C = 02), consumers on A and C with
`max_ack_pending=4`:

- publish 6 to A, 2 to C; fetch 4 from A, no ack → `depth() == 4`, `held() == 8`,
  `oldest_age()` ≈ age of A's 5th message (not the 1st), `bucket_readings()` = A (4, 2, 4),
  B `None`, C (0, 2, 4);
- publish 1 to B (no consumer) → `depth() == 5` (spec D2);
- NAK one of A's 4 → `depth()` still counts it as running (spec D4).

## Prior tests that break (STOP point)

`tests/unit/test_run_queue_stream_config.py` — four tests read `depth()` / `oldest_age()`
through a fake with only `_api_request`. Under spec D5 they fail. Do NOT edit them. Stop and
report the exact change needed to the owner.

## Gates

`uv run .claude/scripts/run_gates.py screamingface-engine` (ruff, ruff format, pyright,
`check_layering.py`, pytest with the 80 % floor).

## Wisdom check

- The App must never bind a consumer: a bind with the App's settings would set the
  worker's `max_ack_pending`. The fake fails the test on any bind.
- `num_pending` excludes NAK'd runs; the integration test pins it.
- Cold start must not read as an empty queue.

# queue-depth-unclaimed — queue depth counts unclaimed runs

## Problem

`RunQueue.depth()` (`apps/screamingface-engine/src/screamingface_engine/runner_queue.py`)
says "how many runs are queued but not yet started". It returns `state.messages` from one
`STREAM.INFO` request (`RunQueue._state`).

The queue stream `url4-runq` uses `RetentionPolicy.WORK_QUEUE`. The broker removes a message
only when a worker acks it. The worker acks a run only at the run's END (the terminal paths
in `worker/supervisor.py`); while the run executes, the worker sends `in_progress`
heartbeats. Thus the stream holds every queued run AND every running run:

    stream messages = queued (not delivered) + running (delivered, not acked)

`RunQueue.oldest_age()` reads the stream's `first_ts`. That is the oldest message in the
stream, which is often a RUNNING run, not a waiting one.

The App uses these two values in four places:

| Consumer | What it needs | What it gets today |
|---|---|---|
| `metrics._QueueCollector` gauge `screamingface_engine_queue_depth` ("Runs queued but not yet claimed by a worker.") | unclaimed runs | queued + running |
| gauge `screamingface_engine_queue_oldest_unclaimed_age_s` | age of the oldest unclaimed run | age of the oldest held message |
| `QueueJobRunner._admit_or_raise` depth ceiling (`run_queue_depth_ceiling`, default 10 000) | a bound on the backlog | a bound on backlog + running |
| `QueueJobRunner._drain_estimate_s` (`Retry-After`) | FIFO depth and head age of the backlog | depth and head age of held messages |

`QueueJobRunner.queue_depth()` also reads `depth()`. It has no caller.

## Decisions

### D1 — Unclaimed runs come from the per-bucket durable consumers

Each bucket subject `url4-runq.<bb>` has one durable pull consumer `url4-runners-<bb>`
(`_consumer_for`). The broker reports, per consumer:

- `num_pending` — messages on the filter subject that the consumer did not deliver yet;
- `num_ack_pending` — messages delivered and not acked (running);
- `config.max_ack_pending` — the consumer's cap.

`RunQueue` gets one shared type and one method:

```python
@dataclass(frozen=True, slots=True)
class BucketReading:
    running: int          # consumer num_ack_pending
    queued: int           # consumer num_pending
    max_ack_pending: int  # consumer config; <= 0 means no cap (JetStream -1)

async def bucket_readings(self) -> list[BucketReading | None]   # None = consumer not found
```

- The list is in `bucket_subjects()` order, one entry per bucket.
- The method sends one public `js.consumer_info(stream, name)` per bucket, gathered
  concurrently.
- A server field that is `None` becomes `0`. A `None` `max_ack_pending` becomes `-1`.
- `nats.js.errors.NotFoundError` gives `None` for that bucket. Other broker errors
  propagate.
- The method is not cached. It is the raw reading. A sibling branch
  (`runner-pool-autoscaling`) reuses it.
- `BucketReading` and `bucket_readings` stay in `runner_queue.py`, a shared leaf. They import
  no control-plane module.

INVARIANT: the App NEVER creates or binds a consumer. Only workers bind consumers, with their
own `max_ack_pending` (`_bound_subscription`). `bucket_readings` uses `consumer_info` only.

### D2 — A bucket with no consumer contributes its subject's message count

A consumer is not found at cold start (no worker has polled yet) and after an operator
deletes a consumer to change `max_ack_pending`. Two options:

| Option | Result at cold start |
|---|---|
| The bucket contributes 0 | A full backlog reads as 0. The ceiling never trips. The gauge says "empty". |
| The bucket contributes its subject's message count | Exact: see below. |

Decision: the subject's message count. Reason: with no consumer, nothing on that subject
is delivered. The stream keeps a message until an ack (WorkQueue). Thus every message on
that subject is unclaimed. A new consumer starts at the first message (deliver policy ALL),
so this agrees with what the next worker sees.

Cost: one public `js.stream_info(stream, subjects_filter="<prefix>.>")` request, which
returns `state.subjects` (subject → count). The App sends it ONLY when one or more buckets
have no consumer. In steady state (all consumers bound) the App does not send it.

Known limit: when an operator deletes a consumer while a worker still runs one of its
messages, that run counts as unclaimed until a worker binds the new consumer. This is rare
and the error is bounded by `max_ack_pending`.

A missing STREAM still raises (the `stream_info` request fails). This is the same as the
old `STREAM.INFO` path.

### D3 — The oldest unclaimed run is the first message after the consumer's delivered sequence

A consumer delivers in stream order. Thus the first undelivered message of a bucket is the
first message on that bucket's subject AFTER the consumer's `delivered.stream_seq`.

For each bucket with `queued > 0`:

```python
js.get_msg(stream, seq=start, subject=bucket_subject, next=True)
```

- `start = delivered.stream_seq + 1` for a bucket with a consumer;
- `start = 1` for a bucket with no consumer (D2).

nats-py 2.16.0 (the pinned version) sends `{"seq": start, "next_by_subj": subject}` to
`STREAM.MSG.GET`. nats-server 2.9 and later support `next_by_subj`; the CI broker is
`nats:2.10`. Verified against a local nats-server v2.10.22 on 2026-11-10.

- The age is `now − min(timestamps)`, from the stream timestamp of each head message.
- `None` when no bucket has an unclaimed run.
- A `get_msg` that answers `NotFoundError` is a race (a worker took the message between the
  two reads). That bucket gives no timestamp. Other errors propagate.
- Buckets with `queued == 0` are not read.

WHY the stream timestamp and not the `Url4-Enqueued-At` header: the old gauge measured
"since the run was published to the queue". A bound start stamps an earlier header
(`enqueued_at`), which is not queue wait.

### D4 — A NAK'd run counts as running

A NAK'd message (`release_held`, the V-4 surplus NAK) and a message whose `ack_wait`
expired wait in the consumer's redelivery queue. Measured on nats-server v2.10.22: after a
NAK, `num_ack_pending` does not change and `num_pending` does not change. The server gives
no count of the redelivery queue.

Decision: such a run counts as RUNNING. It is not in the unclaimed count and not in the
oldest unclaimed age. Reasons:

- No exact signal exists in consumer info.
- The state is short: the next fetch on that bucket redelivers the run first.
- `max_ack_pending` per bucket bounds the error.

The integration test pins this (a NAK keeps unclaimed unchanged), so a server change that
alters it fails loudly.

### D5 — `depth()` and `oldest_age()` mean unclaimed; `held()` keeps the stream count

- `depth()` = Σ `queued` over buckets with a consumer + the subject count of buckets with
  no consumer (D2). This matches the docstring that was always there.
- `oldest_age()` = D3.
- NEW `held()` = the stream's message count (queued + running), from the public
  `js.stream_info(stream)`. Uncached. No production caller needs it now. Tests need it to
  prove that an ack removes a message, and an operator needs it to read the stream.
- The private `_api_request` / `first_ts` path is removed. It existed only for `first_ts`.

The method names stay. The `QueueJobRunner._Queue` protocol and its callers do not change.
Only the meaning of the values changes, to the meaning their documentation always stated.

### D6 — The depth ceiling bounds the UNCLAIMED backlog

`run_queue_depth_ceiling` keeps its name. It now bounds runs that wait for a worker.
Reason: the worker's slot count already bounds running runs, and per bucket
`max_ack_pending` bounds them again. A ceiling on "held" would make the backlog allowance
shrink as the fleet grows. Behavior change: the App admits up to (number of running runs)
more runs than before. With the default ceiling 10 000 this change is small.

### D7 — The drain estimate keeps its formula; its inputs become correct

`_drain_estimate_s` uses `rate = depth / age` (Little's law on a FIFO backlog: the head
waited about as long as the backlog takes to drain). This is correct only for the backlog
and the backlog's head. With D5 both inputs are the backlog's. The code does not change;
its docstring states the inputs. The bucket round-robin is not strict FIFO across buckets:
the oldest head across buckets waited the longest, so the rate estimate is low and the
`Retry-After` is conservative (longer). That is the safe side.

### D8 — Caching: one fan-out per `state_cache_ttl_s`

`depth()` and `oldest_age()` share one cached reading (`_unclaimed_cache`), refreshed at
most once per `state_cache_ttl_s`. One refresh = `bucket_count` `consumer_info` requests
(concurrent), then up to `bucket_count` `get_msg` requests (concurrent, only for buckets
with a backlog), plus one `stream_info` only when a consumer is missing. The App's admission
path keeps its own window (`_refresh_if_stale`), so admission adds at most one refresh per
window, as before. The cost per refresh grows from 1 request to about 2 × `bucket_count`
small requests in 2–3 sequential rounds. This is acceptable at a 2 s window.

## Non-goals

- Changing `DEFAULT_DEPTH_CEILING`, the bucket count, or `max_ack_pending`.
- A count of the redelivery queue (D4).
- New metrics (for example a "running" gauge). `bucket_readings` makes that easy later.
- Removing `QueueJobRunner.queue_depth()`.

## Prior tests that encode the old semantics

`tests/unit/test_run_queue_stream_config.py` pins `depth()` / `oldest_age()` to one
`STREAM.INFO` request through a fake that has no `consumer_info`. These tests fail under D5.
The rules make prior tests append-only, so this unit STOPS for owner approval before any
edit to them. The plan lists the exact changes.

## Invariant this protects

The queue depth the App reports, gates on, and derives `Retry-After` from counts runs that
WAIT for a worker. A running run is never "queued".

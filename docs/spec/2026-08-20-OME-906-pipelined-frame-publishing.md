# Pipelined frame publishing for the Runner event bridge

- **Linear:** https://linear.app/openmined/issue/OME-906 (investigation origin — NOT closed by this)
- **Landing:** `apps/screamingface-engine` and `packages/url4`
- **Status:** delivered — but see the correction below

> ## CORRECTION — read this first
>
> Sections 1 to 4 record the design as it was approved. The premise of section 1 was
> **measured to be wrong** during implementation.
>
> The bridge backlog does NOT depend on how fast the publisher drains it. Across a 100x
> range of publish latency (0 ms to 10 ms per frame) the peak backlog stays flat. The cap
> bounds how many events the engine emits **between two chances for the drain to run**, and
> `url4/dag/executor.py:182` emits `NodeStarted` before it awaits anything while `:186` fans
> out over `node.deps` with an unbounded `asyncio.gather`. A DAG of width W therefore
> buffers about W events in ONE event-loop slice. The cap is a ceiling on DAG width.
>
> The full evidence is in
> `docs/work/2026-08-20-OME-906-pipelined-frame-publishing.md`.
>
> **What this spec delivered is still correct and still valuable on its own terms:** a
> two-phase publish contract that cuts wall-clock time by about 50x at a 10 ms round trip,
> and the high-water reporting that made the real cause measurable. It does NOT fix
> OME-906. Acceptance criteria 1, 2, 3 and 5 in section 8 remain open, and the real fix
> needs its own spec.

## 1. Problem

A DRACO Evaluation fails when many model calls return from the cache in a burst. The run
stops with this error:

```text
ExecutionError: event backlog exceeded the hard cap
(8192 events, 0 Log(s) already dropped) — the consumer is not keeping up
```

The run is correct. The system rejects it because of a throughput mismatch.

### 1.1 The three stages

The Runner moves events through three stages. Each stage has a different speed.

| Stage | Code | Speed |
|---|---|---|
| Producer | `url4.dag.run` calls `_Bridge.on_event` | CPU speed |
| Buffer | `_Bridge` deque, soft cap 1024, hard cap 8192 | — |
| Consumer | `_publish_execution` publishes one frame, then waits | One broker round trip per frame |

The producer is synchronous. `_Bridge.on_event` cannot use `await`. Therefore the buffer
cannot tell the producer to stop. The buffer can only discard an event or raise an error.

### 1.2 Why the cache burst causes the failure

Model latency usually holds the producer back. The cache removes that delay. The DAG then
makes events at CPU speed. The consumer still pays one broker round trip for each frame.

The measured reproduction shows the gap. 622 calls make 4228 frames. At 1 ms for each
round trip, the consumer needs approximately 4 seconds. The producer needs some
milliseconds. The buffer fills.

### 1.3 Why the relief mechanism does not help

`_Bridge.on_event` can discard only a `Log` event. All other event types are lossless.
The buffer at the moment of failure held these events:

| Event type | Count | Can be discarded |
|---|---|---|
| `NodeStarted` | 3465 | no |
| `NodeFinished` | 3605 | no |
| `Usage` | 561 | no |
| `ModelResponse` | 561 | no |
| **Total** | **8192** | — |

The buffer held no `Log` event. Therefore `_evict_oldest_log` removed nothing.

Span lifecycle events are 7070 of the 8192 events. Model events are 1122. Therefore a
change that only groups `Usage` events recovers less than 7 percent. Such a change does
not correct the failure.

## 2. Constraints

The solution must obey these constraints.

| ID | Constraint | Reason |
|---|---|---|
| C1 | The drain rate must not depend on the broker round trip | This is the defect |
| C2 | The frames must stay in order | The SDK finds gaps with the broker stream sequence |
| C3 | No span, cost, result or terminal frame is lost | Only a `Log` is safe to discard |
| C4 | A failed acknowledgement must fail the Evaluation | A hole in the stream must not report success |
| C5 | The memory must stay bounded if the publisher stalls | Protects the process |
| C6 | The high-water mark must be visible | Operators need the diagnosis |

C2 is the strongest constraint. It removes most candidate designs.

## 3. Rejected options

> Row 1 of this table is wrong. See the correction above: raising the cap is the correct
> direction, because the cap is the binding constraint and the publisher is not. 8192
> buffered events measure 2.1 MB, in a process that accepts a 1 GiB result.

| Option | Reason for rejection |
|---|---|
| Increase the 8192 cap | The cap is not the limit. The throughput ratio is the limit. A larger cap moves the failure to a larger Evaluation. |
| Group the `Usage` events | Span lifecycle events are 86 percent of the buffer. This option recovers less than 7 percent. |
| Put many frames in one broker message | The SDK expects one CloudEvent for each message. Its gap logic uses the per-message sequence. This option breaks the SDK contract. |
| Make the bridge apply backpressure | `_Bridge.on_event` is synchronous. It cannot wait. To block it stops the event loop that drains it. A correct version needs an asynchronous observer in the url4 engine. That change is large. It is out of scope. |
| Start one task for each frame in the lifecycle | Concurrent tasks reach the socket in an unknown order. The broker then assigns the stream sequence out of order. This option breaks C2. |

The last row is important. **The pipeline must exist in the transport, not in the caller.**

## 4. Design

`nats-py` 2.15 supplies the necessary primitive. `JetStreamContext.publish_async` does
three things:

1. It waits on a semaphore. The semaphore bounds the frames in flight. This satisfies C5.
2. It writes to the connection inside the call. One task therefore writes in call order.
   This satisfies C2.
3. It returns a future for the acknowledgement. This satisfies C4.

`publish_async_completed` waits for all pending acknowledgements. It is the barrier.

The design separates two ideas that `publish` holds together today:

- The transport accepted the frame, and the order is correct.
- The broker made the frame durable.

```text
Before:  drain -> publish -> wait for the broker -> drain -> ...
         one frame in flight. Throughput = 1 / round trip.

After:   drain -> publish -> drain -> publish -> ...
         up to N frames in flight, in order.
         flush() waits for all acknowledgements at the outcome boundary.
```

The consumer then runs at CPU speed. The buffer stays shallow. This satisfies C1.

### 4.1 Port contract

`packages/url4/src/url4/streaming/interfaces/stream.py` gets one new method.

`publish(topic, event)` keeps its signature. Its contract becomes:

- The frames reach the broker in call order.
- An adapter can defer the acknowledgement to `flush`.
- The caller must use exactly one task. Concurrent callers break the order guarantee.
- The method raises an error if an earlier deferred publish failed. This stops a broken
  run early.

`flush()` is new:

- It waits until every frame published before it is durable.
- It raises the first deferred failure. Then it discards the remaining deferred state.
  A later `flush` on the termination path therefore does not raise the same error twice.
- Its default body does nothing. An adapter that is durable when `publish` returns needs
  no override.

The default body makes the blast radius zero. `InMemoryEventStream.publish` appends to an
in-process log. It is durable when it returns. The test fakes are also in-process. Only
`JetStreamPublisher` overrides `flush`.

### 4.2 Lifecycle barrier

`packages/url4/src/url4/streaming/lifecycle.py` gets two calls to `flush`.

The first call is at the end of `_publish_execution`, after the result frame. The
docstring of that function states that an error from it selects the outcome arm in `run`.
A failed `flush` therefore reaches the existing failure arm. The arm publishes
`Terminated(status="failed")`. C4 needs no new control flow.

The second call is in `_terminate`, after it publishes the terminal frame. The terminal
frame is then durable before `run` returns.

### 4.3 JetStream adapter

`apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py` changes
`JetStreamPublisher`:

- `publish` calls `publish_async`. It adds a done callback to the returned future. It
  does not wait for the acknowledgement.
- `flush` calls `publish_async_completed`. Then it raises any recorded failure.
- The done callback records the first failure only. The first failure explains the run.
  The callback also reads the exception. This stops the "exception was never retrieved"
  warning.
- The adapter keeps no list of pending futures. Such a list is itself an unbounded queue.
  `nats-py` already tracks the pending set.
- The adapter states its own bound. It builds the context with
  `publish_async_max_pending=1024`. The bound is a promise of this class. It is not a
  library default.

### 4.4 The stall timeout is not used

`publish_async` accepts `wait_stall`. This design does not use it, for two reasons.

1. The hard cap of the bridge already bounds an endless stall. The frames in flight fill.
   `publish_async` then waits on the semaphore. The drain stops. The buffer reaches 8192.
   `BridgeOverflowError` follows. The memory is bounded and the run fails. C5 holds.
2. `nats-py` converts `asyncio.CancelledError` to `TooManyStalledMsgsError` on that path.
   A cancelled run would then report `failed` instead of `stopped`.

## 5. Failure behavior

| Situation | Result |
|---|---|
| Cache burst, healthy broker | The buffer stays shallow. The Evaluation completes. |
| One acknowledgement is rejected in the middle of a run | The next `publish` raises. The failure arm publishes `Terminated(failed)`. |
| The last acknowledgement is rejected | The `flush` at the end raises. The same arm runs. |
| The broker never answers | The frames in flight fill. The drain stops. The buffer reaches the hard cap. The run fails. The memory is bounded at 1024 in flight plus 8192 buffered. |
| The run is cancelled | `CancelledError` leaves the semaphore wait. The existing `stopped` arm runs. |
| Local in-memory adapter | `publish` is already durable. `flush` does nothing. The behavior does not change. |

`BridgeOverflowError` stays. It now reports only a true stall. Its message is then correct.

## 6. Observability

`RunCacheCounters` sets the precedent. Its docstring gives two reasons against Prometheus.
Both reasons apply here:

1. The run mode is a one-shot Job. It has no scrape endpoint.
2. `.claude/scripts/check_layering.py` forbids `screamingface_engine.runner.*` to import
   `screamingface_engine.metrics`.

Therefore the bridge reports through the telemetry stream of the run:

- `_Bridge` keeps a high-water mark. `on_event` updates it.
- The `BridgeOverflowError` message states the high-water mark.
- `_closing_logs` emits the high-water mark only if the run passed the soft cap. The
  docstring of that function requires silence when there is nothing to report. A mark
  below 1024 is not worth a log line.

## 7. Out of scope

- Write the bridge overflow to disk. The Linear issue asks for bounded memory and a
  failure. It does not ask for unlimited buffering.
- Make the url4 observer protocol asynchronous. This is the correct long-term shape. Its
  blast radius is too large for this correction.
- Drain the buffer in batches. No measurement supports this change.

## 8. Acceptance criteria

The criteria come from OME-906:

1. A deterministic regression test covers a DRACO-shaped cache burst with a delayed
   publisher.
2. A 100-Case DRACO Fusion Evaluation with 700 or more immediate cached Judge responses
   completes. It does not raise `BridgeOverflowError`.
3. The started, span, cost, result and terminal frames stay in order. None is lost.
4. A failed acknowledgement fails the Evaluation with a correct terminal error.
5. The memory stays bounded when the publisher stalls without end.
6. The bridge records the high-water mark for operational diagnosis.

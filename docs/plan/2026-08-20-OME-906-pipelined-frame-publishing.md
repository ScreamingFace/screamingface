# Implementation plan — pipelined frame publishing

> **Steps 1 to 4 are delivered. Step 5 is NOT, and must not be attempted as written.** The
> reproduction it asks for disproved the spec's premise: pipelining does not raise the
> overflow ceiling. See the correction at the top of the spec and the evidence in the work
> ledger. The real fix needs its own spec and plan.

- **Spec:** `docs/spec/2026-08-20-OME-906-pipelined-frame-publishing.md`
- **Linear:** https://linear.app/openmined/issue/OME-906
- **Branch:** `OME-906-pipelined-frame-publishing`
- **Stacks:** `url4` (`packages/url4`) and `screamingface-engine`
  (`apps/screamingface-engine`). Both use the `sdlc-python` skill.

## Order of work

The `url4` package holds the port. The engine holds the only override. Therefore the port
comes first. Each step is RED first, then GREEN.

| Step | Stack | Subject |
|---|---|---|
| 1 | url4 | Add `flush` to the `EventPublisher` port |
| 2 | url4 | Call `flush` at the two outcome boundaries |
| 3 | screamingface-engine | Record the bridge high-water mark |
| 4 | screamingface-engine | Make `JetStreamPublisher` pipeline its publishes |
| 5 | screamingface-engine | Add the DRACO-shaped regression test |

## Step 1 — The port method

**File:** `packages/url4/src/url4/streaming/interfaces/stream.py`

Add one method to `EventPublisher`, after `publish` and before `close`:

```python
    async def flush(self) -> None:
        """Wait until every frame published so far is durable.

        Raises the first deferred failure, then DISCARDS the remaining deferred state, so
        the termination path's own flush does not raise an error already reported.

        Does nothing by default: an adapter whose `publish` is durable when it returns has
        nothing to wait for. Only a deferring adapter overrides this.
        """
        return None
```

Extend the `publish` docstring with the two new rules:

- The frames reach the broker in call order. An adapter can defer the acknowledgement to
  `flush`.
- The caller must use exactly one task. Concurrent callers break the order guarantee.

**RED first.** `packages/url4/tests/` gets these tests:

- A minimal `EventPublisher` subclass that implements only the abstract methods. Assert
  that `await pub.flush()` returns `None`. This test covers the default body. The `url4`
  gate needs 95 percent coverage, so the default body needs a caller.
- Assert that `EventPublisher` stays abstract for `ensure_stream` and `publish`. `flush`
  must not become abstract.

**Do not** make `flush` abstract. An abstract method breaks every existing implementation
and every test fake.

## Step 2 — The lifecycle barrier

**File:** `packages/url4/src/url4/streaming/lifecycle.py`

In `_publish_execution`, after the `ResultEvent` publish, add:

```python
    await stream.flush()
```

Add a comment that states why the call is at this place: the outcome of the run is decided
after this line, so the durability must be known before it.

In `_terminate`, after the `TerminatedEvent` publish, add the same call.

**RED first.** `packages/url4/tests/` gets these tests:

- A fake publisher that counts calls. Assert `flush` runs after the result frame and
  before the terminal frame.
- A fake publisher whose `flush` raises. Assert `run` publishes
  `Terminated(status="failed")` with the error, and that `run` does not report success.
- A fake publisher that records the order of every call. Assert the terminal frame is
  published, then flushed.

**Watch the arms.** `run` has one arm for each way a run ends. The arm for
`asyncio.CancelledError` must keep its current behavior. Check that the new `flush` in
`_terminate` does not change the `stopped` outcome.

## Step 3 — The bridge high-water mark

**File:** `apps/screamingface-engine/src/screamingface_engine/runner/executor.py`

In `_Bridge.__init__`, add `self._high_water = 0`.

In `on_event`, after `self._buf.append(event)`, add:

```python
        if len(self._buf) > self._high_water:
            self._high_water = len(self._buf)
```

Add a `high_water` property beside `dropped`.

Add the mark to the `BridgeOverflowError` message.

**File:** the same module, function `_closing_logs`

Change the signature to accept the high-water mark. Emit a log frame only if the mark
passed the soft cap. The function's docstring requires silence when there is nothing to
report, so a mark below the soft cap emits nothing.

Use the attribute key style of `RunCacheCounters` for the new attribute.

**RED first.** `apps/screamingface-engine/tests/unit/test_url4_executor.py` gets these
tests:

- A burst that stays below the soft cap. Assert no high-water log frame.
- A burst that passes the soft cap. Assert one log frame with the correct value.
- Assert the `BridgeOverflowError` message holds the mark.

## Step 4 — The adapter pipeline

**File:** `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py`

`_JetStreamConnection._jetstream` must build the context with the explicit bound:

```python
self._nc.jetstream(publish_async_max_pending=_MAX_IN_FLIGHT)
```

`nats.aio.client.NATS.jetstream(**opts)` forwards the keyword. This is verified against
`nats-py` 2.15.0.

Replace `JetStreamPublisher.publish` and add `flush`:

```python
class JetStreamPublisher(_JetStreamConnection, EventPublisher):
    """...

    Publishes are PIPELINED: `publish` returns when the frame is written to the
    connection, and `flush` waits for the acknowledgements.

    WHY (OME-906): a cached DRACO burst makes span events faster than one broker round
    trip for each frame can drain. The bridge upstream cannot apply backpressure, because
    the engine's observer callback is synchronous. Therefore the bridge overflowed its
    hard cap on a run that was correct.

    INVARIANT: exactly ONE task calls `publish`. `publish_async` writes to the connection
    inside the call, so one task gives the broker the frames in call order. Two tasks void
    that order, and the SDK finds gaps by the stream sequence the broker then assigns.
    """

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        js = await self._jetstream()
        self._raise_deferred()
        ack = await js.publish_async(subject_for(topic), encode(event))
        ack.add_done_callback(self._record_failure)

    async def flush(self) -> None:
        js = await self._jetstream()
        await js.publish_async_completed()
        self._raise_deferred()
```

`_record_failure` keeps the first failure only, and reads the exception:

```python
    def _record_failure(self, ack: asyncio.Future[api.PubAck]) -> None:
        if ack.cancelled():
            return
        # Reading the exception HERE also stops the "exception was never retrieved"
        # warning on a future that nothing awaits.
        exc = ack.exception()
        if exc is not None and self._deferred_failure is None:
            self._deferred_failure = exc
```

`_raise_deferred` raises and clears:

```python
    def _raise_deferred(self) -> None:
        exc, self._deferred_failure = self._deferred_failure, None
        if exc is not None:
            raise PublishFailedError("a deferred JetStream publish was rejected") from exc
```

Keep no list of pending futures. Such a list grows with the run and is itself an unbounded
queue. `nats-py` already holds the pending set.

Decide the home of `PublishFailedError` during the step. Check first whether an existing
engine error type fits. Do not add a new type if one exists.

**RED first.** `apps/screamingface-engine/tests/unit/test_event_stream_adapters.py` gets
these tests. Replace `_jetstream` with a fake context. The unit suite has no broker.

- `publish` does not wait for the acknowledgement. Assert it returns while the future is
  pending.
- The order is kept. Publish several frames. Assert the fake received the subjects in call
  order.
- A rejected acknowledgement raises on the next `publish`.
- A rejected acknowledgement raises on `flush`.
- `flush` clears the failure. A second `flush` does not raise again.
- `flush` waits for the pending acknowledgements.
- A cancelled acknowledgement future is ignored.

Keep the existing port-conformance tests.

## Step 5 — The DRACO regression

**File:** a new test module under `apps/screamingface-engine/tests/integration/`

`InMemoryEventStream` publishes for free. It can never reproduce this defect. Therefore
the test needs a publisher fake with a delay.

Build two fakes:

- `_SerialPublisher`: `publish` waits 1 ms and is then durable. This fake models the old
  behavior.
- `_PipelinedPublisher`: `publish` returns at once and records the frame. `flush` waits
  for the recorded frames. This fake models the new contract.

Build a DRACO-shaped executor: a 100-Case protocol, a Fusion of three member Models and
one synthesizer, and immediate cache-hit responses. Target 700 or more model calls.

Assert with `_PipelinedPublisher`:

- `lifecycle.run` completes. It does not raise `BridgeOverflowError`.
- The frame order is `Started`, then the span and cost frames, then
  `CostUsage(scope="subtree")`, then `Result`, then `Terminated(succeeded)`.
- Every span frame is present. Count the spans against the node count.

Assert with a fake whose `publish` never returns:

- The run fails.
- The buffer length stays at or below the hard cap.

Do **not** assert that `_SerialPublisher` still overflows. Such a test fixes unwanted
behavior in place.

## Gates

Run both stacks. The changed paths trigger both CI lanes.

```sh
# packages/url4
cd packages/url4
uv run ruff check && uv run ruff format --check && uv run pyright
uv run pytest --cov=url4 --cov-fail-under=95 -q

# apps/screamingface-engine
cd apps/screamingface-engine
uv run ruff check && uv run ruff format --check && uv run pyright
uv run pytest -q
```

Also run the layering check. Step 3 touches `screamingface_engine.runner`, which must not
import `screamingface_engine.metrics`.

## Risks

| Risk | Control |
|---|---|
| The `url4` coverage gate is 95 percent. The new default `flush` body needs a caller. | Step 1 adds a direct test of the default body. |
| A new `flush` in `_terminate` could change the `stopped` outcome. | Step 2 tests the cancellation arm. |
| The adapter tests have no broker. | Replace `_jetstream` with a fake. This matches the current test design, which asserts only port conformance against a real address. |
| `nats-py` behavior could change. | The version is pinned at 2.15.0 in `uv.lock`. The plan cites the verified call sites. |

## Definition of done

**Not met, and correctly so.** Steps 1 to 4 are delivered with both gate sets green. Step 5
stopped the unit: it showed that acceptance criteria 1, 2, 3 and 5 of OME-906 cannot be met
by this design, because the design targets the wrong mechanism.

Delivered here: the two-phase publish contract (a 50x wall-clock gain at a 10 ms round trip)
and the bridge high-water mark (acceptance criterion 6). Everything else stays open.

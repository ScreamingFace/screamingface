"""A local run's span-sink close has an owner that cancellation cannot skip (OME-1747 review).

`relay.shutdown` used to run only inside the run's task, behind `await asyncio.to_thread(...)`.
`stop()` / `aclose()` cancel that task, so:

* a close still QUEUED on a busy default executor was cancelled with it and never ran at all —
  queued spans dropped, the exporter left open (HupBaHa's one-worker-executor repro:
  `close_calls == 0` even after `aclose()` and freeing the worker);
* a close already RUNNING was abandoned, and `aclose()` returned before it finished.

INVARIANT pinned here: every built sink is closed exactly once, whatever cancels the run, and
`aclose()` returns only after every close has finished.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
import pytest_asyncio

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.tracing.span_tree import Span
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import ResultData, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

pytestmark = pytest.mark.asyncio

TOPIC = "t-local-sink-cleanup"
ENDPOINT_ENV = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"}
# Bounds every wait so a regression fails the test instead of hanging the suite.
BOUND_S = 10


class _OkExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        yield Completed(
            result=ResultData(body="ok"),
            subtree_cost=CostUsageData(
                scope="self",
                provider="test",
                model="test-model",
                pricing_version="v0",
                usage=TokenUsage(input_tokens=0, output_tokens=0),
                cost=CostBreakdown(total_usd=Decimal("0")),
            ),
        )


class _CountingSink:
    """The `SpanSink` port. `close` can be held open to model a slow collector."""

    def __init__(self, *, hold: bool = False) -> None:
        self.close_calls = 0
        self.closing = threading.Event()
        self.release = threading.Event()
        if not hold:
            self.release.set()

    def emit(self, span: Span) -> None:
        pass

    def close(self) -> None:
        self.closing.set()
        self.release.wait(timeout=BOUND_S)
        self.close_calls += 1


@pytest_asyncio.fixture
async def busy_default_executor() -> AsyncIterator[threading.Event]:
    """A ONE-worker default executor whose only worker is occupied until the event is set.

    This is the reviewer's repro: concurrent local runs share the default executor, so a run's
    `to_thread(relay.shutdown)` can sit queued behind other work.
    """
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(pool)
    gate = threading.Event()
    loop.run_in_executor(None, gate.wait, BOUND_S)
    try:
        yield gate
    finally:
        gate.set()
        pool.shutdown(wait=True)


def _runner(stream: InMemoryEventStream, sink: _CountingSink) -> InProcessJobRunner:
    def loader(_env: Mapping[str, str]) -> _CountingSink:
        return sink

    return InProcessJobRunner(
        stream, lambda _env: _OkExecutor(), base_env=ENDPOINT_ENV, span_sink=loader
    )


async def _terminated(stream: InMemoryEventStream) -> TerminatedEvent:
    async with asyncio.timeout(BOUND_S):
        async for event in stream.subscribe(TOPIC, from_sequence=None):
            if isinstance(event, TerminatedEvent):
                return event
    raise AssertionError("stream ended without a terminal frame")


async def _settle() -> None:
    """Give the run's task the loop turns it needs to reach (and queue) its sink close."""
    await asyncio.sleep(0.05)


async def test_aclose_waits_for_a_close_queued_behind_a_busy_executor(
    busy_default_executor: threading.Event,
) -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink()
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    assert (await _terminated(stream)).data.status == "succeeded"
    await _settle()
    assert sink.close_calls == 0  # queued behind the occupied worker

    closing = asyncio.create_task(runner.aclose())
    await _settle()
    # INVARIANT: aclose() cannot return while the sink's close is still owed.
    assert not closing.done()

    busy_default_executor.set()
    await asyncio.wait_for(closing, BOUND_S)

    assert sink.close_calls == 1
    assert runner.active_count() == 0
    assert await runner.status(TOPIC) == "succeeded"


async def test_stop_does_not_cancel_a_close_queued_behind_a_busy_executor(
    busy_default_executor: threading.Event,
) -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink()
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)
    await _settle()
    await runner.stop(TOPIC)
    await _settle()
    assert sink.close_calls == 0

    busy_default_executor.set()
    await asyncio.wait_for(runner.aclose(), BOUND_S)

    # Exactly once: the stop neither skipped the close nor caused a second one.
    assert sink.close_calls == 1
    assert await runner.status(TOPIC) == "succeeded"


@pytest.mark.parametrize("cancel", ["stop", "aclose"])
async def test_aclose_waits_for_a_close_that_is_already_running(cancel: str) -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink(hold=True)
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)
    async with asyncio.timeout(BOUND_S):
        while not sink.closing.is_set():
            await asyncio.sleep(0.01)

    if cancel == "stop":
        await runner.stop(TOPIC)
    closing = asyncio.create_task(runner.aclose())
    await _settle()
    assert not closing.done()
    assert sink.close_calls == 0

    sink.release.set()
    await asyncio.wait_for(closing, BOUND_S)

    assert sink.close_calls == 1
    assert await runner.status(TOPIC) == "succeeded"


# --- OME-1747 review round 3: a cancelled `aclose()` must not reach the runner-owned close ---
#
# `aclose()` used to gather the close tasks themselves. Cancelling `aclose()` cancelled them
# (despite `return_exceptions=True`), the done callback dropped them from the runner, and a
# queued `relay.shutdown` never ran; a repeated or concurrent `aclose()` then had nothing left
# to wait for. INVARIANT pinned here: caller cancellation stops only that caller's wait.


async def _cancelled(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _until_closed(sink: _CountingSink) -> None:
    async with asyncio.timeout(BOUND_S):
        while sink.close_calls == 0:
            await asyncio.sleep(0.01)


async def _until_closing(sink: _CountingSink) -> None:
    async with asyncio.timeout(BOUND_S):
        while not sink.closing.is_set():
            await asyncio.sleep(0.01)


async def test_cancelled_aclose_still_lets_a_queued_close_run_exactly_once(
    busy_default_executor: threading.Event,
) -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink()
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)
    await _settle()
    closing = asyncio.create_task(runner.aclose())
    await _settle()
    await _cancelled(closing)
    assert sink.close_calls == 0  # still queued behind the occupied worker

    busy_default_executor.set()
    # No further aclose(): the runner-owned close runs on its own once a worker frees.
    await _until_closed(sink)

    await asyncio.wait_for(runner.aclose(), BOUND_S)
    assert sink.close_calls == 1


async def test_cancelled_aclose_leaves_a_running_close_owed_to_the_next_aclose() -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink(hold=True)
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)
    await _until_closing(sink)
    closing = asyncio.create_task(runner.aclose())
    await _settle()
    await _cancelled(closing)

    again = asyncio.create_task(runner.aclose())
    await _settle()
    # INVARIANT: the running close is still tracked, so the next aclose() waits for it.
    assert not again.done()
    assert sink.close_calls == 0

    sink.release.set()
    await asyncio.wait_for(again, BOUND_S)
    assert sink.close_calls == 1


async def test_cancelling_one_of_two_concurrent_acloses_does_not_release_the_other(
    busy_default_executor: threading.Event,
) -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink()
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)
    await _settle()
    first = asyncio.create_task(runner.aclose())
    second = asyncio.create_task(runner.aclose())
    await _settle()
    await _cancelled(first)
    await _settle()
    assert not second.done()
    assert sink.close_calls == 0

    busy_default_executor.set()
    await asyncio.wait_for(second, BOUND_S)
    assert sink.close_calls == 1


async def test_repeated_aclose_after_a_cancelled_one_waits_for_the_queued_close(
    busy_default_executor: threading.Event,
) -> None:
    stream = InMemoryEventStream()
    sink = _CountingSink()
    runner = _runner(stream, sink)

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)
    await _settle()
    closing = asyncio.create_task(runner.aclose())
    await _settle()
    await _cancelled(closing)

    again = asyncio.create_task(runner.aclose())
    await _settle()
    assert not again.done()
    assert sink.close_calls == 0

    busy_default_executor.set()
    await asyncio.wait_for(again, BOUND_S)
    assert sink.close_calls == 1

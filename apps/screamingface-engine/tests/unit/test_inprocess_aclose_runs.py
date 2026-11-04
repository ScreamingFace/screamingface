"""A cancelled `aclose()` never cancels a local run a second time (OME-1747 review, round 3).

`aclose()` used to gather the in-flight run tasks directly. Cancelling `aclose()` (or one of two
concurrent calls) cancelled each run AGAIN while it was shutting down — i.e. while
`lifecycle.run` was flushing its `Terminated(stopped)` frame — so the frame's flush was cut off
and the run ended before its outcome was durable.

INVARIANT pinned here: `aclose()` stops each run exactly once, then waits on shielded views of
the run tasks. A caller's cancellation abandons only that caller's wait; a repeated or concurrent
`aclose()` waits for the same completion.

These run with NO OTLP endpoint, so no span sink exists — the run's own shutdown is under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import ResultData, TerminatedEvent
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

pytestmark = pytest.mark.asyncio

TOPIC = "t-local-aclose-runs"
# Below lifecycle's 10 s terminal-flush bound, so a held flush is released, never timed out.
BOUND_S = 5


class _BlockingExecutor(Executor):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        self.started.set()
        await asyncio.Event().wait()
        yield Completed(  # pragma: no cover - never reached; the run is stopped
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


class _HeldFlushStream(InMemoryEventStream):
    """Every flush waits for `release` — a broker that has not acked the stop frame yet.

    The blocked executor publishes nothing that is flushed, so the only flush is the one
    `lifecycle.run` makes for its `Terminated(stopped)` frame.
    """

    def __init__(self) -> None:
        super().__init__()
        self.flushing = asyncio.Event()
        self.release = asyncio.Event()
        self.flush_calls = 0
        self.flushes_completed = 0
        self.flushes_cancelled = 0

    async def flush(self) -> None:
        self.flush_calls += 1
        self.flushing.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.flushes_cancelled += 1
            raise
        self.flushes_completed += 1


async def _shutting_down(
    stream: _HeldFlushStream,
) -> tuple[InProcessJobRunner, asyncio.Task[None]]:
    """Schedule a run, start `aclose()`, and return once the run is flushing its stop frame."""
    executor = _BlockingExecutor()
    runner = InProcessJobRunner(stream, lambda _env: executor)
    await runner.schedule(TOPIC, "x", 30)
    async with asyncio.timeout(BOUND_S):
        await executor.started.wait()
    closing = asyncio.create_task(runner.aclose())
    async with asyncio.timeout(BOUND_S):
        await stream.flushing.wait()
    return runner, closing


async def _cancelled(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _settle() -> None:
    await asyncio.sleep(0.05)


async def _terminal_frames(stream: InMemoryEventStream) -> list[TerminatedEvent]:
    frames: list[TerminatedEvent] = []
    async with asyncio.timeout(BOUND_S):
        async for event in stream.subscribe(TOPIC, from_sequence=None):
            if isinstance(event, TerminatedEvent):
                frames.append(event)
                break
    return frames


async def test_cancelled_aclose_leaves_a_shutting_down_run_to_finish_and_the_next_waits() -> None:
    stream = _HeldFlushStream()
    runner, closing = await _shutting_down(stream)

    await _cancelled(closing)
    await _settle()
    # The caller's cancel stopped only its own wait: the run is still flushing its stop frame.
    assert stream.flushes_cancelled == 0
    assert await runner.status(TOPIC) == "running"

    again = asyncio.create_task(runner.aclose())
    await _settle()
    assert not again.done()

    stream.release.set()
    await asyncio.wait_for(again, BOUND_S)

    assert stream.flush_calls == 1
    assert stream.flushes_completed == 1
    assert stream.flushes_cancelled == 0
    assert await runner.status(TOPIC) == "stopped"
    assert [f.data.status for f in await _terminal_frames(stream)] == ["stopped"]


async def test_cancelling_one_of_two_concurrent_acloses_stops_the_run_once() -> None:
    stream = _HeldFlushStream()
    runner, first = await _shutting_down(stream)
    second = asyncio.create_task(runner.aclose())
    await _settle()

    await _cancelled(first)
    await _settle()
    assert stream.flushes_cancelled == 0
    assert not second.done()

    stream.release.set()
    await asyncio.wait_for(second, BOUND_S)

    # Finished once: one stop frame, flushed once, never cut off by a second cancel.
    assert stream.flush_calls == 1
    assert stream.flushes_completed == 1
    assert stream.flushes_cancelled == 0
    assert await runner.status(TOPIC) == "stopped"
    assert runner.active_count() == 0

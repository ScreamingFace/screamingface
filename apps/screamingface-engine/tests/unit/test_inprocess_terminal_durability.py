"""`status()` of a local run never claims an outcome that is not durable (OME-1747 review).

`lifecycle.run` RAISES when the terminal frame's flush fails (or is cancelled): the frame may
not be durable, and only a non-zero exit triggers the backstop. The runner used to record the
`Terminated` frame's verdict in a `finally`, so `status()` reported `succeeded` for a task that
had raised. The verdict is now recorded only when `lifecycle.run` returns normally.

These run with NO OTLP endpoint (the default), so no span sink exists: the verdict logic must be
right on the path every local run takes, not only when export is configured.
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

TOPIC = "t-local-durability"
BOUND_S = 10


class _Executor(Executor):
    def __init__(self, *, block: bool = False, boom: Exception | None = None) -> None:
        self._block = block
        self._boom = boom

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        if self._boom is not None:
            raise self._boom
        if self._block:
            await asyncio.Event().wait()
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


class _TerminalFlushStream(InMemoryEventStream):
    """Flush #1 is the pre-outcome barrier; flush #2 is the TERMINAL frame's flush."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self._fail = fail
        self.flushes = 0
        self.terminal_flushing = asyncio.Event()

    async def flush(self) -> None:
        self.flushes += 1
        if self.flushes < 2:
            return
        self.terminal_flushing.set()
        if self._fail:
            raise RuntimeError("terminal frame not acknowledged")
        await asyncio.Event().wait()  # held: a broker that has not acked yet


def _runner(stream: InMemoryEventStream, executor: Executor) -> InProcessJobRunner:
    # No base_env -> no OTLP endpoint -> the production loader builds no sink.
    return InProcessJobRunner(stream, lambda _env: executor)


async def _terminated(stream: InMemoryEventStream) -> TerminatedEvent:
    async with asyncio.timeout(BOUND_S):
        async for event in stream.subscribe(TOPIC, from_sequence=None):
            if isinstance(event, TerminatedEvent):
                return event
    raise AssertionError("stream ended without a terminal frame")


async def _finished(runner: InProcessJobRunner) -> str:
    async with asyncio.timeout(BOUND_S):
        while (status := await runner.status(TOPIC)) == "running":
            await asyncio.sleep(0.01)
    return status


async def test_a_failed_terminal_flush_is_a_failed_status_not_the_frames_verdict() -> None:
    stream = _TerminalFlushStream(fail=True)
    runner = _runner(stream, _Executor())

    await runner.schedule(TOPIC, "x", 30)
    # The frame itself says succeeded — that is exactly the claim that is not durable.
    assert (await _terminated(stream)).data.status == "succeeded"

    assert await _finished(runner) == "failed"


async def test_a_cancel_during_the_terminal_flush_is_stopped_not_the_frames_verdict() -> None:
    """Same rule, cancellation arm: `lifecycle.run` re-raises the cancel because the terminal
    frame was published but never confirmed durable, so the task's own `stopped` stands."""
    stream = _TerminalFlushStream()
    runner = _runner(stream, _Executor())

    await runner.schedule(TOPIC, "x", 30)
    async with asyncio.timeout(BOUND_S):
        await stream.terminal_flushing.wait()
    await runner.stop(TOPIC)

    assert await _finished(runner) == "stopped"


async def test_an_exploding_executor_reports_failed() -> None:
    stream = InMemoryEventStream()
    runner = _runner(stream, _Executor(boom=RuntimeError("nope")))

    await runner.schedule(TOPIC, "x", 30)
    assert (await _terminated(stream)).data.status == "failed"

    # The task itself returned normally (lifecycle caught the failure); the frame says failed.
    assert await _finished(runner) == "failed"


async def test_a_run_past_its_deadline_reports_timed_out() -> None:
    stream = InMemoryEventStream()
    runner = _runner(stream, _Executor(block=True))

    # `deadline_s` is an int on the port; 1 s is the smallest real bound.
    await runner.schedule(TOPIC, "x", 1)
    assert (await _terminated(stream)).data.status == "timed_out"

    assert await _finished(runner) == "timed_out"


async def test_a_succeeded_run_reports_succeeded() -> None:
    stream = InMemoryEventStream()
    runner = _runner(stream, _Executor())

    await runner.schedule(TOPIC, "x", 30)
    await _terminated(stream)

    assert await _finished(runner) == "succeeded"

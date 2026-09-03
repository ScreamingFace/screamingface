"""The two-phase publish contract: ordered hand-off, then an explicit durability barrier.

FEATURE: a cached DRACO burst must not overflow the Runner event bridge (OME-906). The
Runner used to await one broker acknowledgement per frame, which capped the drain at one
round trip per frame while the engine produced events at CPU speed. `EventPublisher` now
separates "the transport took the frame, in order" from "the broker made it durable", and
the lifecycle waits for durability only where it decides the outcome of the run.

These tests pin the CONTRACT, not one adapter: `flush` must default to doing nothing, the
lifecycle must flush before it declares an outcome, and a deferred failure surfacing at the
flush must fail the run the same way an immediate publish failure always has.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from _fakes import MockExecutor

from url4.streaming.interfaces import EventPublisher, ExecStep, Executor, TraceContext
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import OutboundFrame, ResultEvent, TerminatedEvent

TOPIC = "durability-topic"


class _TracingPublisher(EventPublisher):
    """Records `publish` and `flush` as one ordered trace, so a test can assert the barrier
    lands between the frames rather than merely that it ran."""

    def __init__(self, *, flush_raises: BaseException | None = None) -> None:
        self.trace: list[str] = []
        self.published: list[OutboundFrame] = []
        self._flush_raises = flush_raises
        self.flushes = 0

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.published.append(event)
        self.trace.append(f"publish:{type(event).__name__}")

    async def flush(self) -> None:
        self.flushes += 1
        self.trace.append("flush")
        # Only the FIRST flush raises: an adapter reports a deferred failure once and then
        # discards it, so the termination path can still get its own frame out.
        if self._flush_raises is not None and self.flushes == 1:
            raise self._flush_raises


class _CancellingExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        raise asyncio.CancelledError
        yield  # pragma: no cover - unreachable, makes this an async generator


def _terminal(pub: _TracingPublisher) -> TerminatedEvent:
    return next(f for f in pub.published if isinstance(f, TerminatedEvent))


def test_the_port_flush_defaults_to_doing_nothing() -> None:
    """INVARIANT: `flush` is NOT abstract. Every existing adapter and test fake is durable
    when `publish` returns, so making it abstract would break all of them for nothing."""

    class _Minimal(EventPublisher):
        async def ensure_stream(self, topic: str) -> None:
            return None

        async def publish(self, topic: str, event: OutboundFrame) -> None:
            return None

    assert asyncio.run(_Minimal().flush()) is None


@pytest.mark.asyncio
async def test_the_run_flushes_after_the_result_and_before_the_terminal_frame() -> None:
    # INVARIANT: the barrier sits where the OUTCOME is decided. A flush after the terminal
    # frame instead of before it would let a run publish "succeeded" over a stream whose
    # span frames were never acknowledged.
    pub = _TracingPublisher()

    await publish_run(pub, MockExecutor(), TOPIC, "'hi' -> claude")

    assert "flush" in pub.trace
    result_at = pub.trace.index("publish:ResultEvent")
    terminal_at = pub.trace.index("publish:TerminatedEvent")
    first_flush_at = pub.trace.index("flush")
    assert result_at < first_flush_at < terminal_at


@pytest.mark.asyncio
async def test_the_terminal_frame_is_flushed_before_the_run_returns() -> None:
    pub = _TracingPublisher()

    await publish_run(pub, MockExecutor(), TOPIC, "'hi' -> claude")

    assert pub.trace[-1] == "flush", (
        f"the terminal frame must be durable before `run` returns, trace ended {pub.trace[-3:]}"
    )


@pytest.mark.asyncio
async def test_a_deferred_failure_surfacing_at_the_flush_fails_the_run() -> None:
    # STORY: as an operator, a run whose span frames never reached the broker must report
    # `failed`, not `succeeded` over a stream with a hole in it.
    pub = _TracingPublisher(flush_raises=RuntimeError("ack rejected"))

    await publish_run(pub, MockExecutor(), TOPIC, "'hi' -> claude")

    terminal = _terminal(pub)
    assert terminal.data.status == "failed"
    assert terminal.data.error is not None
    assert "ack rejected" in terminal.data.error.message


@pytest.mark.asyncio
async def test_a_failed_flush_still_lets_the_terminal_frame_out() -> None:
    """INVARIANT: every exit path from `run` publishes a terminal frame. A deferred failure
    reported at the first flush must not also take out the frame that reports it."""
    pub = _TracingPublisher(flush_raises=RuntimeError("ack rejected"))

    await publish_run(pub, MockExecutor(), TOPIC, "'hi' -> claude")

    assert isinstance(pub.published[-1], TerminatedEvent)
    assert not any(isinstance(f, ResultEvent) and f is pub.published[-1] for f in pub.published)


@pytest.mark.asyncio
async def test_a_cancelled_run_still_terminates_as_stopped() -> None:
    # WHY here: `_terminate` gained a flush, and the cancellation arm suppresses failures
    # from it. This pins that the added barrier did not turn a `stopped` run into a `failed`
    # one, which is the one regression the new call could plausibly cause.
    pub = _TracingPublisher()

    with pytest.raises(asyncio.CancelledError):
        await publish_run(pub, _CancellingExecutor(), TOPIC, "'hi' -> claude")

    assert _terminal(pub).data.status == "stopped"

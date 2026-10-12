"""Fault schedules for :func:`url4.streaming.lifecycle.run` (audit 2026-10-09: D1–D3, D5, D9).

Each test drives the REAL ``run`` against a scripted publisher and maps to one counterexample of
the lifecycle model (``docs/spec/2026-10-09-url4-audit/evidence/F2-streaming/repro_lifecycle.py``,
scenarios R1–R6). The invariants under test:

- at most one terminal frame, and it is the last frame (``at_most_one_terminal``,
  ``terminal_is_last``);
- the wire ``sequence`` is gap-free even when a publish fails before it writes (``seq_gap_free``);
- a failure of the terminal frame itself (publish, flush, or the flush bound) raises out of ``run``
  on every outcome, so the worker backstop sees a non-zero exit; a stop stays a cancellation;
- the executor's generator is closed by ``run`` itself, in ``run``'s task, after the terminal
  frame and outside the deadline.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal

import pytest

from url4.streaming import lifecycle
from url4.streaming.interfaces import Completed, EventPublisher, ExecStep, Executor, TraceContext
from url4.streaming.lifecycle import _Sequencer, run
from url4.streaming.protocol import (
    CostBreakdown,
    CostUsageData,
    LogData,
    OutboundFrame,
    ResultData,
    TerminatedEvent,
    TokenUsage,
)

TOPIC = "lifecycle-faults"


def _completed() -> Completed:
    cost = CostUsageData(
        scope="subtree",
        provider="t",
        model="m",
        pricing_version="2026-07-01",
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost=CostBreakdown(total_usd=Decimal("0.001")),
    )
    return Completed(result=ResultData(body="ok", media_type="text/plain"), subtree_cost=cost)


class _Steps(Executor):
    """Yields ``telemetry`` log lines, then ``Completed``. ``hook(i)`` runs before line ``i``."""

    def __init__(
        self, telemetry: int = 0, hook: Callable[[int], Awaitable[None]] | None = None
    ) -> None:
        self.telemetry, self.hook = telemetry, hook

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        for i in range(self.telemetry):
            if self.hook is not None:
                await self.hook(i)
            yield LogData.at("INFO", f"tel-{i}")
        yield _completed()


class _Raising(Executor):
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        raise self.exc
        yield _completed()  # unreachable: makes this an async generator


class _Recording(EventPublisher):
    """Durable on return; counts flushes so a test can fail one of them."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []
        self.flushes = 0

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.frames.append(event)


def _terminals(frames: list[OutboundFrame]) -> list[str]:
    return [f.data.status for f in frames if isinstance(f, TerminatedEvent)]


def _assert_well_formed(frames: list[OutboundFrame]) -> None:
    """One terminal frame, last, over a gap-free 1-based sequence."""
    assert len(_terminals(frames)) == 1, [f.type for f in frames]
    assert isinstance(frames[-1], TerminatedEvent)
    assert [int(str(f.sequence)) for f in frames] == list(range(1, len(frames) + 1))


@pytest.mark.asyncio
async def test_r1_terminal_flush_failure_does_not_publish_a_second_terminal() -> None:
    class P(_Recording):
        async def flush(self) -> None:
            self.flushes += 1
            if self.flushes == 2:  # 1 = the execution barrier, 2 = the terminal flush
                raise RuntimeError("ack timeout on the terminal frame")

    pub = P()
    # The success outcome was published but may not be durable: the caller must hear about it.
    with pytest.raises(RuntimeError, match="terminal frame"):
        await run(pub, _Steps(), TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["succeeded"]


@pytest.mark.asyncio
async def test_r2_cancel_during_terminal_flush_does_not_publish_a_second_terminal() -> None:
    gate = asyncio.Event()

    class P(_Recording):
        async def flush(self) -> None:
            self.flushes += 1
            if self.flushes == 2:
                gate.set()
                await asyncio.Event().wait()  # the broker is slow to ack the terminal frame

    pub = P()
    task = asyncio.ensure_future(run(pub, _Steps(), TOPIC, "x", deadline_s=5))
    await gate.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["succeeded"]


class _JetStreamLike(EventPublisher):
    """The JetStream deferral semantics, reduced and CONTRACT-COMPLIANT (``EventPublisher``):
    ``publish`` reaps settled acks and raises the first recorded failure BEFORE it writes;
    ``flush`` waits for every ack, reaps and raises the first failure. Raising a failure
    DISCARDS the remaining deferred state, so a failure reported once is never raised again and
    a later flush raises only about frames published after it."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []
        self.acks: dict[asyncio.Future[None], OutboundFrame] = {}
        self.deferred: BaseException | None = None
        self.on_flush: Callable[[], None] | None = None

    async def ensure_stream(self, topic: str) -> None:
        return None

    def _reap(self) -> None:
        for ack in tuple(self.acks):
            if ack.done():
                del self.acks[ack]
                exc = ack.exception()
                if exc is not None and self.deferred is None:
                    self.deferred = exc

    def _raise_deferred(self) -> None:
        exc, self.deferred = self.deferred, None
        if exc is not None:
            self.acks.clear()  # discard the rest of the deferred state with it
            raise RuntimeError(f"deferred publish failure: {exc}")

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self._reap()
        self._raise_deferred()
        self.frames.append(event)
        self.acks[asyncio.get_running_loop().create_future()] = event

    async def flush(self) -> None:
        if self.on_flush is not None:
            self.on_flush()
        if self.acks:
            await asyncio.wait(tuple(self.acks))
        self._reap()
        self._raise_deferred()


def _r3_publisher(*, reject_terminal: bool) -> tuple[_JetStreamLike, _Steps]:
    """tel-0's ack is rejected and surfaces on the next publish, which fails the run while
    tel-1's ack is still in flight. At the failed arm's flush every pending ack settles: the
    terminal frame's is rejected only when ``reject_terminal``."""
    pub = _JetStreamLike()

    async def hook(i: int) -> None:
        if i == 2:  # acks so far: [Started, tel-0, tel-1]; tel-0's is rejected now
            list(pub.acks)[1].set_exception(RuntimeError("rejected tel-0"))

    def settle_at_flush() -> None:
        for ack, frame in list(pub.acks.items()):
            if ack.done():
                continue
            if isinstance(frame, TerminatedEvent) and reject_terminal:
                ack.set_exception(RuntimeError("rejected terminal"))
            elif frame.type.endswith("log"):
                ack.set_exception(RuntimeError("rejected tel-1"))
            else:
                ack.set_result(None)

    pub.on_flush = settle_at_flush
    return pub, _Steps(telemetry=3, hook=hook)


@pytest.mark.asyncio
async def test_r3_failure_already_reported_does_not_raise_again_at_the_terminal_flush() -> None:
    pub, steps = _r3_publisher(reject_terminal=False)

    await run(pub, steps, TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["failed"]


@pytest.mark.asyncio
async def test_r3_new_rejection_of_the_terminal_frame_raises_out_of_the_failed_arm() -> None:
    pub, steps = _r3_publisher(reject_terminal=True)

    with pytest.raises(RuntimeError, match="rejected terminal"):
        await run(pub, steps, TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["failed"]


@pytest.mark.asyncio
async def test_r4_publish_refused_before_write_leaves_no_sequence_hole() -> None:
    class P(_Recording):
        async def publish(self, topic: str, event: OutboundFrame) -> None:
            if event.type.endswith("result"):
                raise RuntimeError("connection reset before write")
            self.frames.append(event)

    pub = P()
    await run(pub, _Steps(telemetry=1), TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["failed"]


@pytest.mark.asyncio
async def test_r5_deadline_converted_by_the_adapter_still_ends_timed_out() -> None:
    class TooManyStalledMsgsError(Exception):
        pass

    class P(_Recording):
        async def publish(self, topic: str, event: OutboundFrame) -> None:
            if event.type.endswith("log"):
                try:
                    await asyncio.Event().wait()  # window full, broker stalled
                except asyncio.CancelledError:
                    raise TooManyStalledMsgsError from None  # what nats-py does
            self.frames.append(event)

    pub = P()
    await run(pub, _Steps(telemetry=1), TOPIC, "x", deadline_s=0.05)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["timed_out"]


@pytest.mark.asyncio
async def test_r6_run_closes_the_executor_generator_in_its_own_task() -> None:
    closed_in: list[asyncio.Task[object] | None] = []

    class E(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            try:
                yield _completed()
            finally:
                closed_in.append(asyncio.current_task())

    task = asyncio.ensure_future(run(_Recording(), E(), TOPIC, "x", deadline_s=5))
    await task

    assert closed_in == [task]


@pytest.mark.asyncio
async def test_own_timeout_error_with_the_deadline_not_expired_ends_failed() -> None:
    pub = _Recording()

    await run(pub, _Raising(TimeoutError("upstream read timed out")), TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["failed"]


class _HangingTerminalFlush(_Recording):
    """The execution barrier (if any) flushes; the terminal flush never completes."""

    def __init__(self, *, barrier: bool) -> None:
        super().__init__()
        self.hang_at = 2 if barrier else 1

    async def flush(self) -> None:
        self.flushes += 1
        if self.flushes == self.hang_at:
            await asyncio.Event().wait()  # nats-py ack futures have no timeout of their own


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executor", "barrier", "status"),
    [(_Steps(), True, "succeeded"), (_Raising(RuntimeError("boom")), False, "failed")],
)
async def test_terminal_flush_is_bounded_and_its_expiry_raises_on_every_outcome(
    monkeypatch: pytest.MonkeyPatch, executor: Executor, barrier: bool, status: str
) -> None:
    monkeypatch.setattr(lifecycle, "_TERMINAL_FLUSH_TIMEOUT_S", 0.05)
    pub = _HangingTerminalFlush(barrier=barrier)

    async with asyncio.timeout(5):
        with pytest.raises(TimeoutError, match="terminal flush exceeded"):
            await run(pub, executor, TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == [status]


@pytest.mark.asyncio
async def test_stopped_arm_terminal_failure_stays_a_cancellation() -> None:
    class P(_Recording):
        async def flush(self) -> None:
            raise RuntimeError("terminal ack rejected")

    pub = P()
    with pytest.raises(asyncio.CancelledError) as stopped:
        await run(pub, _Raising(asyncio.CancelledError()), TOPIC, "x", deadline_s=5)

    assert isinstance(stopped.value.__cause__, RuntimeError)
    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["stopped"]


@pytest.mark.asyncio
async def test_slow_teardown_runs_after_the_terminal_frame_and_outside_the_deadline() -> None:
    pub = _Recording()
    seen_at_teardown: list[list[str]] = []

    class E(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            try:
                yield _completed()
            finally:
                seen_at_teardown.append(_terminals(pub.frames))
                await asyncio.sleep(0.2)  # longer than the run's whole deadline

    await run(pub, E(), TOPIC, "x", deadline_s=0.1)

    assert seen_at_teardown == [["succeeded"]]
    _assert_well_formed(pub.frames)


@pytest.mark.asyncio
async def test_teardown_failure_propagates_after_the_terminal_frame_stands() -> None:
    pub = _Recording()

    class E(Executor):
        async def execute(
            self, url4: str, *, trace: TraceContext | None = None
        ) -> AsyncIterator[ExecStep]:
            try:
                yield _completed()
            finally:
                raise RuntimeError("world close failed")

    with pytest.raises(RuntimeError, match="world close failed"):
        await run(pub, E(), TOPIC, "x", deadline_s=5)

    _assert_well_formed(pub.frames)
    assert _terminals(pub.frames) == ["succeeded"]


def test_sequencer_commit_refuses_an_envelope_it_did_not_issue_next() -> None:
    seq = _Sequencer(TOPIC, "root")
    first = seq.peek("00-trace")
    seq.commit(first)

    with pytest.raises(RuntimeError, match="sequence"):
        seq.commit(first)

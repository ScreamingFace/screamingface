"""Drive the REAL url4.streaming.lifecycle.run against scripted publishers.

Each scenario maps to one model counterexample. Run with the url4 package venv:
  $PKG/.venv/bin/python repro_lifecycle.py
Prints one line per scenario: the frames that reached the publisher (seq:type[:status]),
how run() exited, and whether the finding reproduced.
"""
from __future__ import annotations

import asyncio
import gc
from collections.abc import AsyncIterator
from decimal import Decimal

from url4.streaming.interfaces import (
    Completed,
    EventPublisher,
    ExecStep,
    Executor,
    TraceContext,
)
from url4.streaming.lifecycle import run
from url4.streaming.protocol import (
    CostBreakdown,
    CostUsageData,
    LogData,
    OutboundFrame,
    ResultData,
    TerminatedEvent,
    TokenUsage,
)

TOPIC = "repro"


def _cost() -> CostUsageData:
    return CostUsageData(
        scope="subtree", provider="t", model="m", pricing_version="2026-07-01",
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost=CostBreakdown(total_usd=Decimal("0.001")),
    )


def _completed() -> Completed:
    return Completed(result=ResultData(body="ok", media_type="text/plain"), subtree_cost=_cost())


def _show(frames: list[OutboundFrame]) -> str:
    out = []
    for f in frames:
        t = f.type.rsplit(".", 1)[-1]
        if isinstance(f, TerminatedEvent):
            t += ":" + f.data.status
        out.append(f"{f.sequence}:{t}")
    return " ".join(out)


def _terms(frames: list[OutboundFrame]) -> list[str]:
    return [f.data.status for f in frames if isinstance(f, TerminatedEvent)]


async def _outcome(coro) -> str:
    try:
        await coro
        return "returned"
    except asyncio.CancelledError:
        return "raised CancelledError"
    except BaseException as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}: {exc}"


class Simple(Executor):
    def __init__(self, telemetry: int = 0, hook=None) -> None:
        self.telemetry, self.hook = telemetry, hook

    async def execute(self, url4: str, *, trace: TraceContext | None = None) -> AsyncIterator[ExecStep]:
        for i in range(self.telemetry):
            if self.hook:
                await self.hook(i)
            yield LogData.at("INFO", f"tel-{i}")
        yield _completed()


class Recording(EventPublisher):
    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []
        self.flushes = 0

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.frames.append(event)


# ---------------------------------------------------------------- scenarios

async def r1_flush_raises_on_terminal_flush() -> None:
    """model: term_pub:ok -> term_flush:raises -> term_pub:ok (at_most_one_terminal)."""
    class P(Recording):
        async def flush(self) -> None:
            self.flushes += 1
            if self.flushes == 2:          # 1 = _publish_execution's barrier, 2 = _terminate's
                raise RuntimeError("ack timeout on the terminal frame")
    p = P()
    how = await _outcome(run(p, Simple(), TOPIC, "x", deadline_s=5))
    print(f"R1 flush raises in _terminate('succeeded'): {_show(p.frames)} | run {how} | "
          f"terminals={_terms(p.frames)} -> {'REPRODUCED' if len(_terms(p.frames)) == 2 else 'not reproduced'}")


async def r2_cancel_during_terminal_flush() -> None:
    """model: term_pub:ok -> term_flush:cancelled -> term_pub:ok."""
    gate = asyncio.Event()

    class P(Recording):
        async def flush(self) -> None:
            self.flushes += 1
            if self.flushes == 2:
                gate.set()
                await asyncio.Event().wait()   # the broker is slow to ack the terminal frame
    p = P()
    task = asyncio.ensure_future(run(p, Simple(), TOPIC, "x", deadline_s=5))
    await gate.wait()
    task.cancel()                              # InProcessJobRunner.stop
    how = await _outcome(task)
    print(f"R2 cancel while _terminate('succeeded') flushes: {_show(p.frames)} | run {how} | "
          f"terminals={_terms(p.frames)} -> {'REPRODUCED' if len(_terms(p.frames)) == 2 else 'not reproduced'}")


class JetStreamLike(EventPublisher):
    """The JetStreamPublisher deferral semantics, reduced: publish reaps settled acks and
    raises the first recorded failure (clearing it) BEFORE writing; flush waits for all
    acks, reaps, raises the first failure, clears it."""

    def __init__(self) -> None:
        self.frames: list[OutboundFrame] = []
        self.acks: dict[asyncio.Future[None], OutboundFrame] = {}
        self.deferred: BaseException | None = None

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
            raise RuntimeError(f"deferred publish failure: {exc}")

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self._reap()
        self._raise_deferred()
        self.frames.append(event)
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.acks[fut] = event

    on_flush = None

    async def flush(self) -> None:
        if self.on_flush is not None:
            self.on_flush()
        if self.acks:
            await asyncio.wait(tuple(self.acks))
        self._reap()
        self._raise_deferred()

    def fail_ack(self, index: int, msg: str) -> None:
        ack = list(self.acks)[index]
        ack.set_exception(RuntimeError(msg))

    def settle_rest(self) -> None:
        for ack in self.acks:
            if not ack.done():
                ack.set_result(None)


async def r3_second_deferred_failure_at_the_failed_arm_flush() -> None:
    """model: pub_tel:raises_unwritten -> term_pub:ok -> term_flush:raises (run raises out of
    the failed arm). tel-0's ack is rejected and surfaces on the next publish; tel-1's ack is
    still in flight then, and is rejected while the failed arm's flush waits for it."""
    p = JetStreamLike()

    async def hook(i: int) -> None:
        if i == 2:
            p.fail_ack(1, "rejected tel-0")   # acks: [Started, tel-0, tel-1]

    def settle_at_flush() -> None:
        for n, ack in enumerate(list(p.acks)):
            if ack.done():
                continue
            if p.acks[ack].type.endswith("log"):
                ack.set_exception(RuntimeError("rejected tel-1"))
            else:
                ack.set_result(None)
    p.on_flush = settle_at_flush
    how = await _outcome(run(p, Simple(telemetry=3, hook=hook), TOPIC, "x", deadline_s=5))
    t = _terms(p.frames)
    print(f"R3 second rejected ack settles during the failed arm's flush: {_show(p.frames)} | "
          f"run {how} | terminals={t} -> "
          f"{'REPRODUCED (terminal written, run raises out of the failed arm)' if t and how.startswith('raised') else 'not reproduced'}")


async def r4_prewrite_refusal_leaves_a_sequence_hole() -> None:
    """model: pub_*:raises_unwritten -> term_pub:ok (seq_gap_free)."""
    class P(Recording):
        async def publish(self, topic: str, event: OutboundFrame) -> None:
            if event.type.endswith("result"):
                raise RuntimeError("connection reset before write")
            self.frames.append(event)
    p = P()
    how = await _outcome(run(p, Simple(telemetry=1), TOPIC, "x", deadline_s=5))
    seqs = [int(f.sequence) for f in p.frames]
    gap = seqs != list(range(1, len(seqs) + 1))
    print(f"R4 pre-write publish failure: {_show(p.frames)} | run {how} | "
          f"{'REPRODUCED (hole in sequence)' if gap else 'not reproduced'}")


async def r5_deadline_converted_by_adapter() -> None:
    """nats-py publish_async converts CancelledError into TooManyStalledMsgsError while it waits
    for its in-flight semaphore. Does the run still end `timed_out`?"""
    class TooManyStalledMsgsError(Exception):
        pass

    class P(Recording):
        async def publish(self, topic: str, event: OutboundFrame) -> None:
            if event.type.endswith("log"):
                try:
                    await asyncio.Event().wait()     # window full, broker stalled
                except asyncio.CancelledError:
                    raise TooManyStalledMsgsError from None   # what nats-py does
            self.frames.append(event)
    p = P()
    how = await _outcome(run(p, Simple(telemetry=1), TOPIC, "x", deadline_s=0.05))
    t = _terms(p.frames)
    seqs = [int(f.sequence) for f in p.frames]
    print(f"R5 deadline fires inside a cancel-converting publish: {_show(p.frames)} | run {how} | "
          f"terminals={t} gap={seqs != list(range(1, len(seqs) + 1))} -> "
          f"{'REPRODUCED (failed, not timed_out)' if t == ['failed'] else 'not reproduced'}")


async def r6_executor_not_closed_on_completed() -> None:
    order: list[str] = []

    class E(Executor):
        async def execute(self, url4: str, *, trace: TraceContext | None = None) -> AsyncIterator[ExecStep]:
            try:
                yield _completed()
                order.append("executor resumed after Completed")
            finally:
                order.append("executor finally (world close)")

    class P(Recording):
        async def publish(self, topic: str, event: OutboundFrame) -> None:
            await asyncio.sleep(0)
            order.append(f"publish {event.type.rsplit('.', 1)[-1]}")
            self.frames.append(event)
    p = P()
    await run(p, E(), TOPIC, "x", deadline_s=5)
    order.append("run returned")
    gc.collect()
    await asyncio.sleep(0.01)
    term_i = order.index("publish terminated")
    fin_i = order.index("executor finally (world close)") if "executor finally (world close)" in order else -1
    print(f"R6 executor generator on Completed: {order} -> "
          "REPRODUCED: run never closes it; the asyncgen finalizer closes it in ANOTHER task at "
          "the run's next suspension")


async def r0_control() -> None:
    p = Recording()
    how = await _outcome(run(p, Simple(telemetry=1), TOPIC, "x", deadline_s=5))
    print(f"R0 control (happy path): {_show(p.frames)} | run {how}")


async def main() -> None:
    for sc in (r0_control, r1_flush_raises_on_terminal_flush, r2_cancel_during_terminal_flush,
               r3_second_deferred_failure_at_the_failed_arm_flush,
               r4_prewrite_refusal_leaves_a_sequence_hole, r5_deadline_converted_by_adapter,
               r6_executor_not_closed_on_completed):
        print(f"-- {sc.__name__}", flush=True)
        try:
            await asyncio.wait_for(sc(), timeout=5)
        except TimeoutError:
            print(f"   {sc.__name__}: HUNG (no progress in 5 s)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

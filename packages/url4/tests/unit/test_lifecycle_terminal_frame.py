"""The streaming lifecycle's terminal-frame guarantee: exactly one terminal frame per run.

INVARIANT (F6): every exit path from :func:`url4.streaming.lifecycle.run` — success, error,
cancellation, deadline — publishes exactly ONE terminal frame, so a subscriber never waits
forever and never sees two conflicting outcomes. ``_terminate``'s docstring states this;
these tests pin all four arms.

Also pins the producer-side sequencer invariants (F5b): the wire ``sequence`` counter in
``lifecycle._Sequencer`` and the ``engine_seq`` counter in ``dag._context._ObsState`` are
strictly monotonic and gap-free, and each fails loudly if the increment ever breaks.

Requires the ``[streaming]`` extra (pydantic). The dev group installs it; the import guard
below keeps a base install green if it is ever absent.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Literal, cast

import pytest

pytest.importorskip("pydantic")

from url4.dag._context import _ObsState
from url4.observe import NullObserver
from url4.streaming.interfaces import (
    Completed,
    EventPublisher,
    ExecStep,
    Executor,
    TraceContext,
)
from url4.streaming.lifecycle import _Sequencer
from url4.streaming.lifecycle import run as publish_run
from url4.streaming.protocol import (
    CostBreakdown,
    CostUsageData,
    OutboundFrame,
    ResultData,
    TerminatedEvent,
    TokenUsage,
)

TOPIC = "terminal-frame-topic"
EXPR = "'hi' -> claude"


class _RecordingPublisher(EventPublisher):
    """An in-process publisher, durable on return, that records every frame."""

    def __init__(self) -> None:
        self.published: list[OutboundFrame] = []

    async def ensure_stream(self, topic: str) -> None:
        return None

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        self.published.append(event)

    def terminals(self) -> list[TerminatedEvent]:
        return [frame for frame in self.published if isinstance(frame, TerminatedEvent)]


def _cost(scope: Literal["self", "subtree"]) -> CostUsageData:
    return CostUsageData(
        scope=scope,
        provider="test",
        model="test-model",
        pricing_version="2026-07-01",
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        cost=CostBreakdown(total_usd=Decimal("0.001")),
    )


class _SuccessExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        yield Completed(
            result=ResultData(body="ok", media_type="text/plain"),
            subtree_cost=_cost("subtree"),
        )


class _ErrorExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        raise RuntimeError("boom")
        yield  # unreachable: makes this an async generator


class _CancellingExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        raise asyncio.CancelledError
        yield cast("ExecStep", None)  # unreachable: makes this an async generator


class _HangingExecutor(Executor):
    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        await asyncio.Event().wait()
        yield cast("ExecStep", None)  # unreachable: cancelled by the run's deadline


@pytest.mark.asyncio
async def test_success_exit_emits_exactly_one_terminal_frame() -> None:
    pub = _RecordingPublisher()

    await publish_run(pub, _SuccessExecutor(), TOPIC, EXPR)

    terminals = pub.terminals()
    assert len(terminals) == 1
    assert terminals[0].data.status == "succeeded"
    assert pub.published[-1] is terminals[0]


@pytest.mark.asyncio
async def test_error_exit_emits_exactly_one_terminal_frame() -> None:
    pub = _RecordingPublisher()

    await publish_run(pub, _ErrorExecutor(), TOPIC, EXPR)

    terminals = pub.terminals()
    assert len(terminals) == 1
    assert terminals[0].data.status == "failed"
    assert terminals[0].data.error is not None
    assert pub.published[-1] is terminals[0]


@pytest.mark.asyncio
async def test_cancel_exit_emits_exactly_one_terminal_frame() -> None:
    pub = _RecordingPublisher()

    with pytest.raises(asyncio.CancelledError):
        await publish_run(pub, _CancellingExecutor(), TOPIC, EXPR)

    terminals = pub.terminals()
    assert len(terminals) == 1
    assert terminals[0].data.status == "stopped"
    assert pub.published[-1] is terminals[0]


@pytest.mark.asyncio
async def test_timeout_exit_emits_exactly_one_terminal_frame() -> None:
    pub = _RecordingPublisher()

    await publish_run(pub, _HangingExecutor(), TOPIC, EXPR, deadline_s=0.05)

    terminals = pub.terminals()
    assert len(terminals) == 1
    assert terminals[0].data.status == "timed_out"
    assert pub.published[-1] is terminals[0]


def test_sequencer_numbers_are_gap_free_and_monotonic() -> None:
    seq = _Sequencer(TOPIC, "root")

    numbers = [int(seq.next("00-trace")["sequence"]) for _ in range(5)]

    assert numbers == [1, 2, 3, 4, 5]


def test_sequencer_invariant_rejects_a_gap() -> None:
    seq = _Sequencer(TOPIC, "root")
    seq.next("00-trace")
    seq.next("00-trace")

    with pytest.raises(AssertionError):
        seq._check_invariants(previous=0)


def test_obs_state_engine_seq_is_gap_free_and_monotonic() -> None:
    obs = _ObsState(NullObserver(), "trace")

    assert [obs.next_seq() for _ in range(5)] == [1, 2, 3, 4, 5]


def test_obs_state_invariant_rejects_a_gap() -> None:
    obs = _ObsState(NullObserver(), "trace")
    obs.next_seq()
    obs.next_seq()

    with pytest.raises(AssertionError):
        obs._check_invariants(previous=0)

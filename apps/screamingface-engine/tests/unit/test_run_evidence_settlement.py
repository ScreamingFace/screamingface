"""E5 P1 spec R3: the one classifier that builds a `CandidateOutcome`.

FEATURE: first-class Runs (OME-1785). `settlement_of` reads the same verdict `outcome_of` gives the
evidence line, so the registry and `kubectl logs` can never disagree about how a run ended.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.run_evidence import (
    NO_TERMINAL_FRAME,
    SettlementWatch,
    TerminalWatch,
    outcome_of,
    settlement_of,
)
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for
from url4.streaming.protocol.taxonomy import ErrorInfo

pytestmark = pytest.mark.asyncio


def _terminated(status: Any, code: str | None = None) -> TerminatedEvent:
    error = None if code is None else ErrorInfo(code=code, message="details")
    return TerminatedEvent(
        id="term",
        source=source_for("topic"),
        subject="topic",
        data=TerminatedData(status=status, error=error),
    )


async def _finished_task(result: object = None, error: BaseException | None = None) -> Any:
    async def body() -> object:
        if error is not None:
            raise error
        return result

    task = asyncio.ensure_future(body())
    await asyncio.gather(task, return_exceptions=True)
    return task


async def _cancelled_task() -> Any:
    task = asyncio.ensure_future(asyncio.sleep(10))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return task


def test_a_settlement_watch_is_a_terminal_watch() -> None:
    assert issubclass(SettlementWatch, TerminalWatch)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("succeeded", None),
        ("failed", "provider_error"),
        ("timed_out", "deadline"),
        ("stopped", None),
    ],
)
async def test_the_terminal_frame_decides(status: Any, code: str | None) -> None:
    watch = SettlementWatch(InMemoryEventStream())
    await watch.publish("topic", _terminated(status, code))

    outcome = settlement_of(watch, await _finished_task(), cost_usd=Decimal("0.5"))

    assert outcome == CandidateOutcome(status, code, Decimal("0.5"))


async def test_the_watch_still_publishes_and_still_reports_the_log_verdict() -> None:
    stream = InMemoryEventStream()
    watch = SettlementWatch(stream)
    await watch.publish("topic", _terminated("failed", "provider_error"))

    assert (watch.outcome, watch.error) == ("failed", "provider_error: details")
    frame = await anext(stream.subscribe("topic"))
    assert isinstance(frame, TerminatedEvent)


async def test_a_run_that_raised_before_any_frame_failed() -> None:
    watch = SettlementWatch(InMemoryEventStream())

    outcome = settlement_of(watch, await _finished_task(error=RuntimeError("boom")))

    assert outcome == CandidateOutcome("failed", NO_TERMINAL_FRAME)


async def test_a_run_cancelled_before_any_frame_stopped() -> None:
    watch = SettlementWatch(InMemoryEventStream())

    assert settlement_of(watch, await _cancelled_task()) == CandidateOutcome("stopped")


async def test_a_run_with_no_frame_and_no_error_reads_as_failed() -> None:
    """WHY: the evidence line names it `unknown`; a Candidate has no such state, and nobody saw
    it succeed. The code says why, so it stays findable."""
    watch = SettlementWatch(InMemoryEventStream())

    outcome = settlement_of(watch, await _finished_task(), cost_usd=Decimal("0.1"))

    assert outcome == CandidateOutcome("failed", NO_TERMINAL_FRAME, Decimal("0.1"))


async def test_the_error_code_is_the_last_terminal_frames() -> None:
    watch = SettlementWatch(InMemoryEventStream())
    await watch.publish("topic", _terminated("failed", "provider_error"))
    await watch.publish("topic", _terminated("succeeded"))

    assert settlement_of(watch, await _finished_task()) == CandidateOutcome("succeeded")


async def test_the_evidence_error_is_the_last_terminal_frames_too() -> None:
    """INVARIANT (spec R3): one classifier, so the evidence line and the outcome agree."""
    watch = SettlementWatch(InMemoryEventStream())
    await watch.publish("topic", _terminated("failed", "provider_error"))
    await watch.publish("topic", _terminated("succeeded"))

    assert outcome_of(watch, await _finished_task()) == ("succeeded", None)

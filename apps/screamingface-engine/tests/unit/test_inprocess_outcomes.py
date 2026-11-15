"""The in-process runner publishes each run's Candidate outcome (OME-1785, E5 P1 spec R3)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal

import pytest

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    InMemoryEventStream,
)
from screamingface_engine.candidate_outcomes import CandidateOutcome, OutcomeDelivery
from screamingface_engine.runner.summary import RunSummary
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import ResultData
from url4.streaming.protocol.signals import CostUsageData
from url4.streaming.protocol.taxonomy import CostBreakdown, TokenUsage

pytestmark = pytest.mark.asyncio

TOPIC = "t-outcome"


def _subtree() -> CostUsageData:
    return CostUsageData(
        scope="self",
        provider="test",
        model="test-model",
        pricing_version="v0",
        usage=TokenUsage(input_tokens=0, output_tokens=0),
        cost=CostBreakdown(total_usd=Decimal("0")),
    )


class _Executor(Executor):
    """Completes, blocks or raises, and reports a summary like the real executor does."""

    def __init__(
        self,
        *,
        block: bool = False,
        boom: Exception | None = None,
        cost: Decimal | None = None,
    ) -> None:
        self._block = block
        self._boom = boom
        self._cost = cost

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        if self._boom is not None:
            raise self._boom
        if self._block:
            await asyncio.Event().wait()
        yield Completed(result=ResultData(body="ok"), subtree_cost=_subtree())

    def last_summary(self) -> RunSummary:
        return RunSummary(outcome="succeeded", trace_id=None, cost_usd=self._cost)


def _runner(executor: Executor, outcomes: InMemoryCandidateOutcomeStream) -> InProcessJobRunner:
    def factory(env: Mapping[str, str]) -> Executor:
        return executor

    return InProcessJobRunner(InMemoryEventStream(), factory, outcomes=outcomes)


async def _published(outcomes: InMemoryCandidateOutcomeStream) -> OutcomeDelivery:
    deliveries = outcomes.consume()
    try:
        return await asyncio.wait_for(anext(deliveries), 10)
    finally:
        await deliveries.aclose()


async def test_a_success_publishes_its_exact_cost() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(cost=Decimal("0.25")), outcomes)

    await runner.schedule(TOPIC, "q", 10)
    delivery = await _published(outcomes)

    assert (delivery.topic, delivery.outcome) == (
        TOPIC,
        CandidateOutcome("succeeded", None, Decimal("0.25")),
    )


async def test_a_failure_publishes_failed_with_the_frames_code() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(boom=RuntimeError("boom")), outcomes)

    await runner.schedule(TOPIC, "q", 10)
    outcome = (await _published(outcomes)).outcome

    assert outcome.status == "failed"
    assert outcome.error_code is not None


async def test_a_timeout_publishes_timed_out() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(block=True), outcomes)

    await runner.schedule(TOPIC, "q", 1)

    assert (await _published(outcomes)).outcome.status == "timed_out"


async def test_a_cancel_publishes_stopped() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(block=True), outcomes)

    await runner.schedule(TOPIC, "q", 60)
    await asyncio.sleep(0.05)
    await runner.stop(TOPIC)

    assert (await _published(outcomes)).outcome.status == "stopped"


async def test_exactly_one_outcome_per_run() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(), outcomes)

    await runner.schedule(TOPIC, "q", 10)
    deliveries = outcomes.consume()
    try:
        first = await asyncio.wait_for(anext(deliveries), 10)
        await first.ack()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(anext(deliveries), 0.2)
    finally:
        await deliveries.aclose()


async def test_a_failing_outcome_stream_never_breaks_the_run() -> None:
    class _Broken(InMemoryCandidateOutcomeStream):
        async def publish(self, topic: str, outcome: CandidateOutcome) -> None:
            raise ConnectionError("the stream is down")

    stream = InMemoryEventStream()
    runner = InProcessJobRunner(stream, lambda env: _Executor(), outcomes=_Broken())

    await runner.schedule(TOPIC, "q", 10)
    for _ in range(200):
        if await runner.status(TOPIC) == "succeeded":
            break
        await asyncio.sleep(0.01)
    assert await runner.status(TOPIC) == "succeeded"


async def test_without_an_outcome_stream_the_runner_is_unchanged() -> None:
    runner = InProcessJobRunner(InMemoryEventStream(), lambda env: _Executor())

    await runner.schedule(TOPIC, "q", 10)
    await asyncio.sleep(0.05)

    assert await runner.status(TOPIC) == "succeeded"

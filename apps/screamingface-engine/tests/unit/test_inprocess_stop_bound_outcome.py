"""E5 P2 spec R9 and R14: a stop on a local topic with no task publishes its `stopped` outcome.

FEATURE: a detached Run (OME-1837). STORY: as a researcher who cancels a local Run after a restart,
every Candidate it had sent settles, so the Run reads canceled instead of running forever.
"""

from __future__ import annotations

import asyncio

import pytest
from test_inprocess_outcomes import _Executor, _published, _runner

from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    InMemoryEventStream,
)
from screamingface_engine.candidate_outcomes import OutcomeDelivery

pytestmark = pytest.mark.asyncio

TOPIC = "t-bound"


async def _all(outcomes: InMemoryCandidateOutcomeStream) -> list[OutcomeDelivery]:
    seen: list[OutcomeDelivery] = []
    deliveries = outcomes.consume()
    try:
        while True:
            delivery = await asyncio.wait_for(anext(deliveries), 0.2)
            seen.append(delivery)
            await delivery.ack()
    except TimeoutError:
        return seen
    finally:
        await deliveries.aclose()


async def test_a_bound_topic_with_no_task_settles_stopped() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(), outcomes)

    await runner.stop_bound(TOPIC)

    delivery = await _published(outcomes)
    assert (delivery.topic, delivery.outcome.status) == (TOPIC, "stopped")


async def test_a_live_task_settles_once_through_its_own_end() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(block=True), outcomes)
    await runner.schedule(TOPIC, "q", 10)
    await asyncio.sleep(0)

    await runner.stop_bound(TOPIC)

    assert [(d.topic, d.outcome.status) for d in await _all(outcomes)] == [(TOPIC, "stopped")]


async def test_without_an_outcome_stream_nothing_is_published() -> None:
    runner = InProcessJobRunner(InMemoryEventStream(), lambda env: _Executor())

    await runner.stop_bound(TOPIC)


async def test_a_driver_started_topic_runs_once_in_this_process_even_after_it_ended() -> None:
    """R14 (review round 3): the driver sends a start again when it cannot record that it was
    sent; a local Run's start that already ran is refused as started, never run (and paid) a
    second time. A raw start keeps today's rule: refused only while it runs."""
    from url4.streaming.interfaces import JobAlreadyExists

    outcomes = InMemoryCandidateOutcomeStream()
    runner = _runner(_Executor(), outcomes)
    await runner.schedule(TOPIC, "q", 10, exclusive=True)
    await _published(outcomes)

    with pytest.raises(JobAlreadyExists):
        await runner.schedule(TOPIC, "q", 10, exclusive=True)

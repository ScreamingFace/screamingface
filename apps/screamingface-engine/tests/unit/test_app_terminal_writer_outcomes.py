"""The App's terminal writers publish a Candidate outcome only when their own frame landed
(OME-1785, E5 P1 spec R3).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from screamingface_engine.adapters.max_deliveries import MAX_DELIVERIES, MaxDeliveriesAdvisor
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.adapters.queue_runner import CANCELLED, QueueJobRunner
from screamingface_engine.candidate_outcomes import CandidateOutcome
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)


class _ConditionalPublisher:
    """The slice of `JetStreamPublisher` these writers use, with its first-terminal rule:
    `publish_next` writes nothing after a terminal frame. ``lose_the_race`` makes another
    writer's terminal frame land between the writer's tail read and its own append."""

    def __init__(self, *, lose_the_race: bool = False) -> None:
        self.frames: list[Any] = []
        self._lose_the_race = lose_the_race

    async def last_frame(self, topic: str) -> Any:
        return self.frames[-1] if self.frames else None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        raise AssertionError("a terminal writer must use publish_next")

    async def publish_next(self, topic: str, event: Any) -> bool:
        if self._lose_the_race:
            self.frames.append(_terminated(topic, "succeeded"))
        if self.frames and isinstance(self.frames[-1], TerminatedEvent):
            return False
        self.frames.append(event)
        return True

    async def flush(self) -> None:
        pass


class _Queue:
    async def publish(self, message: bytes, *, identity: Any = None) -> None:
        pass

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _NobodyOwnsIt:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _terminated(topic: str, status: Any) -> TerminatedEvent:
    return TerminatedEvent(
        id="other", source=source_for(topic), subject=topic, data=TerminatedData(status=status)
    )


def _queue_runner(
    publisher: _ConditionalPublisher, outcomes: InMemoryCandidateOutcomeStream
) -> QueueJobRunner:
    return QueueJobRunner(
        queue=_Queue(),
        publisher=publisher,
        control=_NobodyOwnsIt(),
        clock=lambda: T0,
        capability_lifetime_s=100.0,
        control_timeout_s=0.01,
        outcomes=outcomes,
    )


async def _published(outcomes: InMemoryCandidateOutcomeStream) -> list[tuple[str, Any]]:
    """Every outcome published so far."""
    seen: list[tuple[str, Any]] = []
    deliveries = outcomes.consume()
    try:
        while True:
            delivery = await asyncio.wait_for(anext(deliveries), 0.1)
            seen.append((delivery.topic, delivery.outcome))
            await delivery.ack()
    except TimeoutError:
        return seen
    finally:
        await deliveries.aclose()


async def test_a_tombstone_that_landed_publishes_stopped() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    runner = _queue_runner(_ConditionalPublisher(), outcomes)
    await runner.schedule("t", "'hi'", 60)

    await runner.stop("t")

    assert await _published(outcomes) == [("t", CandidateOutcome("stopped", CANCELLED))]


async def test_a_tombstone_that_lost_the_race_publishes_nothing() -> None:
    """INVARIANT (spec R3): the registry agrees with the terminal frame the Client reads."""
    outcomes = InMemoryCandidateOutcomeStream()
    publisher = _ConditionalPublisher(lose_the_race=True)
    runner = _queue_runner(publisher, outcomes)
    await runner.schedule("t", "'hi'", 60)

    await runner.stop("t")

    assert await _published(outcomes) == []


async def test_max_deliveries_that_landed_publishes_failed() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    advisor = MaxDeliveriesAdvisor("nats://localhost:4222", clock=lambda: T0, outcomes=outcomes)

    await advisor._publish_failure(_ConditionalPublisher(), "t")

    assert await _published(outcomes) == [("t", CandidateOutcome("failed", MAX_DELIVERIES))]


async def test_max_deliveries_losing_to_a_final_success_publishes_nothing() -> None:
    outcomes = InMemoryCandidateOutcomeStream()
    advisor = MaxDeliveriesAdvisor("nats://localhost:4222", clock=lambda: T0, outcomes=outcomes)

    await advisor._publish_failure(_ConditionalPublisher(lose_the_race=True), "t")

    assert await _published(outcomes) == []


async def test_without_an_outcome_stream_the_writers_are_unchanged() -> None:
    publisher = _ConditionalPublisher()
    advisor = MaxDeliveriesAdvisor("nats://localhost:4222", clock=lambda: T0)

    await advisor._publish_failure(publisher, "t")

    assert [frame.data.status for frame in publisher.frames] == ["failed"]

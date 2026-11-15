"""The one writer of Candidate outcomes (OME-1785, E5 P1 spec R4)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import pytest

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs.consumer import OutcomeWriter

pytestmark = pytest.mark.asyncio

ACK_WAIT_S = 0.05


class _Registry:
    """The slice of `RunRegistry` the writer calls, failing while `down` is set."""

    def __init__(self) -> None:
        self.down = False
        self.settled: list[tuple[str, CandidateOutcome]] = []

    async def settle(self, topic: str, outcome: CandidateOutcome) -> None:
        if self.down:
            raise ConnectionError("the database is down")
        self.settled.append((topic, outcome))


@asynccontextmanager
async def _writing(writer: OutcomeWriter) -> AsyncIterator[None]:
    task = asyncio.create_task(writer.run())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _until(condition: Callable[[], object], timeout: float = 2.0) -> None:
    async def wait() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


async def test_an_outcome_is_settled_then_acked() -> None:
    stream = InMemoryCandidateOutcomeStream(ack_wait_s=ACK_WAIT_S)
    registry = _Registry()
    async with _writing(OutcomeWriter(stream, registry, retry_s=0.01)):
        await stream.publish("t1", CandidateOutcome("succeeded"))
        await _until(lambda: registry.settled)
        await asyncio.sleep(ACK_WAIT_S * 3)

    # Acked: it was never delivered a second time.
    assert registry.settled == [("t1", CandidateOutcome("succeeded"))]


async def test_nothing_is_acked_while_the_registry_fails_and_the_redelivery_settles() -> None:
    """INVARIANT (spec R4): ack only after the commit, so an outage loses no outcome."""
    stream = InMemoryCandidateOutcomeStream(ack_wait_s=ACK_WAIT_S)
    registry = _Registry()
    registry.down = True
    async with _writing(OutcomeWriter(stream, registry, retry_s=0.01)):
        await stream.publish("t1", CandidateOutcome("failed", "provider_error"))
        await asyncio.sleep(ACK_WAIT_S * 3)
        assert registry.settled == []

        registry.down = False
        await _until(lambda: registry.settled)

    assert registry.settled == [("t1", CandidateOutcome("failed", "provider_error"))]


async def test_the_writer_keeps_writing_after_a_failure() -> None:
    stream = InMemoryCandidateOutcomeStream(ack_wait_s=ACK_WAIT_S)
    registry = _Registry()
    registry.down = True
    async with _writing(OutcomeWriter(stream, registry, retry_s=0.01)):
        await stream.publish("t1", CandidateOutcome("succeeded"))
        await asyncio.sleep(ACK_WAIT_S)
        registry.down = False
        await stream.publish("t2", CandidateOutcome("stopped"))
        await _until(lambda: {topic for topic, _ in registry.settled} == {"t1", "t2"})

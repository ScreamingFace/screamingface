"""#1759 review: one transient write failure never lets a later outcome of the same topic commit
before an earlier one (E5 P1 spec R4; E5 P2 spec §4.4, first-wins).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my Candidate's state is the outcome
that came first, even when the database blinked while it was written.
"""

from __future__ import annotations

import asyncio

import pytest

from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.candidate_outcomes import CandidateOutcome
from screamingface_engine.runs import consumer
from screamingface_engine.runs.consumer import OutcomeWriter

pytestmark = pytest.mark.asyncio

# WHY ack_wait well past retry_s: a restarted consumer would get the later outcome at once and the
# failed one only after ack_wait, which is the reordering this guards against.
ACK_WAIT_S = 0.5
RETRY_S = 0.01


class _Blinks:
    """Fails its first write, then records every write in order."""

    def __init__(self, failures: int = 1) -> None:
        self.failures = failures
        self.settled: list[tuple[str, CandidateOutcome]] = []

    async def settle(self, topic: str, outcome: CandidateOutcome) -> None:
        if self.failures:
            self.failures -= 1
            raise ConnectionError("the database blinked")
        self.settled.append((topic, outcome))


async def _written(registry: _Blinks, *outcomes: CandidateOutcome, count: int) -> None:
    stream = InMemoryCandidateOutcomeStream(ack_wait_s=ACK_WAIT_S)
    task = asyncio.create_task(OutcomeWriter(stream, registry, retry_s=RETRY_S).run())
    try:
        for outcome in outcomes:
            await stream.publish("t1", outcome)

        async def until_written() -> None:
            while len(registry.settled) < count:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(until_written(), 2.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_failed_write_is_tried_again_before_the_next_outcome() -> None:
    registry = _Blinks()

    await _written(
        registry,
        CandidateOutcome("failed", "provider_error"),
        CandidateOutcome("succeeded"),
        count=2,
    )

    assert [outcome.status for _, outcome in registry.settled] == ["failed", "succeeded"]


async def test_an_outcome_that_never_writes_holds_the_others_back_only_so_long() -> None:
    """Past `IN_PLACE_TRIES` the consumer restarts, so the next outcome is written."""
    registry = _Blinks(failures=consumer.IN_PLACE_TRIES)

    await _written(
        registry, CandidateOutcome("failed", "provider_error"), CandidateOutcome("stopped"), count=1
    )

    assert [outcome.status for _, outcome in registry.settled] == ["stopped"]

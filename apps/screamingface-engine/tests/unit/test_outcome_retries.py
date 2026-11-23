"""E5 P2 spec R6: a driver-started run's outcome is retried until the stream takes it.

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose Run outlived a broker outage, every
Candidate still settles, so my Run ends and its slots free.
"""

from __future__ import annotations

import asyncio
import os
import socket
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
from nats.errors import NoServersError

from screamingface_engine.adapters.candidate_outcomes_jetstream import (
    CandidateOutcomesStreamConfig,
    JetStreamCandidateOutcomeStream,
)
from screamingface_engine.adapters.memory import (
    InMemoryCandidateOutcomeStream,
    OutcomeStreamFull,
)
from screamingface_engine.candidate_outcomes import CandidateOutcome, OutcomeNotAccepted
from screamingface_engine.worker.outcome_retry import OutcomeRetries

pytestmark = pytest.mark.asyncio

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")
OUTCOME = CandidateOutcome("succeeded", None, Decimal("0.5"))


def _nats_reachable() -> bool:
    parsed = urlsplit(NATS_URL)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


class _Flaky:
    """An outcome stream that refuses ``refusals`` publishes with ``error``, then accepts."""

    def __init__(self, refusals: int, error: Exception | None = None) -> None:
        self.refusals = refusals
        self.error = error or OutcomeNotAccepted("the broker is unreachable")
        self.published: list[tuple[str, CandidateOutcome]] = []
        self.attempts = 0

    async def publish(self, topic: str, outcome: CandidateOutcome) -> None:
        self.attempts += 1
        if self.refusals:
            self.refusals -= 1
            raise self.error
        self.published.append((topic, outcome))


def _retries(stream: Any) -> OutcomeRetries:
    return OutcomeRetries(stream, first_delay_s=0.01, max_delay_s=0.02)


async def test_an_accepted_outcome_starts_no_retry() -> None:
    stream = _Flaky(0)
    retries = _retries(stream)

    await retries.publish("t1", OUTCOME)

    assert stream.published == [("t1", OUTCOME)]
    assert retries.pending == 0


async def test_a_refused_outcome_is_published_again_until_it_lands() -> None:
    stream = _Flaky(3)
    retries = _retries(stream)

    await retries.publish("t1", OUTCOME)
    await retries.drain(grace_s=5)

    assert stream.published == [("t1", OUTCOME)]
    assert stream.attempts == 4


async def test_any_other_refusal_is_dropped_as_today() -> None:
    stream = _Flaky(1, ValueError("an outcome the codec refuses"))
    retries = _retries(stream)

    await retries.publish("t1", OUTCOME)
    await retries.drain(grace_s=5)

    assert stream.published == []
    assert stream.attempts == 1


async def test_the_drain_stops_a_retry_that_never_lands() -> None:
    stream = _Flaky(10_000)
    retries = _retries(stream)

    await retries.publish("t1", OUTCOME)
    await asyncio.wait_for(retries.drain(grace_s=0.05), timeout=5)

    assert stream.published == []
    assert retries.pending == 0


async def test_a_full_in_memory_stream_is_not_accepted_now() -> None:
    assert issubclass(OutcomeStreamFull, OutcomeNotAccepted)
    stream = InMemoryCandidateOutcomeStream(max_outcomes=1)
    await stream.publish("t1", OUTCOME)

    with pytest.raises(OutcomeNotAccepted):
        await stream.publish("t2", OUTCOME)


@pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}")
async def test_a_full_jetstream_stream_is_not_accepted_now() -> None:
    """The broker answers a full `discard=new` stream with a 503 (code 10077)."""
    config = CandidateOutcomesStreamConfig(name=f"test-full-{uuid4().hex}", max_bytes=1024)
    stream = JetStreamCandidateOutcomeStream(NATS_URL, config=config)
    await stream.ensure_stream()
    try:
        with pytest.raises(OutcomeNotAccepted):
            for index in range(100):
                await stream.publish(f"t{index}", OUTCOME)
    finally:
        nc = await nats.connect(NATS_URL)
        try:
            await nc.jetstream().delete_stream(config.name)
        finally:
            await nc.close()
        await stream.close()


async def test_an_unreachable_broker_is_not_accepted_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nats, "connect", _refuse)
    stream = JetStreamCandidateOutcomeStream("nats://127.0.0.1:1")

    with pytest.raises(OutcomeNotAccepted):
        await stream.publish("t1", OUTCOME)


async def _refuse(*args: Any, **kwargs: Any) -> Any:
    raise NoServersError

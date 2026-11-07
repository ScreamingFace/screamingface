"""E5 P1 spec D4, R4, R6, R11: one contract over both `CandidateOutcomeStream` adapters.

FEATURE: first-class Runs (OME-1785). The in-memory adapter always runs; the JetStream one runs
where a broker is reachable (the CI conformance job, `URL4_CLOUD_TEST_NATS_URL`).
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
import pytest_asyncio
from nats.js.api import DiscardPolicy

from screamingface_engine.adapters.candidate_outcomes_jetstream import (
    CandidateOutcomesStreamConfig,
    CandidateOutcomesStreamConfigError,
    JetStreamCandidateOutcomeStream,
)
from screamingface_engine.adapters.memory import InMemoryCandidateOutcomeStream
from screamingface_engine.candidate_outcomes import (
    CandidateOutcome,
    CandidateOutcomeStream,
    OutcomeDelivery,
)

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")
ACK_WAIT_S = 1.0


def _nats_reachable() -> bool:
    parsed = urlsplit(NATS_URL)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


def _in_memory() -> CandidateOutcomeStream:
    return InMemoryCandidateOutcomeStream(ack_wait_s=ACK_WAIT_S)


def _jetstream() -> CandidateOutcomeStream:
    # WHY a fresh stream per test: the broker is shared, and a work queue keeps what is unacked.
    name = f"test-outcomes-{uuid4().hex}"
    return JetStreamCandidateOutcomeStream(
        NATS_URL,
        config=CandidateOutcomesStreamConfig(name=name, ack_wait_s=ACK_WAIT_S),
    )


ADAPTERS = [
    pytest.param(_in_memory, id="memory"),
    pytest.param(
        _jetstream,
        id="jetstream",
        marks=pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}"),
    ),
]


@pytest_asyncio.fixture(params=ADAPTERS)
async def stream(
    request: pytest.FixtureRequest,
) -> AsyncIterator[CandidateOutcomeStream]:
    factory: Callable[[], CandidateOutcomeStream] = request.param
    adapter = factory()
    await adapter.ensure_stream()
    try:
        yield adapter
    finally:
        if isinstance(adapter, JetStreamCandidateOutcomeStream):
            await _delete(adapter)


async def _delete(stream: JetStreamCandidateOutcomeStream) -> None:
    """Remove a test's stream from the shared broker. WHY not an adapter method: the Engine's
    only stream deletion is the legacy purge (`test_events_stream_layout.py`)."""
    await stream.close()
    nc = await nats.connect(NATS_URL)
    try:
        await nc.jetstream().delete_stream(stream.config.name)
    finally:
        await nc.close()


async def _next(deliveries: AsyncIterator[OutcomeDelivery], timeout: float) -> OutcomeDelivery:
    return await asyncio.wait_for(anext(deliveries), timeout)


@pytest.mark.asyncio
async def test_a_published_outcome_is_consumed(stream: CandidateOutcomeStream) -> None:
    outcome = CandidateOutcome("succeeded", cost_usd=Decimal("0.25"))
    await stream.publish("topic-a", outcome)

    delivery = await _next(stream.consume(), 5)

    assert (delivery.topic, delivery.outcome) == ("topic-a", outcome)


@pytest.mark.asyncio
async def test_an_unacked_outcome_is_delivered_again(stream: CandidateOutcomeStream) -> None:
    """INVARIANT (spec R4): an outcome the writer could not commit is never lost."""
    await stream.publish("topic-a", CandidateOutcome("failed", error_code="boom"))
    deliveries = stream.consume()

    first = await _next(deliveries, 5)
    again = await _next(deliveries, ACK_WAIT_S * 10)

    assert (again.topic, again.outcome) == (first.topic, first.outcome)


@pytest.mark.asyncio
async def test_an_acked_outcome_is_not_delivered_again(stream: CandidateOutcomeStream) -> None:
    await stream.publish("topic-a", CandidateOutcome("succeeded"))
    deliveries = stream.consume()
    await (await _next(deliveries, 5)).ack()

    with pytest.raises(TimeoutError):
        await _next(deliveries, ACK_WAIT_S * 3)


@pytest.mark.asyncio
async def test_outcomes_arrive_in_publish_order(stream: CandidateOutcomeStream) -> None:
    for index in range(3):
        await stream.publish(f"topic-{index}", CandidateOutcome("succeeded"))
    deliveries = stream.consume()

    topics = []
    for _ in range(3):
        delivery = await _next(deliveries, 5)
        topics.append(delivery.topic)
        await delivery.ack()

    assert topics == ["topic-0", "topic-1", "topic-2"]


@pytest.mark.asyncio
async def test_ensure_stream_is_idempotent(stream: CandidateOutcomeStream) -> None:
    await stream.ensure_stream()
    await stream.publish("topic-a", CandidateOutcome("succeeded"))
    await stream.ensure_stream()

    assert (await _next(stream.consume(), 5)).topic == "topic-a"


def test_only_the_broker_survives_a_restart() -> None:
    """Spec R6: reconcile reads this property, never a mode flag."""
    assert JetStreamCandidateOutcomeStream(NATS_URL).survives_restart is True
    assert InMemoryCandidateOutcomeStream().survives_restart is False


@pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}")
@pytest.mark.asyncio
async def test_a_malformed_message_is_dropped_not_redelivered() -> None:
    """WHY: a payload no writer can decode would otherwise loop forever ahead of real outcomes."""
    stream = _jetstream()
    assert isinstance(stream, JetStreamCandidateOutcomeStream)
    await stream.ensure_stream()
    try:
        nc = await nats.connect(NATS_URL)
        try:
            await nc.jetstream().publish(stream.config.subject, b"not an outcome")
        finally:
            await nc.close()
        await stream.publish("topic-a", CandidateOutcome("succeeded"))
        deliveries = stream.consume()

        delivery = await _next(deliveries, 5)
        await delivery.ack()

        assert delivery.topic == "topic-a"
        with pytest.raises(TimeoutError):
            await _next(deliveries, ACK_WAIT_S * 3)
    finally:
        await _delete(stream)


@pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}")
@pytest.mark.asyncio
async def test_ensure_stream_never_rewrites_a_live_streams_limits() -> None:
    """WHY: a process built with the defaults must not shrink a stream an operator widened."""
    widened = _jetstream()
    assert isinstance(widened, JetStreamCandidateOutcomeStream)
    name = widened.config.name
    wide = CandidateOutcomesStreamConfig(name=name, max_bytes=128 * 1024**2)
    await JetStreamCandidateOutcomeStream(NATS_URL, config=wide).ensure_stream()
    try:
        await widened.ensure_stream()

        nc = await nats.connect(NATS_URL)
        try:
            info = await nc.jetstream().stream_info(name)
        finally:
            await nc.close()
        assert info.config.max_bytes == 128 * 1024**2
    finally:
        await _delete(widened)


def test_a_full_stream_refuses_new_outcomes_instead_of_dropping_old_ones() -> None:
    assert CandidateOutcomesStreamConfig().stream_config().discard == DiscardPolicy.NEW


@pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}")
@pytest.mark.asyncio
async def test_an_existing_stream_that_drops_old_outcomes_is_refused() -> None:
    """WHY: `discard=old` would silently drop outcomes not yet written (spec R4)."""
    stream = _jetstream()
    assert isinstance(stream, JetStreamCandidateOutcomeStream)
    wanted = stream.config.stream_config()
    wanted.discard = DiscardPolicy.OLD
    nc = await nats.connect(NATS_URL)
    try:
        await nc.jetstream().add_stream(wanted)
    finally:
        await nc.close()
    try:
        with pytest.raises(CandidateOutcomesStreamConfigError, match="discard"):
            await stream.ensure_stream()
    finally:
        await _delete(stream)


@pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}")
@pytest.mark.asyncio
async def test_an_existing_writer_consumer_takes_this_codes_redelivery_rule() -> None:
    """WHY: `pull_subscribe` binds an existing durable as it is; a `max_deliver=1` left on it
    would stop redelivery, and an outcome the writer could not commit would be lost."""
    stream = _jetstream()
    assert isinstance(stream, JetStreamCandidateOutcomeStream)
    await stream.ensure_stream()
    stale = stream.config.consumer_config()
    stale.max_deliver = 1
    nc = await nats.connect(NATS_URL)
    try:
        await nc.jetstream().add_consumer(stream.config.name, stale)
        await stream.publish("topic-a", CandidateOutcome("succeeded"))
        deliveries = stream.consume()
        await _next(deliveries, 5)  # never acked

        again = await _next(deliveries, 5 + ACK_WAIT_S)

        assert again.topic == "topic-a"
        info = await nc.jetstream().consumer_info(stream.config.name, stream.config.consumer)
        assert info.config.max_deliver in (None, -1)
    finally:
        await nc.close()
        await _delete(stream)

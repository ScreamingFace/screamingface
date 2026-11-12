"""E5 P2 spec D7 and R3: one contract over both `TopicClaims` adapters.

FEATURE: a detached Run (OME-1837). STORY: as a researcher, a Candidate the Engine starts twice
runs once, so I never pay for it twice.

The in-memory adapter always runs; the JetStream one runs where a broker is reachable (the CI
conformance job, `URL4_CLOUD_TEST_NATS_URL`). WHY a real broker before any worker code: the bucket
is the Engine's first use of NATS key-value, and its atomic create and compare-and-set are what
the worker's claim step stands on (spec §8).
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
import pytest_asyncio
from nats.js.api import StorageType

from screamingface_engine.adapters.memory import InMemoryTopicClaims
from screamingface_engine.adapters.topic_claims_jetstream import (
    JetStreamTopicClaims,
    TopicClaimsBucketConfig,
    TopicClaimsBucketConfigError,
)
from screamingface_engine.topic_claims import Claim, TopicClaims, TopicClaimsUnavailable

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")
# Short enough that a test can wait for an entry to expire.
MAX_AGE_S = 1.0
TOPIC = "url4-cloud.5f1c2a"


def _nats_reachable() -> bool:
    parsed = urlsplit(NATS_URL)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


NO_BROKER = pytest.mark.skipif(not _nats_reachable(), reason=f"no NATS at {NATS_URL}")


def _in_memory() -> TopicClaims:
    return InMemoryTopicClaims(max_age_s=MAX_AGE_S)


def _bucket_config() -> TopicClaimsBucketConfig:
    # WHY a fresh bucket per test: the broker is shared, and a claim outlives its test.
    return TopicClaimsBucketConfig(bucket=f"test-claims-{uuid4().hex}", max_age_s=MAX_AGE_S)


def _jetstream() -> TopicClaims:
    return JetStreamTopicClaims(NATS_URL, config=_bucket_config())


ADAPTERS = [
    pytest.param(_in_memory, id="memory"),
    pytest.param(_jetstream, id="jetstream", marks=NO_BROKER),
]


@pytest_asyncio.fixture(params=ADAPTERS)
async def claims(request: pytest.FixtureRequest) -> AsyncIterator[TopicClaims]:
    factory: Callable[[], TopicClaims] = request.param
    adapter = factory()
    await adapter.ensure_bucket(update=True)
    try:
        yield adapter
    finally:
        if isinstance(adapter, JetStreamTopicClaims):
            await _delete(adapter.config)
        await adapter.close()


async def _delete(config: TopicClaimsBucketConfig) -> None:
    nc = await nats.connect(NATS_URL)
    try:
        await nc.jetstream().delete_stream(config.stream)
    finally:
        await nc.close()


@pytest.mark.asyncio
async def test_a_new_claim_names_its_worker(claims: TopicClaims) -> None:
    claim = await claims.claim(TOPIC, "worker-a")

    assert claim.holder == "worker-a"
    assert not claim.finished


@pytest.mark.asyncio
async def test_a_second_claim_reads_the_first(claims: TopicClaims) -> None:
    first = await claims.claim(TOPIC, "worker-a")

    assert await claims.claim(TOPIC, "worker-b") == first


@pytest.mark.asyncio
async def test_of_two_racing_claims_exactly_one_wins(claims: TopicClaims) -> None:
    """INVARIANT (D7): an atomic create decides between two workers, however close they are."""
    a, b = await asyncio.gather(claims.claim(TOPIC, "worker-a"), claims.claim(TOPIC, "worker-b"))

    assert a == b
    assert a.holder in {"worker-a", "worker-b"}


@pytest.mark.asyncio
async def test_a_claim_names_the_same_worker_on_a_second_copy(claims: TopicClaims) -> None:
    """A copy whose claim names this worker runs (R3), so the read must say so."""
    first = await claims.claim(TOPIC, "worker-a")

    assert await claims.claim(TOPIC, "worker-a") == first


@pytest.mark.asyncio
async def test_topics_are_claimed_independently(claims: TopicClaims) -> None:
    await claims.claim(TOPIC, "worker-a")

    assert (await claims.claim(f"{TOPIC}-2", "worker-b")).holder == "worker-b"


@pytest.mark.asyncio
async def test_any_topic_is_a_valid_key(claims: TopicClaims) -> None:
    """WHY: a key-value key allows few characters; the adapter keys by the topic's checksum."""
    topic = "url4-cloud.* a topic/with > every: odd character ü"

    assert (await claims.claim(topic, "worker-a")).holder == "worker-a"


@pytest.mark.asyncio
async def test_a_takeover_at_the_read_revision_moves_the_claim(claims: TopicClaims) -> None:
    held = await claims.claim(TOPIC, "worker-a")

    taken = await claims.take_over(TOPIC, "worker-b", held.revision)

    assert taken is not None
    assert taken.holder == "worker-b"
    assert taken.revision != held.revision
    assert await claims.claim(TOPIC, "worker-c") == taken


@pytest.mark.asyncio
async def test_a_takeover_at_a_stale_revision_fails(claims: TopicClaims) -> None:
    """INVARIANT (R3): of two workers taking over a dead holder's claim, exactly one runs."""
    held = await claims.claim(TOPIC, "worker-a")
    taken = await claims.take_over(TOPIC, "worker-b", held.revision)

    assert await claims.take_over(TOPIC, "worker-c", held.revision) is None
    assert await claims.claim(TOPIC, "worker-d") == taken


@pytest.mark.asyncio
async def test_of_two_racing_takeovers_exactly_one_wins(claims: TopicClaims) -> None:
    held = await claims.claim(TOPIC, "worker-a")

    b, c = await asyncio.gather(
        claims.take_over(TOPIC, "worker-b", held.revision),
        claims.take_over(TOPIC, "worker-c", held.revision),
    )

    assert [taken is None for taken in (b, c)].count(True) == 1
    winner = b or c
    assert winner is not None
    assert await claims.claim(TOPIC, "worker-d") == winner


@pytest.mark.asyncio
async def test_a_finished_claim_reads_as_finished(claims: TopicClaims) -> None:
    await claims.claim(TOPIC, "worker-a")

    await claims.finish(TOPIC, "worker-a")

    claim = await claims.claim(TOPIC, "worker-b")
    assert claim.holder == "worker-a"
    assert claim.finished


@pytest.mark.asyncio
async def test_finish_leaves_a_claim_another_worker_took_over(claims: TopicClaims) -> None:
    held = await claims.claim(TOPIC, "worker-a")
    taken = await claims.take_over(TOPIC, "worker-b", held.revision)

    await claims.finish(TOPIC, "worker-a")

    assert await claims.claim(TOPIC, "worker-c") == taken


@pytest.mark.asyncio
async def test_finish_without_a_claim_writes_nothing(claims: TopicClaims) -> None:
    await claims.finish(TOPIC, "worker-a")

    claim = await claims.claim(TOPIC, "worker-b")
    assert claim.holder == "worker-b"
    assert not claim.finished


@pytest.mark.asyncio
async def test_a_claim_expires_with_the_events_retention(claims: TopicClaims) -> None:
    """WHY it may expire: by then the topic's frames are gone too (spec §4.4)."""
    await claims.claim(TOPIC, "worker-a")

    async def _claimed_anew() -> Claim:
        while True:
            claim = await claims.claim(TOPIC, "worker-b")
            if claim.holder == "worker-b":
                return claim
            await asyncio.sleep(0.2)

    claim = await asyncio.wait_for(_claimed_anew(), timeout=MAX_AGE_S + 5)
    assert not claim.finished


@pytest.mark.asyncio
async def test_declaring_the_bucket_again_keeps_its_claims(claims: TopicClaims) -> None:
    first = await claims.claim(TOPIC, "worker-a")

    await claims.ensure_bucket(update=True)
    await claims.ensure_bucket()

    assert await claims.claim(TOPIC, "worker-b") == first


@NO_BROKER
@pytest.mark.asyncio
async def test_a_racing_declaration_reconciles_against_the_winner() -> None:
    """WHY: every worker declares the bucket at the same startup."""
    config = _bucket_config()
    adapters = [JetStreamTopicClaims(NATS_URL, config=config) for _ in range(4)]
    try:
        await asyncio.gather(*(adapter.ensure_bucket(update=True) for adapter in adapters))
        claim = await adapters[0].claim(TOPIC, "worker-a")
        assert await adapters[1].claim(TOPIC, "worker-b") == claim
    finally:
        await _delete(config)
        for adapter in adapters:
            await adapter.close()


@NO_BROKER
@pytest.mark.asyncio
async def test_the_bucket_is_declared_without_nats_py_create_key_value() -> None:
    """INVARIANT (plan E2): look, then create only what is missing. The stream is still a
    key-value bucket nats-py binds to."""
    config = _bucket_config()
    adapter = JetStreamTopicClaims(NATS_URL, config=config)
    nc = await nats.connect(NATS_URL)
    try:
        await adapter.ensure_bucket(update=True)
        info = (await nc.jetstream().stream_info(config.stream)).config
        assert info.max_msgs_per_subject == 1
        assert info.max_age == MAX_AGE_S
        assert info.storage == StorageType.FILE
        kv = await nc.jetstream().key_value(config.bucket)
        assert kv is not None
    finally:
        await _delete(config)
        await nc.close()
        await adapter.close()


@NO_BROKER
@pytest.mark.asyncio
async def test_startup_applies_a_changed_age_and_others_leave_it() -> None:
    config = _bucket_config()
    longer = TopicClaimsBucketConfig(bucket=config.bucket, max_age_s=MAX_AGE_S * 3)
    nc = await nats.connect(NATS_URL)
    try:
        await JetStreamTopicClaims(NATS_URL, config=config).ensure_bucket(update=True)
        await JetStreamTopicClaims(NATS_URL, config=longer).ensure_bucket()
        assert (await nc.jetstream().stream_info(config.stream)).config.max_age == MAX_AGE_S

        await JetStreamTopicClaims(NATS_URL, config=longer).ensure_bucket(update=True)
        assert (await nc.jetstream().stream_info(config.stream)).config.max_age == MAX_AGE_S * 3
    finally:
        await _delete(config)
        await nc.close()


@NO_BROKER
@pytest.mark.asyncio
async def test_a_bucket_stored_differently_is_refused() -> None:
    config = _bucket_config()
    in_memory = TopicClaimsBucketConfig(
        bucket=config.bucket, max_age_s=MAX_AGE_S, storage=StorageType.MEMORY
    )
    try:
        await JetStreamTopicClaims(NATS_URL, config=config).ensure_bucket(update=True)
        with pytest.raises(TopicClaimsBucketConfigError, match="storage"):
            await JetStreamTopicClaims(NATS_URL, config=in_memory).ensure_bucket(update=True)
    finally:
        await _delete(config)


@NO_BROKER
@pytest.mark.asyncio
async def test_a_missing_bucket_reads_as_unavailable() -> None:
    """R3: a worker that cannot use the bucket runs its copy, so the error must be one it can
    name."""
    adapter = JetStreamTopicClaims(NATS_URL, config=_bucket_config())
    try:
        with pytest.raises(TopicClaimsUnavailable):
            await adapter.claim(TOPIC, "worker-a")
    finally:
        await adapter.close()


def test_the_bucket_takes_the_event_streams_retention_replicas_and_storage() -> None:
    from screamingface_engine.adapters.jetstream import EventsStreamConfig

    events = EventsStreamConfig(max_age_s=3600.0, replicas=3, storage=StorageType.MEMORY)

    config = TopicClaimsBucketConfig.for_events(events)

    assert config.bucket == "url4-claims"
    assert (config.max_age_s, config.replicas, config.storage) == (3600.0, 3, StorageType.MEMORY)


def test_the_pool_builds_the_bucket_from_its_event_stream_settings() -> None:
    from screamingface_engine.adapters.factory import build_topic_claims
    from screamingface_engine.config import Settings

    claims = build_topic_claims(Settings(events_max_age_s=172_800, events_replicas=3))

    assert claims.config.bucket == "url4-claims"
    assert (claims.config.max_age_s, claims.config.replicas) == (172_800, 3)

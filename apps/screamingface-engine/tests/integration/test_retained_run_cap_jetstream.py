"""The retained-run cap against a real JetStream (OME-1462).

The unit tests prove the arithmetic against a fake that applies `keep` and `seq` the way the
broker is documented to. This proves the broker agrees: a subject-filtered purge with `keep`,
a forward `next_by_subj` scan, and a subject-filtered purge below a stream sequence, on the
SHARED stream, leaving every other subject alone.
"""

import os
import socket
from urllib.parse import urlsplit
from uuid import uuid4

import nats
import pytest
from nats.js import JetStreamContext
from nats.js.errors import NotFoundError

from screamingface_engine.adapters.jetstream import EventsStreamConfig, JetStreamPublisher
from screamingface_engine.subjects import EVENTS_STREAM, subject_for

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")


def _nats_reachable(url: str = NATS_URL) -> bool:
    parsed = urlsplit(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _nats_reachable(),
        reason=f"needs a reachable NATS at {NATS_URL} (set URL4_CLOUD_TEST_NATS_URL)",
    ),
]


async def _payloads(js: JetStreamContext, topic: str) -> list[bytes]:
    """Every payload left on the topic's subject, oldest first."""
    out: list[bytes] = []
    seq = 1
    while True:
        try:
            msg = await js.get_msg(EVENTS_STREAM, seq=seq, subject=subject_for(topic), next=True)
        except NotFoundError:
            return out
        out.append(msg.data or b"")
        seq = (msg.seq or seq) + 1


async def test_a_retained_subject_is_capped_and_its_neighbour_is_not() -> None:
    topic, neighbour = f"cap-{uuid4().hex}", f"cap-n-{uuid4().hex}"
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    # Six frames of 40 bytes each; the cap is 3 frames, then 80 bytes — two frames.
    publisher = JetStreamPublisher(
        NATS_URL, events=EventsStreamConfig(retained_max_msgs=3, retained_max_bytes=80)
    )
    try:
        await publisher.ensure_stream(topic)
        for n in range(6):
            await js.publish(subject_for(topic), f"{n}".encode() * 40)
            await js.publish(subject_for(neighbour), f"{n}".encode() * 40)

        await publisher.trim_retained(topic)

        assert await _payloads(js, topic) == [b"4" * 40, b"5" * 40]
        assert len(await _payloads(js, neighbour)) == 6
    finally:
        await publisher.close()
        await nc.close()


async def test_an_oversized_terminal_frame_survives_the_byte_cap() -> None:
    topic = f"cap-big-{uuid4().hex}"
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    publisher = JetStreamPublisher(
        NATS_URL, events=EventsStreamConfig(retained_max_msgs=10, retained_max_bytes=10)
    )
    try:
        await publisher.ensure_stream(topic)
        await js.publish(subject_for(topic), b"a" * 5)
        await js.publish(subject_for(topic), b"T" * 500)

        await publisher.trim_retained(topic)

        assert await _payloads(js, topic) == [b"T" * 500]
    finally:
        await publisher.close()
        await nc.close()

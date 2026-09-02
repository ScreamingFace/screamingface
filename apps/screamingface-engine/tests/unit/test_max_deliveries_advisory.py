"""The max-deliveries advisory subscriber (OME-1090): a run the queue gave up on gets a
named terminal failure on its own event stream.

JetStream publishes `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.url4-runq.url4-runners`
when a queue message has been redelivered `max_deliver` times without an ack. The App
subscribes, decodes the run's topic from the advisory's embedded message, and publishes
`Terminated(failed)` — the run's status derivation then reads that frame like any other
terminal outcome.
"""

import base64
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from screamingface_engine.adapters.max_deliveries import (
    MAX_DELIVERIES,
    MAX_DELIVERIES_ADVISORY_SUBJECT,
    MaxDeliveriesAdvisor,
    topic_of_advisory,
)
from screamingface_engine.runner_queue import encode_message
from url4.streaming.protocol import TerminatedEvent

T0 = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)


def _advisory(topic: str) -> bytes:
    """A max-deliveries advisory as JetStream publishes it: the original queue message's
    body base64-encoded under `message.data`."""
    body = encode_message(topic, "'hi'", 60)
    return json.dumps(
        {
            "type": "io.nats.jetstream.advisory.v1.max_deliver",
            "stream": "url4-runq",
            "consumer": "url4-runners",
            "stream_seq": 1,
            "deliveries": 2,
            "message": {
                "subject": "url4-runq.work",
                "seq": 1,
                "data": base64.b64encode(body).decode("utf-8"),
            },
        }
    ).encode("utf-8")


def test_the_advisory_subject_names_the_queue_stream_and_consumer() -> None:
    assert MAX_DELIVERIES_ADVISORY_SUBJECT == (
        "$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.url4-runq.url4-runners"
    )


def test_topic_of_advisory_decodes_the_runs_topic() -> None:
    assert topic_of_advisory(_advisory("t-advisory")) == "t-advisory"


def test_topic_of_advisory_returns_none_for_garbage() -> None:
    assert topic_of_advisory(b"not json") is None
    assert topic_of_advisory(b"{}") is None
    assert topic_of_advisory(b'{"message": {"data": "!!!"}}') is None


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[Any] = []
        self.ensured: list[str] = []

    async def ensure_stream(self, topic: str) -> None:
        self.ensured.append(topic)

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


@pytest.mark.asyncio
async def test_the_advisor_publishes_a_named_terminal_failure() -> None:
    advisor = MaxDeliveriesAdvisor("nats://localhost:4222", clock=lambda: T0)
    publisher = _FakePublisher()
    await advisor._handle(publisher, _advisory("t-gave-up"))

    assert publisher.ensured == ["t-gave-up"]
    assert len(publisher.published) == 1
    frame = publisher.published[0]
    assert isinstance(frame, TerminatedEvent)
    assert frame.data.status == "failed"
    assert frame.data.error is not None and frame.data.error.code == MAX_DELIVERIES
    assert frame.source.endswith("t-gave-up")

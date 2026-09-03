"""The max-deliveries advisory subscriber (OME-1090): a run the queue gave up on gets a
named terminal failure on its own event stream.

JetStream publishes `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.url4-runq.url4-runners`
when a queue message has been redelivered `max_deliver` times without an ack. The App
subscribes, decodes the run's topic from the advisory's embedded message, and publishes
`Terminated(failed)` — the run's status derivation then reads that frame like any other
terminal outcome.
"""

import asyncio
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
from url4.streaming.protocol import TerminatedData, TerminatedEvent, source_for

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
    # The consumer token is wildcarded: consumers are `url4-runners-<bucket>` — ONE token
    # (dashes are not NATS separators) — so `.*` matches it, while `.url4-runners.*`
    # would demand a second token and match nothing.
    assert MAX_DELIVERIES_ADVISORY_SUBJECT == (
        "$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.url4-runq.*"
    )


def test_topic_of_advisory_decodes_the_runs_topic() -> None:
    assert topic_of_advisory(_advisory("t-advisory")) == "t-advisory"


def test_topic_of_advisory_returns_none_for_garbage() -> None:
    assert topic_of_advisory(b"not json") is None
    assert topic_of_advisory(b"{}") is None
    assert topic_of_advisory(b'{"message": {"data": "!!!"}}') is None


class _FakePublisher:
    def __init__(self, last_frame: Any = None) -> None:
        self.published: list[Any] = []
        self.ensured: list[str] = []
        self._last_frame = last_frame

    async def last_frame(self, topic: str) -> Any:
        return self._last_frame

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


def _terminated(topic: str, status: str) -> TerminatedEvent:
    return TerminatedEvent(
        id="x",
        source=source_for(topic),
        subject=topic,
        time=T0,
        data=TerminatedData(status=status),
    )


@pytest.mark.asyncio
async def test_the_advisor_never_overwrites_a_run_that_actually_finished() -> None:
    """The advisory and the run race: a worker on its FINAL redelivery can complete and
    publish `Terminated(succeeded)` right as the expired ack_wait fires the advisory —
    the run finished, the broker merely missed the ack. Publishing unconditionally
    appended `failed` AFTER the success, and status() — a last-frame read — reported a
    succeeded run as failed. The advisor reads the tail first; a terminal frame means
    the run already has its outcome."""
    advisor = MaxDeliveriesAdvisor("nats://localhost:4222", clock=lambda: T0)
    success = _terminated("t-finished", "succeeded")
    publisher = _FakePublisher(last_frame=success)

    await advisor._handle(publisher, _advisory("t-finished"))

    assert publisher.published == [], "the run's own outcome stands"
    assert publisher.ensured == [], "nothing was declared on its account either"


def test_the_advisory_subject_follows_the_configured_stream_name() -> None:
    """P2-4: the subject was a hardcoded `url4-runq` literal — a renamed queue publishes
    advisories on a different subject, and a subscription on the default would silently
    stop hearing every max-deliveries event (each run the queue gave up on ending
    without a terminal frame). The subject now comes from the constructor."""
    advisor = MaxDeliveriesAdvisor("nats://x", run_queue_stream="prod-runq")
    assert advisor._subject == "$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.prod-runq.*"
    assert MaxDeliveriesAdvisor("nats://x")._subject == MAX_DELIVERIES_ADVISORY_SUBJECT


class _connecting_nc:
    """A connect() replacement whose subscription ends immediately, counting connects
    and closes. WHY the `sleep(0)` in connect: without it, the UNFIXED run loop (which
    reconnects without sleeping on a normal `_serve` return) spins through these
    instantly-completing awaits without ever yielding — starving the event loop so the
    test HANGS instead of failing. One yield per connect keeps the hot spin observable
    AND cancellable."""

    connects = 0
    closes = 0

    class _EndingSub:
        @property
        def messages(self) -> Any:
            async def _end() -> Any:
                return
                yield  # pragma: no cover — an immediately-ending async generator

            return _end()

    class _NC:
        async def subscribe(self, subject: str) -> "_connecting_nc._EndingSub":
            return _connecting_nc._EndingSub()

        async def close(self) -> None:
            _connecting_nc.closes += 1

    @classmethod
    async def connect(cls, _url: str) -> "_connecting_nc._NC":
        await asyncio.sleep(0)
        cls.connects += 1
        return cls._NC()


@pytest.mark.asyncio
async def test_a_normal_serve_return_is_treated_as_a_disconnect(monkeypatch: Any) -> None:
    """P2-5: a dropped subscription ends `_serve`'s `async for` NORMALLY — `_serve`
    returns without raising — so `run()` used to reconnect without closing the previous
    nc/publisher pair (leaking the publisher's own lazy connection every round) and,
    when the fresh subscription died immediately, spun in a tight loop. Every iteration
    now closes and backs off."""
    import contextlib

    import screamingface_engine.adapters.max_deliveries as mod

    real_delay = mod.RETRY_DELAY_S
    monkeypatch.setattr(mod, "RETRY_DELAY_S", 0.01)
    monkeypatch.setattr(mod.nats, "connect", _connecting_nc.connect)
    try:
        advisor = mod.MaxDeliveriesAdvisor("nats://x")
        task = asyncio.create_task(advisor.run())
        try:
            while _connecting_nc.connects < 2:
                await asyncio.sleep(0.01)
            assert _connecting_nc.closes >= 1, "aclose must run between reconnects, never leaked"
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        monkeypatch.setattr(mod, "RETRY_DELAY_S", real_delay)

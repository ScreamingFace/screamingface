import os
import socket
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, NamedTuple
from urllib.parse import urlsplit

import pytest
from _pytest.mark import ParameterSet

from screamingface_engine.adapters.jetstream import JetStreamConsumer, JetStreamPublisher
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import (
    Completed,
    EventStream,
    ExecStep,
    Executor,
    JobAlreadyExists,
    JobStatus,
    TraceContext,
    job_name,
)
from url4.streaming.protocol import (
    CachePolicy,
    CostUsageData,
    LogData,
    OutboundFrame,
    ResultData,
    SpanData,
    TokenUsage,
)
from url4.streaming.protocol.taxonomy import CostBreakdown
from url4.streaming.testing import TAKE_TIMEOUT_S, take

NATS_URL = os.environ.get("URL4_CLOUD_TEST_NATS_URL", "nats://localhost:4222")


def _nats_reachable(url: str = NATS_URL) -> bool:
    """Whether a NATS server is listening, probed once at collection time.

    WHY this is `skipif` and not a bare `skip`: these parameters are the ONLY thing that ever runs
    the conformance suite against the real broker, and a bare `skip` disables them unconditionally
    — not just in CI, but on a developer machine with NATS already running, and with no way to opt
    in. The one class of bug this system has actually shipped (a WS hang that survived a green
    suite) came from `InMemoryEventStream` and `JetStreamConsumer` disagreeing, which is precisely
    what a real-broker run of the shared contract catches and a fake-only run cannot.
    """
    parsed = urlsplit(url)
    try:
        with socket.create_connection((parsed.hostname or "localhost", parsed.port or 4222), 0.5):
            return True
    except OSError:
        return False


NATS_AVAILABLE = _nats_reachable()


class _JetStreamEventStream(EventStream):
    """Composes the production Consumer/Publisher pair into one `EventStream` for the shared
    conformance suite, which needs both directions on one object.

    `JetStreamConsumer` (App-side: subscribe/purge/ensure_stream) and `JetStreamPublisher`
    (Runner-side: publish) are deliberately TWO classes in production — the two deployables that
    use them may not import each other (`adapters/jetstream.py`'s own docstring). They never share
    a process there. Here they share a NATS connection pair, which is what the real system does
    end to end: the App ensures the stream when a subscriber attaches, the Runner only ever
    publishes into a stream that already exists — `JetStreamPublisher.publish` does not call
    `ensure_stream` itself, so this composite's `ensure_stream` correctly delegates to the
    consumer alone, matching production ordering rather than papering over it.
    """

    def __init__(self, nats_url: str) -> None:
        self._consumer = JetStreamConsumer(nats_url)
        self._publisher = JetStreamPublisher(nats_url)

    async def ensure_stream(self, topic: str) -> None:
        await self._consumer.ensure_stream(topic)

    async def publish(self, topic: str, event: OutboundFrame) -> None:
        await self._publisher.publish(topic, event)
        # WHY flush here (OME-906): `JetStreamPublisher.publish` now DEFERS its
        # acknowledgement, so it returns before the broker has confirmed the frame. The shared
        # contract suite publishes and then reads, and it must mean the same thing for both
        # parameters — `InMemoryEventStream.publish` is durable on return, so this composite
        # makes itself durable on return too.
        #
        # AIDEV-NOTE: this deliberately DIVERGES from the Runner, which flushes once at the
        # outcome boundary rather than per frame — that is the whole point of the pipeline. The
        # contract suite asserts sequence, replay and purge semantics, not durability timing;
        # the timing is covered by `test_jetstream_pipelining.py`. Do not "fix" this to match
        # production, and do not add a flush to the contract suite instead: that would make
        # every adapter's contract depend on a barrier only one of them needs.
        await self._publisher.flush()

    def subscribe(
        self, topic: str, from_sequence: int | None = None
    ) -> AsyncIterator[OutboundFrame]:
        return self._consumer.subscribe(topic, from_sequence)

    async def purge(self, topic: str) -> None:
        await self._consumer.purge(topic)

    async def delete_stream(self, topic: str) -> None:
        await self._consumer.delete_stream(topic)

    async def close(self) -> None:
        await self._consumer.close()
        await self._publisher.close()


STREAM_FACTORIES: list[Callable[[], EventStream] | ParameterSet] = [
    pytest.param(InMemoryEventStream, id="InMemoryEventStream"),
    pytest.param(
        lambda: _JetStreamEventStream(NATS_URL),
        id="JetStreamConsumer",
        marks=pytest.mark.skipif(
            not NATS_AVAILABLE,
            reason=f"needs a reachable NATS at {NATS_URL} (set URL4_CLOUD_TEST_NATS_URL)",
        ),
    ),
]


class ScheduledRun(NamedTuple):
    topic: str
    url4: str
    deadline_s: int
    traceparent: str | None
    credential: str | None
    profile: str | None
    identity: Mapping[str, str] | None = None


class RecordingJobRunner(IdentityAwareJobRunner):
    def __init__(self, *, exists: bool = False, conflict_on_schedule: bool = False) -> None:
        self._exists = exists
        self._conflict = conflict_on_schedule
        self.scheduled: list[ScheduledRun] = []
        self.stopped: list[str] = []

    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
        identity: Mapping[str, str] | None = None,
        # Accepted so this fake still satisfies the port, and deliberately NOT recorded onto
        # `ScheduledRun`: that tuple is compared whole by an existing test, so widening it would
        # change what an already-written assertion means. A test that needs to observe the policy
        # subclasses this and records it there.
        cache: CachePolicy | None = None,
    ) -> str:
        if self._conflict:
            raise JobAlreadyExists(topic)
        self.scheduled.append(
            ScheduledRun(topic, url4, deadline_s, traceparent, credential, profile, identity)
        )
        return job_name(topic)

    async def stop(self, topic: str) -> None:
        self.stopped.append(topic)

    async def exists(self, topic: str) -> bool:
        return self._exists

    async def status(self, topic: str) -> JobStatus:
        return "running"


class FixedGate:
    def __init__(self, present: bool = True) -> None:
        self._present = present

    async def has_subscriber(self, topic: str) -> bool:
        return self._present


class MockExecutor(Executor):
    def _cost(self, scope: Literal["self", "subtree"]) -> CostUsageData:
        return CostUsageData(
            scope=scope,
            provider="anthropic",
            model="claude-opus-4-8",
            pricing_version="2026-07-01",
            usage=TokenUsage(input_tokens=1200, output_tokens=340),
            cost=CostBreakdown(
                input_usd=Decimal("0.0180"),
                output_usd=Decimal("0.0255"),
                total_usd=Decimal("0.0435"),
            ),
        )

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        yield LogData(severity_number=9, severity_text="INFO", body=f"executing {url4}")
        yield SpanData(
            name="chat",
            operation="chat",
            provider="anthropic",
            request_model="claude-opus-4-8",
            response_model="claude-opus-4-8",
            input_tokens=1200,
            output_tokens=340,
            start=datetime.now(UTC),
            end=datetime.now(UTC),
        )
        yield self._cost("self")
        yield Completed(
            result=ResultData(body="[mock] done", media_type="text/plain"),
            subtree_cost=self._cost("subtree"),
        )


__all__ = [
    "STREAM_FACTORIES",
    "TAKE_TIMEOUT_S",
    "FixedGate",
    "MockExecutor",
    "RecordingJobRunner",
    "ScheduledRun",
    "take",
]

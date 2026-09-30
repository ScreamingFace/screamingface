"""A broker failure inside `QueueJobRunner.schedule()` is a retryable 503, never a naked 500.

FEATURE: an honest, retryable answer when the run queue is down (residual gap of OME-948 R5,
under OME-1086).

WHY this file exists: `JobRunnerAtCapacity` (a FULL queue) was mapped to 503 by OME-1091, but a
queue that cannot be REACHED was not mapped at all. Both broker calls on the schedule path —
the admission depth read (`RunQueue.depth`, a raw `STREAM.INFO` request) and the durable
publish (`RunQueue.publish`) — raise `nats.errors.Error` on a timeout, a closed connection or
a reconnect in flight. Nothing caught it, so the client got Starlette's plain-text 500: an
answer that says "the server is broken", which a well-behaved client does not retry, for a
condition an identical retry seconds later usually cures.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import nats.errors
import nats.js.errors
import pytest
from httpx import ASGITransport

from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueueUnavailable
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import JobRunnerAtCapacity

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)
SECRET = "broker-failure-secret-0123456789abcdef"
WINDOW_S = 60
LIFETIME_S = 58_800
CALLER: Mapping[str, str] = {"X-User-Email": "a@example.com"}


class _FailingQueue:
    """The slice of `RunQueue` the runner uses; each call can be told to raise."""

    def __init__(
        self,
        *,
        publish_error: BaseException | None = None,
        depth_error: BaseException | None = None,
        depth: int = 0,
    ) -> None:
        self.publish_error = publish_error
        self.depth_error = depth_error
        self._depth = depth
        self.published: list[bytes] = []

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        if self.publish_error is not None:
            raise self.publish_error
        self.published.append(message)

    async def depth(self) -> int:
        if self.depth_error is not None:
            raise self.depth_error
        return self._depth

    async def oldest_age(self) -> float | None:
        return None


class _Publisher:
    async def last_frame(self, topic: str) -> Any:
        return None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _Control:
    async def request(self, subject: str, payload: bytes, *, timeout: float) -> Any:
        raise TimeoutError()


def _runner(queue: _FailingQueue, *, caller_inflight_cap: int = 8, depth_ceiling: int = 10):
    return QueueJobRunner(
        queue=queue,
        publisher=_Publisher(),
        control=_Control(),
        clock=lambda: T0,
        capability_lifetime_s=LIFETIME_S,
        caller_inflight_cap=caller_inflight_cap,
        depth_ceiling=depth_ceiling,
        # Every schedule re-reads the depth, so a depth failure is not hidden by the cache.
        state_cache_ttl_s=0.0,
    )


# --- the adapter translates -------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [nats.errors.TimeoutError(), nats.errors.ConnectionClosedError(), nats.errors.NoServersError()],
    ids=["timeout", "closed", "no-servers"],
)
async def test_a_publish_broker_failure_raises_run_queue_unavailable(error: Exception) -> None:
    runner = _runner(_FailingQueue(publish_error=error))

    with pytest.raises(RunQueueUnavailable) as exc:
        await runner.schedule("t", "'hi'", 60, identity=CALLER)

    # INVARIANT: the broker's own error stays reachable for the operator's traceback.
    assert exc.value.__cause__ is error


async def test_an_admission_read_broker_failure_raises_run_queue_unavailable() -> None:
    queue = _FailingQueue(depth_error=nats.errors.ConnectionClosedError())
    runner = _runner(queue)

    with pytest.raises(RunQueueUnavailable):
        await runner.schedule("t", "'hi'", 60, identity=CALLER)

    assert queue.published == []


async def test_a_failed_publish_releases_the_reservation_it_made() -> None:
    """INVARIANT: the translation must not skip the release. At cap 1, a leaked reservation
    would refuse this caller's NEXT run for a run that was never queued."""
    queue = _FailingQueue(publish_error=nats.errors.TimeoutError())
    runner = _runner(queue, caller_inflight_cap=1)

    with pytest.raises(RunQueueUnavailable):
        await runner.schedule("t1", "'hi'", 60, identity=CALLER)
    queue.publish_error = None
    await runner.schedule("t2", "'hi'", 60, identity=CALLER)

    assert len(queue.published) == 1


async def test_a_capacity_refusal_is_not_relabelled_as_unavailable() -> None:
    """A FULL queue and an UNREACHABLE one are different answers with different `Retry-After`
    sources; the translation covers only the broker's own errors."""
    runner = _runner(_FailingQueue(depth=10), depth_ceiling=10)

    with pytest.raises(JobRunnerAtCapacity):
        await runner.schedule("t", "'hi'", 60, identity=CALLER)


async def test_a_failed_publish_leaves_no_accepted_record() -> None:
    """A run that was never durably queued must not read `scheduled` afterwards."""
    runner = _runner(_FailingQueue(publish_error=nats.errors.TimeoutError()))

    with pytest.raises(RunQueueUnavailable):
        await runner.schedule("t", "'hi'", 60, identity=CALLER)

    assert await runner.status("t") == "not_found"


# --- the REST edge maps -----------------------------------------------------------------------


class _Gate:
    async def has_subscriber(self, topic: str) -> bool:
        return True


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


@pytest.mark.parametrize(
    "queue",
    [
        _FailingQueue(publish_error=nats.errors.TimeoutError()),
        _FailingQueue(depth_error=nats.errors.ConnectionClosedError()),
    ],
    ids=["publish", "admission-read"],
)
async def test_the_rest_edge_answers_a_retryable_503_problem(queue: _FailingQueue) -> None:
    app = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=_runner(queue),
        clock=lambda: T0,
        interest=_Gate(),
    )
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/",
            params={"q": "gpt()"},
            headers={"URL4-Capability": _token("topic-down"), "Prefer": "respond-async"},
        )

    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.headers["Retry-After"] == "5"
    body = resp.json()
    assert body["status"] == 503
    assert body["title"] == "Service Unavailable"
    # INVARIANT: generic — no broker vocabulary reaches the client.
    assert body["detail"] == "the run queue is unavailable — retry shortly"
    for internal in ("nats", "jetstream", "stream", "timeout"):
        assert internal not in body["detail"].lower()


# --- only AVAILABILITY failures are retryable (design review) ---------------------------------


@pytest.mark.parametrize(
    "error",
    [
        nats.js.errors.ServiceUnavailableError(),
        nats.errors.NoRespondersError(),
        nats.errors.StaleConnectionError(),
        nats.errors.ConnectionReconnectingError(),
    ],
    ids=["js-503", "no-responders", "stale", "reconnecting"],
)
async def test_every_availability_failure_is_retryable(error: Exception) -> None:
    runner = _runner(_FailingQueue(publish_error=error))

    with pytest.raises(RunQueueUnavailable):
        await runner.schedule("t", "'hi'", 60, identity=CALLER)


@pytest.mark.parametrize(
    "error",
    [
        nats.errors.MaxPayloadError(),
        nats.errors.BadSubjectError(),
        # The stream-config conflict `RunQueue.ensure_stream` re-raises ON PURPOSE.
        nats.js.errors.BadRequestError(),
    ],
    ids=["max-payload", "bad-subject", "config-conflict"],
)
async def test_a_non_retryable_broker_error_is_not_relabelled_as_retry_shortly(
    error: Exception,
) -> None:
    """INVARIANT: "retry shortly" must be TRUE. A payload too large, a bad subject or a stream
    config conflict fails identically on every retry — it stays the 500 it is, so an operator
    sees a defect instead of a client retrying into it. The reservation is still released."""
    queue = _FailingQueue(publish_error=error)
    runner = _runner(queue, caller_inflight_cap=1)

    with pytest.raises(type(error)):
        await runner.schedule("t1", "'hi'", 60, identity=CALLER)
    queue.publish_error = None
    await runner.schedule("t2", "'hi'", 60, identity=CALLER)


async def test_a_non_retryable_broker_error_answers_500_at_the_edge() -> None:
    app = create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=_runner(_FailingQueue(publish_error=nats.errors.MaxPayloadError())),
        clock=lambda: T0,
        interest=_Gate(),
    )
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/",
            params={"q": "gpt()"},
            headers={"URL4-Capability": _token("topic-bad"), "Prefer": "respond-async"},
        )

    assert resp.status_code == 500

"""Sync `GET /?q=` without a WebSocket (uniform executor, PRD 02).

A sync request HOLDS its topic's interest while it waits, so the 428 gate passes and the orphan
reaper does not arm. The hold ends on the terminal frame, on the bound, on a client disconnect,
and on an error. `respond-async` keeps the 428 rule (the client reads the frames on a WS).

The App under test uses the REAL `ConnectionRegistry` (no substituted gate): the registry is
both the gate and the audience source the reaper listens to.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.ws.registry import ConnectionRegistry
from url4.streaming.interfaces import JobRunnerAtCapacity
from url4.streaming.protocol import (
    OutboundFrame,
    ResultData,
    ResultEvent,
    TerminatedData,
    TerminatedEvent,
)

pytestmark = pytest.mark.asyncio

SECRET = "rest-sync-hold-secret"
WINDOW_S = 60
T0 = datetime(2026, 9, 25, 9, 0, 0, tzinfo=UTC)


def _cap(topic: str) -> dict[str, str]:
    codec = JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=58_800)
    return {"URL4-Capability": codec.sign(topic, T0)}


class _Audience:
    """Records the registry's audience transitions (what the orphan reaper reacts to)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def audience_arrived(self, topic: str) -> None:
        self.events.append(("arrived", topic))

    def audience_left(self, topic: str) -> None:
        self.events.append(("left", topic))


def _app(
    *,
    stream: Any = None,
    runner: RecordingJobRunner | None = None,
    sync_max_wait_s: float = 5.0,
    record: bool = True,
) -> tuple[FastAPI, ConnectionRegistry, _Audience]:
    """`record=True` makes an `_Audience` recorder the registry's listener — IN PLACE OF the
    orphan reaper (the registry has one listener). Tests that watch the reaper pass False."""
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, sync_max_wait_s=sync_max_wait_s)
    app = create_app(
        settings,
        stream=stream if stream is not None else InMemoryEventStream(),
        job_runner=runner or RecordingJobRunner(),
        clock=lambda: T0,
    )
    registry: ConnectionRegistry = app.state.registry
    audience = _Audience()
    if record:
        registry.listen(audience)
    return app, registry, audience


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _terminated(topic: str, status: str = "succeeded") -> TerminatedEvent:
    return TerminatedEvent(
        id=f"term-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=TerminatedData(status=status),  # type: ignore[arg-type]
    )


def _result(topic: str, body: str) -> ResultEvent:
    return ResultEvent(
        id=f"res-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=ResultData(body=body, media_type="application/json"),
    )


async def _wait_until(predicate: Any, timeout: float = 2.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout)


async def test_sync_request_without_ws_returns_200() -> None:
    """SYN-1 / SY-H1."""
    topic = "sync-no-ws"
    stream = InMemoryEventStream()
    await stream.publish(topic, _result(topic, '{"answer": 42}'))
    await stream.publish(topic, _terminated(topic))
    runner = RecordingJobRunner()
    app, registry, _ = _app(stream=stream, runner=runner)
    async with _client(app) as client:
        resp = await client.get("/", params={"q": "gpt()"}, headers=_cap(topic))
    assert resp.status_code == 200
    assert resp.json() == {"answer": 42}
    assert [run[0] for run in runner.scheduled] == [topic]
    assert registry.sync_holders == 0


async def test_reaper_does_not_arm_while_sync_holder_waits() -> None:
    """SYN-2 / SY-D1: during the wait the audience ARRIVED and never LEFT, so the reaper
    (which arms on `audience_left`) has nothing to arm."""
    topic = "sync-long"
    stream = InMemoryEventStream()
    app, registry, audience = _app(stream=stream)
    async with _client(app) as client:
        request = asyncio.ensure_future(
            client.get("/", params={"q": "slow()"}, headers=_cap(topic))
        )
        await _wait_until(lambda: registry.sync_holders == 1)
        assert audience.events == [("arrived", topic)]
        assert await registry.has_subscriber(topic)
        await stream.publish(topic, _terminated(topic))
        resp = await request
    assert resp.status_code == 200
    assert audience.events == [("arrived", topic), ("left", topic)]


async def test_bound_elapsed_releases_hold_and_arms_reaper() -> None:
    """SYN-3 / SY-D2: 202 at the bound, the hold is gone, and `audience_left` fires once — the
    reaper's grace starts, so a client may still attach a WebSocket."""
    topic = "sync-bound"
    app, registry, _ = _app(sync_max_wait_s=0.1, record=False)
    async with _client(app) as client:
        resp = await client.get("/", params={"q": "slow()"}, headers=_cap(topic))
    assert resp.status_code == 202
    assert resp.headers["location"] == f"/?topic={topic}"
    assert registry.sync_holders == 0
    assert app.state.reaper is not None
    assert topic in app.state.reaper._deadlines  # noqa: SLF001 - the armed grace is the behavior


async def test_client_disconnect_releases_hold_within_1s() -> None:
    """SYN-4 / SY-D3: the client closes the connection mid-wait; the App stops waiting and
    releases the hold within 1 s. The run itself is NOT stopped (the token can still attach)."""
    topic = "sync-gone"
    runner = RecordingJobRunner()
    app, registry, audience = _app(runner=runner, sync_max_wait_s=30.0)
    disconnect = asyncio.Event()
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if not sent:
            sent.append({})
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    token = _cap(topic)["URL4-Capability"]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"q=slow()",
        "root_path": "",
        "headers": [(b"host", b"test"), (b"url4-capability", token.encode())],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    call = asyncio.ensure_future(app(scope, receive, send))  # type: ignore[arg-type]
    await _wait_until(lambda: registry.sync_holders == 1)
    disconnect.set()
    await asyncio.wait_for(call, timeout=1.0)
    assert registry.sync_holders == 0
    assert audience.events == [("arrived", topic), ("left", topic)]
    assert runner.stopped == []


async def test_audience_left_waits_for_both_ws_and_sync_to_leave() -> None:
    """SYN-5 / SY-D4."""
    registry = ConnectionRegistry()
    audience = _Audience()
    registry.listen(audience)
    registry.add("t")
    async with registry.hold_sync("t"):
        assert registry.sync_holders == 1
    assert audience.events == [("arrived", "t")]
    assert await registry.has_subscriber("t")
    registry.remove("t")
    assert audience.events == [("arrived", "t"), ("left", "t")]


async def test_a_sync_hold_alone_makes_the_topic_subscribed() -> None:
    registry = ConnectionRegistry()
    assert not await registry.has_subscriber("t")
    async with registry.hold_sync("t"):
        assert await registry.has_subscriber("t")
    assert not await registry.has_subscriber("t")


async def test_hold_released_when_wait_raises() -> None:
    """SYN-6 / SY-D6: an exception inside the wait still releases the hold."""
    topic = "sync-boom"

    class _BrokenStream(InMemoryEventStream):
        async def subscribe(  # type: ignore[override]
            self, topic: str, from_sequence: int | None = None
        ) -> AsyncIterator[OutboundFrame]:
            raise RuntimeError("stream broke")
            yield  # pragma: no cover

    app, registry, audience = _app(stream=_BrokenStream())
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/", params={"q": "gpt()"}, headers=_cap(topic))
    assert resp.status_code == 500
    assert registry.sync_holders == 0
    assert audience.events == [("arrived", topic), ("left", topic)]


async def test_admission_503_leaves_hold_count_unchanged() -> None:
    """SYN-7 / SY-D7."""

    class _Full(RecordingJobRunner):
        async def schedule(self, *args: Any, **kwargs: Any) -> str:
            raise JobRunnerAtCapacity(8, 8, retry_after_s=30)

    app, registry, _ = _app(runner=_Full())
    async with _client(app) as client:
        resp = await client.get("/", params={"q": "gpt()"}, headers=_cap("sync-full"))
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "30"
    assert registry.sync_holders == 0


async def test_duplicate_topic_409_takes_no_hold() -> None:
    """SYN-8 / SY-D5: the conflict is decided BEFORE the hold, so a duplicate request never
    touches the topic's audience (which would reset an armed reaper's grace)."""
    app, registry, audience = _app(runner=RecordingJobRunner(exists=True))
    async with _client(app) as client:
        resp = await client.get("/", params={"q": "gpt()"}, headers=_cap("sync-dup"))
    assert resp.status_code == 409
    assert audience.events == []
    assert registry.sync_holders == 0


async def test_sync_holders_gauge_tracks_holds() -> None:
    """SYN-9."""
    topic = "sync-gauge"
    stream = InMemoryEventStream()
    app, registry, _ = _app(stream=stream)
    async with _client(app) as client:
        request = asyncio.ensure_future(
            client.get("/", params={"q": "slow()"}, headers=_cap(topic))
        )
        await _wait_until(lambda: registry.sync_holders == 1)
        during = (await client.get("/metrics")).text
        await stream.publish(topic, _terminated(topic))
        await request
        after = (await client.get("/metrics")).text
    assert "screamingface_engine_sync_holders 1.0" in during
    assert "screamingface_engine_sync_holders 0.0" in after


async def test_bad_token_401_takes_no_hold() -> None:
    """SYN-11 / SY-E3."""
    app, registry, audience = _app()
    async with _client(app) as client:
        resp = await client.get(
            "/", params={"q": "gpt()"}, headers={"URL4-Capability": "not-a-token"}
        )
    assert resp.status_code == 401
    assert audience.events == []
    assert registry.sync_holders == 0

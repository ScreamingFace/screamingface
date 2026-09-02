"""The queue-position notice (OME-1090): a queued run's position reaches the attached
socket through the WS bridge's existing `add_notifier` path, and is superseded once
`StartedEvent` arrives.

No protocol change and no stream write: the notice is a `LogEvent` offered to the topic's
registered notifiers, exactly like the cache-override notice — the client is already
attached while its run is queued, so the wait is visible instead of silent.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.ports import IdentityAwareJobRunner
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import JobStatus, job_name
from url4.streaming.protocol import (
    AttachData,
    AttachEvent,
    CachePolicy,
    OutboundFrameAdapter,
    StartedData,
    StartedEvent,
    source_for,
)

SECRET = "notice-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 9, 2, 9, 0, 0, tzinfo=UTC)
SUBPROTOCOL = "cloudevents.json"


class _QueueAwareRunner(IdentityAwareJobRunner):
    """A fake queue-backed runner: records schedules, reports a queue depth, and lets the
    test publish the run's own frames onto the stream."""

    def __init__(self, stream: InMemoryEventStream, *, depth: int = 3) -> None:
        self._stream = stream
        self._depth = depth
        self.scheduled: list[tuple[str, str, int]] = []

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
        cache: CachePolicy | None = None,
    ) -> str:
        self.scheduled.append((topic, url4, deadline_s))
        return job_name(topic)

    async def stop(self, topic: str) -> None:
        pass

    async def exists(self, topic: str) -> bool:
        return False

    async def status(self, topic: str) -> JobStatus:
        return "scheduled"

    async def queue_depth(self) -> int:
        return self._depth


def _make_app(stream: InMemoryEventStream, runner: _QueueAwareRunner) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, ws_heartbeat_s=30.0)
    return create_app(settings, stream=stream, job_runner=runner, clock=lambda: T0)


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


def _attach() -> dict[str, Any]:
    return AttachEvent(
        id="att", source="/client", subject="t", data=AttachData(from_sequence=None)
    ).model_dump(mode="json", by_alias=True)


def test_the_queue_position_notice_reaches_the_attached_socket_and_is_superseded() -> None:
    stream = InMemoryEventStream()
    runner = _QueueAwareRunner(stream, depth=3)
    app = _make_app(stream, runner)
    topic = "topic-notice"
    with TestClient(app) as client:
        token = _token(topic)
        cap = {"URL4-Capability": token}
        with client.websocket_connect(f"/ws?ticket={token}", subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach())
            started = client.get(
                "/", params={"q": "'hi'"}, headers={**cap, "Prefer": "respond-async"}
            )
            assert started.status_code == 202
            assert runner.scheduled and runner.scheduled[0][0] == topic

            # The notice arrives first: a log frame naming the queue position.
            notice = OutboundFrameAdapter.validate_python(ws.receive_json())
            assert notice.type == "ai.url4.log"
            assert "position 3" in notice.data.body

            # Superseded: the run starts, and the client sees the StartedEvent.
            portal = client.portal
            assert portal is not None
            portal.call(
                stream.publish,
                topic,
                StartedEvent(
                    id="s",
                    source=source_for(topic),
                    subject=topic,
                    time=T0,
                    data=StartedData(url4="'hi'"),
                ),
            )
            started_frame = OutboundFrameAdapter.validate_python(ws.receive_json())
            assert started_frame.type == "ai.url4.started"

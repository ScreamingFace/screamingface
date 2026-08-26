from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.rest import DenyAllGate
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.ws import ConnectionRegistry
from url4.streaming.protocol import (
    AttachData,
    AttachEvent,
    CostBreakdown,
    CostUsageData,
    CostUsageEvent,
    OutboundFrame,
    StartedData,
    StartedEvent,
    StopData,
    StopEvent,
    TerminatedData,
    TerminatedEvent,
    TokenUsage,
)

SECRET = "ws-unit-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
SUBPROTOCOL = "cloudevents.json"
T0 = datetime(2026, 7, 21, 9, 0, 0, tzinfo=UTC)


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(topic, T0)


def _make_app(
    *,
    stream: InMemoryEventStream | None,
    job_runner: RecordingJobRunner | None = None,
    ws_heartbeat_s: float = 30.0,
) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, ws_heartbeat_s=ws_heartbeat_s)
    return create_app(
        settings,
        stream=stream,
        job_runner=job_runner or RecordingJobRunner(),
        clock=lambda: T0,
    )


def _seed(
    client: TestClient, stream: InMemoryEventStream, topic: str, events: list[OutboundFrame]
) -> None:
    portal = client.portal
    assert portal is not None
    for event in events:
        portal.call(stream.publish, topic, event)


def _attach(from_sequence: int | None) -> dict[str, Any]:
    event = AttachEvent(
        id="att", source="/client", subject="t", data=AttachData(from_sequence=from_sequence)
    )
    return event.model_dump(mode="json", by_alias=True)


def _stop() -> dict[str, Any]:
    return StopEvent(id="stp", source="/client", subject="t", data=StopData()).model_dump(
        mode="json", by_alias=True
    )


def _started(topic: str) -> StartedEvent:
    return StartedEvent(
        id=f"s-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=StartedData(url4="gpt()"),
    )


def _cost(topic: str) -> CostUsageEvent:
    return CostUsageEvent(
        id=f"c-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=CostUsageData(
            scope="self",
            provider="anthropic",
            model="claude-opus-4-8",
            pricing_version="2026-07-01",
            usage=TokenUsage(input_tokens=1200, output_tokens=340),
            cost=CostBreakdown(
                input_usd=Decimal("0.0180"),
                output_usd=Decimal("0.0255"),
                total_usd=Decimal("0.0435"),
            ),
        ),
    )


def _terminated(topic: str) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"t-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=TerminatedData(status="succeeded"),
    )


def test_ws_streams_published_events_in_order_as_cloudevents_json() -> None:
    topic = "ws-order"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic), _cost(topic), _terminated(topic)])
        url = f"/ws?ticket={_token(topic)}"
        with client.websocket_connect(url, subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach(None))
            frames = [ws.receive_json() for _ in range(3)]
    types = [f["type"] for f in frames]
    assert types == ["ai.url4.started", "ai.url4.cost.usage", "ai.url4.terminated"]
    assert [f["sequence"] for f in frames] == ["1", "2", "3"]
    assert all(f["specversion"] == "1.0" for f in frames)
    assert frames[1]["data"]["gen_ai.provider.name"] == "anthropic"
    assert frames[1]["data"]["cost"]["total_usd"] == "0.0435"


def test_ws_attach_from_sequence_replays_the_gap() -> None:
    topic = "ws-resume"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic), _cost(topic), _terminated(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(2))
            frames = [ws.receive_json() for _ in range(2)]
    assert [f["sequence"] for f in frames] == ["2", "3"]
    assert [f["type"] for f in frames] == ["ai.url4.cost.usage", "ai.url4.terminated"]


def test_ws_heartbeat_on_idle_connection() -> None:
    topic = "ws-heartbeat"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream, ws_heartbeat_s=0.05)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            frame = ws.receive_json()
    assert frame["type"] == "ai.url4.heartbeat"
    assert frame["subject"] == topic


def test_ws_stop_event_stops_the_job() -> None:
    topic = "ws-stop"
    stream = InMemoryEventStream()
    runner = RecordingJobRunner()
    app = _make_app(stream=stream, job_runner=runner, ws_heartbeat_s=0.05)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_stop())
            assert ws.receive_json()["type"] == "ai.url4.heartbeat"
    assert runner.stopped == [topic]


def test_ws_reattach_cancels_prior_subscription_and_replays() -> None:
    topic = "ws-reattach"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(None))
            first = ws.receive_json()
            ws.send_json(_attach(1))
            second = ws.receive_json()
    assert first["sequence"] == "1"
    assert second["sequence"] == "1"
    assert second["type"] == "ai.url4.started"


def test_ws_malformed_inbound_frames_nacked_stream_survives() -> None:
    topic = "ws-malformed"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream, ws_heartbeat_s=0.05)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_text("this is not json {{{")
            ws.send_json({"type": "ai.url4.bogus", "id": "x", "source": "/c"})
            first = ws.receive_json()
            second = ws.receive_json()
            beat = ws.receive_json()
    assert first["type"] == "ai.url4.error" and first["data"]["code"] == "invalid_frame"
    assert second["type"] == "ai.url4.error" and second["data"]["code"] == "invalid_frame"
    assert beat["type"] == "ai.url4.heartbeat"


def test_ws_unparseable_frame_yields_invalid_frame_nack_and_survives() -> None:
    topic = "ws-nack-parse"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream, ws_heartbeat_s=0.05)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_text("{not json")
            nack = ws.receive_json()
            beat = ws.receive_json()
    assert nack["type"] == "ai.url4.error"
    assert nack["data"]["code"] == "invalid_frame"
    assert nack["data"]["ref_id"] is None
    assert beat["type"] == "ai.url4.heartbeat"


def test_ws_stop_without_runner_yields_unsupported_nack() -> None:
    topic = "ws-nack-stop"
    stream = InMemoryEventStream()
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, ws_heartbeat_s=0.05)
    app = create_app(settings, stream=stream, job_runner=None, clock=lambda: T0)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_stop())
            nack = ws.receive_json()
    assert nack["type"] == "ai.url4.error"
    assert nack["data"]["code"] == "unsupported"
    assert nack["data"]["ref_id"] == "stp"


def test_ws_invalid_ticket_is_rejected() -> None:
    app = _make_app(stream=InMemoryEventStream())
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?ticket=not-a-jwt") as ws:
                ws.receive_json()


def test_ws_missing_ticket_is_rejected() -> None:
    app = _make_app(stream=InMemoryEventStream())
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()


def test_ws_without_bus_is_rejected() -> None:
    app = _make_app(stream=None)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws?ticket={_token('no-stream')}") as ws:
                ws.receive_json()


def test_live_ws_enables_start_and_closing_it_restores_428() -> None:
    topic = "ws-gate"
    stream = InMemoryEventStream()
    runner = RecordingJobRunner()
    app = _make_app(stream=stream, job_runner=runner)
    headers = {"URL4-Capability": _token(topic)}
    with TestClient(app) as client:
        before = client.get("/", params={"q": "gpt()"}, headers=headers)
        assert before.status_code == 428
        url = f"/ws?ticket={_token(topic)}"
        with client.websocket_connect(url, subprotocols=[SUBPROTOCOL]) as ws:
            ws.send_json(_attach(None))
            during = client.get(
                "/", params={"q": "gpt()"}, headers={**headers, "Prefer": "respond-async"}
            )
        assert during.status_code == 202
        after = client.get("/", params={"q": "gpt()"}, headers=headers)
    assert after.status_code == 428
    assert runner.scheduled and runner.scheduled[0][0] == topic


@pytest.mark.asyncio
async def test_connection_registry_counts_live_subscribers() -> None:
    registry = ConnectionRegistry()
    assert await registry.has_subscriber("t") is False
    registry.add("t")
    registry.add("t")
    assert await registry.has_subscriber("t") is True
    registry.remove("t")
    assert await registry.has_subscriber("t") is True
    registry.remove("t")
    assert await registry.has_subscriber("t") is False
    registry.remove("t")
    assert await registry.has_subscriber("t") is False


@pytest.mark.asyncio
async def test_deny_all_gate_reports_no_subscriber() -> None:
    assert await DenyAllGate().has_subscriber("anything") is False

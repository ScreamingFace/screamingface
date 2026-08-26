"""What the App records about a WebSocket that ended, and why it records it.

A dropped Run stream reaches the researcher as one undifferentiated message. The close
code is what separates the causes, and only the App observes it — a client cannot report
a close it never received. These pin the record that makes a drop attributable.

Self-contained by design (sdlc rule 5): builds its own app rather than reaching into the
shared WS test module.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.protocol import (
    AttachData,
    AttachEvent,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
)

SECRET = "ws-diagnostics-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
SUBPROTOCOL = "cloudevents.json"
TOPIC = "topic-diag"
T0 = datetime(2026, 8, 13, 9, 0, 0, tzinfo=UTC)


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


def _app(stream: InMemoryEventStream | None, *, heartbeat_s: float = 30.0) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S, ws_heartbeat_s=heartbeat_s)
    return create_app(settings, stream=stream, job_runner=None, clock=lambda: T0)


def _attach() -> dict[str, Any]:
    return AttachEvent(
        id="att", source="/client", subject=TOPIC, data=AttachData(from_sequence=None)
    ).model_dump(mode="json", by_alias=True)


def _seed(client: TestClient, stream: InMemoryEventStream) -> None:
    portal = client.portal
    assert portal is not None
    for event in (
        StartedEvent(
            id="s1",
            source=f"/trace/{TOPIC}/node/root",
            subject=TOPIC,
            data=StartedData(url4="gpt()"),
        ),
        TerminatedEvent(
            id="t1",
            source=f"/trace/{TOPIC}/node/root",
            subject=TOPIC,
            data=TerminatedData(status="succeeded"),
        ),
    ):
        portal.call(stream.publish, TOPIC, event)


def test_a_finished_stream_records_how_it_ended_and_what_it_carried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # STORY: as the engineer reading back a failure, the App tells me the shape of the
    # connection — how long it lived, whether it was carrying work or idling, and the
    # close code. Without those, every cause of a drop is the same log line: none.
    stream = InMemoryEventStream()
    with caplog.at_level(logging.INFO, logger="screamingface_engine.ws.bridge"):
        with TestClient(_app(stream)) as client:
            with client.websocket_connect(
                f"/ws?ticket={_token(TOPIC)}", subprotocols=[SUBPROTOCOL]
            ) as websocket:
                websocket.send_json(_attach())
                _seed(client, stream)
                websocket.receive_json()
                websocket.receive_json()

    ended = [record for record in caplog.records if "ws stream ended" in record.getMessage()]
    assert len(ended) == 1
    message = ended[0].getMessage()
    assert f"topic={TOPIC}" in message
    assert "frames=2" in message
    assert "heartbeats=0" in message
    assert "duration_s=" in message


def test_an_attach_records_the_cursor_it_resumed_from(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A re-attach is the client telling us it lost frames. Recording the cursor is what
    # distinguishes a clean first attach from a stream that is being repaired.
    stream = InMemoryEventStream()
    with caplog.at_level(logging.INFO, logger="screamingface_engine.ws.bridge"):
        with TestClient(_app(stream)) as client:
            with client.websocket_connect(
                f"/ws?ticket={_token(TOPIC)}", subprotocols=[SUBPROTOCOL]
            ) as websocket:
                websocket.send_json(_attach())
                _seed(client, stream)
                websocket.receive_json()

    attaches = [record for record in caplog.records if "ws attach" in record.getMessage()]
    assert [record.getMessage() for record in attaches] == [
        f"ws attach topic={TOPIC} from_sequence=None"
    ]


def test_a_refused_handshake_is_recorded_rather_than_silently_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # STORY: as the engineer on call, a burst of refusals is visible. A capability whose
    # window elapsed before the client could connect is otherwise invisible here — the
    # client only ever sees a refused handshake with no reason attached.
    with caplog.at_level(logging.INFO, logger="screamingface_engine.ws.endpoint"):
        with TestClient(_app(InMemoryEventStream())) as client:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(
                    "/ws?ticket=not-a-real-capability", subprotocols=[SUBPROTOCOL]
                ) as websocket:
                    websocket.receive_json()

    refused = [record for record in caplog.records if "ws rejected" in record.getMessage()]
    assert [record.getMessage() for record in refused] == ["ws rejected reason=unverifiable ticket"]

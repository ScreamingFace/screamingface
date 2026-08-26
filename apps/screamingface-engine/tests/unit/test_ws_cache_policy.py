"""Batch 4 — the WS carrier: an attach frame's cache intent becomes the topic's session state.

FIRST ATTACH WINS (spec §5.2). The run's aigateway calls may already have executed under the
policy the first attach declared, so a later re-attach that says something different cannot be
allowed to restate it — the run's cache behaviour would stop being reproducible. It is ignored and
said out loud, at `warn`, on the socket that sent it.

The barrier every socket test here uses is a SEEDED STREAM EVENT rather than a heartbeat: the
declaration is recorded before the subscription is (re)started, so receiving a pumped frame proves
the declaration already landed, and a warning — queued before that same subscription — would
always arrive first. That makes "no warning was emitted" an assertion about frame ORDER rather
than about elapsed time, so it cannot flake.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from _fakes import RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.ws import ConnectionRegistry
from url4.streaming.protocol import (
    AttachData,
    AttachEvent,
    CachePolicy,
    OutboundFrame,
    StartedData,
    StartedEvent,
)

SECRET = "ws-cache-policy-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)

OPT_OUT = CachePolicy(participate=False)
OPT_IN = CachePolicy(participate=True)


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


def _make_app(*, stream: InMemoryEventStream) -> FastAPI:
    settings = Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S)
    return create_app(settings, stream=stream, job_runner=RecordingJobRunner(), clock=lambda: T0)


def _seed(
    client: TestClient, stream: InMemoryEventStream, topic: str, events: list[OutboundFrame]
) -> None:
    portal = client.portal
    assert portal is not None
    for event in events:
        portal.call(stream.publish, topic, event)


def _started(topic: str) -> StartedEvent:
    return StartedEvent(
        id=f"s-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=StartedData(url4="gpt()"),
    )


def _attach(
    *, cache: CachePolicy | None = None, from_sequence: int | None = None
) -> dict[str, Any]:
    event = AttachEvent(
        id="att",
        source="/client",
        subject="t",
        data=AttachData(from_sequence=from_sequence, cache=cache),
    )
    return event.model_dump(mode="json", by_alias=True)


def _attach_without_cache_key(from_sequence: int | None = None) -> dict[str, Any]:
    """An attach frame with no `cache` key AT ALL — what every client in flight already sends."""
    frame = _attach(from_sequence=from_sequence)
    del frame["data"]["cache"]
    return frame


# --- the registry, directly -------------------------------------------------------------------


def test_registry_records_the_first_declaration_and_ignores_a_later_conflicting_one() -> None:
    registry = ConnectionRegistry()
    registry.add("t")
    assert registry.declare_cache_policy("t", OPT_OUT) is True
    assert registry.cache_policy_for("t") == OPT_OUT
    assert registry.declare_cache_policy("t", OPT_IN) is False
    assert registry.cache_policy_for("t") == OPT_OUT


def test_registry_accepts_a_restatement_of_the_standing_policy() -> None:
    registry = ConnectionRegistry()
    registry.add("t")
    registry.declare_cache_policy("t", OPT_OUT)
    # A reconnecting client re-sends the frame it sent the first time. That is not a conflict, and
    # reporting it as one would make every ordinary reconnect emit a warning nobody can act on.
    assert registry.declare_cache_policy("t", CachePolicy(participate=False)) is True
    assert registry.cache_policy_for("t") == OPT_OUT


def test_registry_treats_declaring_nothing_as_the_first_declaration() -> None:
    registry = ConnectionRegistry()
    registry.add("t")
    # "Did not declare" IS a declaration for first-attach-wins purposes: the run starts under the
    # ON default, and a later attach cannot retroactively opt that run out.
    assert registry.declare_cache_policy("t", None) is True
    assert registry.declare_cache_policy("t", OPT_OUT) is False
    assert registry.cache_policy_for("t") is None


def test_registry_forgets_the_declaration_when_the_last_subscriber_leaves() -> None:
    registry = ConnectionRegistry()
    registry.add("t")
    registry.add("t")
    registry.declare_cache_policy("t", OPT_OUT)
    registry.remove("t")
    assert registry.cache_policy_for("t") == OPT_OUT
    registry.remove("t")
    assert registry.cache_policy_for("t") is None


def test_registry_reports_no_policy_for_an_unknown_topic() -> None:
    assert ConnectionRegistry().cache_policy_for("never-seen") is None


def test_registry_declaration_without_a_subscriber_does_not_outlive_a_remove() -> None:
    registry = ConnectionRegistry()
    assert registry.declare_cache_policy("t", OPT_OUT) is True
    registry.remove("t")
    assert registry.cache_policy_for("t") is None


@pytest.mark.asyncio
async def test_registry_declaration_does_not_make_a_topic_look_subscribed() -> None:
    registry = ConnectionRegistry()
    registry.declare_cache_policy("t", OPT_OUT)
    # The 428 precondition asks about SUBSCRIBERS. A declaration is not one, and letting it pass
    # for one would start a run with nothing attached to observe its terminal frame.
    assert await registry.has_subscriber("t") is False


# --- the socket -------------------------------------------------------------------------------


def test_attach_carrying_a_policy_records_it_for_the_topic() -> None:
    topic = "ws-cache-declared"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(cache=OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            assert app.state.registry.cache_policy_for(topic) == OPT_OUT


def test_attach_without_a_cache_field_records_no_policy() -> None:
    topic = "ws-cache-absent"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach_without_cache_key())
            assert ws.receive_json()["type"] == "ai.url4.started"
            # `None`, not a default-constructed policy: the header carrier must still be able to
            # tell silence from a stated intent when the two are reconciled.
            assert app.state.registry.cache_policy_for(topic) is None


def test_reattach_with_a_different_policy_leaves_it_unchanged_and_warns() -> None:
    topic = "ws-cache-conflict"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(cache=OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            ws.send_json(_attach(cache=OPT_IN, from_sequence=1))
            warned = ws.receive_json()
            assert app.state.registry.cache_policy_for(topic) == OPT_OUT
            # The re-attach still resubscribes — the policy is ignored, the frame is not.
            assert ws.receive_json()["type"] == "ai.url4.started"
    assert warned["type"] == "ai.url4.log"
    assert warned["data"]["severity_text"] == "WARN"
    assert warned["subject"] == topic
    attributes = warned["data"]["attributes"]
    assert attributes["cache.declared"] == '{"participate":true}'
    assert attributes["cache.effective"] == '{"participate":false}'


def test_reattach_with_an_identical_policy_warns_about_nothing() -> None:
    topic = "ws-cache-restated"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(cache=OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            ws.send_json(_attach(cache=CachePolicy(participate=False), from_sequence=1))
            # A warning would have been queued BEFORE this replay, so the replay arriving first is
            # proof none was emitted.
            assert ws.receive_json()["type"] == "ai.url4.started"


def test_reattach_declaring_a_policy_after_declaring_none_is_ignored_and_warns() -> None:
    topic = "ws-cache-late-declaration"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach_without_cache_key())
            assert ws.receive_json()["type"] == "ai.url4.started"
            ws.send_json(_attach(cache=OPT_OUT, from_sequence=1))
            warned = ws.receive_json()
            assert app.state.registry.cache_policy_for(topic) is None
    assert warned["type"] == "ai.url4.log"
    assert warned["data"]["severity_text"] == "WARN"
    assert warned["data"]["attributes"]["cache.effective"] == "not stated"


def test_a_second_connection_cannot_restate_the_first_connections_policy() -> None:
    topic = "ws-cache-two-connections"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        url = f"/ws?ticket={_token(topic)}"
        with client.websocket_connect(url) as first:
            first.send_json(_attach(cache=OPT_OUT))
            assert first.receive_json()["type"] == "ai.url4.started"
            with client.websocket_connect(url) as second:
                second.send_json(_attach(cache=OPT_IN))
                warned = second.receive_json()
                assert app.state.registry.cache_policy_for(topic) == OPT_OUT
    assert warned["type"] == "ai.url4.log"
    assert warned["data"]["severity_text"] == "WARN"


def test_run_start_stays_gated_on_an_attached_subscriber() -> None:
    """The whole design rests on attach preceding run start; assert it rather than assume it."""
    topic = "ws-cache-gate"
    stream = InMemoryEventStream()
    app = _make_app(stream=stream)
    headers = {"URL4-Capability": _token(topic)}
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        assert client.get("/", params={"q": "gpt()"}, headers=headers).status_code == 428
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(cache=OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            started = client.get(
                "/", params={"q": "gpt()"}, headers={**headers, "Prefer": "respond-async"}
            )
            # By the time a run CAN be scheduled, the frame's declaration is already recorded.
            assert app.state.registry.cache_policy_for(topic) == OPT_OUT
    assert started.status_code == 202

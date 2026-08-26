"""Batch 5 — convergence: two carriers, ONE effective cache policy.

A run can be configured twice — once on the WS attach frame, once on the ``GET /`` that starts it
— and the gateway must be told exactly one thing. This is where the two become one (spec §5.3, D4):

* **The header wins a genuine disagreement.** Attach happens first; the GET is the later,
  run-scoped statement, so last-writer-wins matches causal order. The override is never silent — a
  ``warn`` ``LogEvent`` reaches the attached client saying what it declared and what actually
  applies. Losing a declaration quietly is the failure mode this whole design exists to avoid.
* **Explicit beats absent, both ways.** One carrier speaking while the other is silent is not a
  disagreement and warns about nothing.
* **Silence on both resolves to the ON default HERE, and nowhere else.** Everything downstream
  takes a RESOLVED policy, so "what does saying nothing mean?" is answered exactly once —
  which is the only reason ``policy_to_body_field`` gets to stay a dumb translation.

The route-level tests spy on ``_schedule`` rather than on the job runner. That is deliberate and
not laziness: threading the policy past ``_schedule`` onto the runner is the NEXT batch, so the
kwarg it is handed is genuinely the last observable point in this one. Asserting further down
would either pass vacuously or pin work that does not exist yet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from _fakes import FixedGate, RecordingJobRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.auth import JwtCodec
from screamingface_engine.config import Settings
from screamingface_engine.rest import cache_policy, routes
from screamingface_engine.rest.cache_policy import default_policy, resolve
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.ws import ConnectionRegistry
from url4.streaming.protocol import (
    AttachData,
    AttachEvent,
    CachePolicy,
    OutboundFrame,
    StartedData,
    StartedEvent,
    TerminatedData,
    TerminatedEvent,
)

SECRET = "rest-cache-convergence-secret"
WINDOW_S = 60
LIFETIME_S = 58_800  # capability_lifetime_s (D1, OME-1016)
T0 = datetime(2026, 8, 5, 9, 0, 0, tzinfo=UTC)

OPT_OUT = CachePolicy(participate=False)
OPT_IN = CachePolicy(participate=True)
BOUNDED = CachePolicy(participate=True, max_age=60)


# --- the resolver, on its own ------------------------------------------------------------------


def test_silence_on_both_carriers_resolves_to_the_on_default() -> None:
    resolution = resolve(None, None)

    assert resolution.effective == CachePolicy(participate=True)
    assert resolution.overridden is None


def test_the_default_is_participation_and_carries_no_freshness_bound() -> None:
    """D1: caching is active unless a caller says otherwise, and silence states no bound."""
    assert default_policy().participate is True
    assert default_policy().max_age is None


def test_each_default_is_its_own_object() -> None:
    """A shared module-level instance would be mutable state two concurrent runs could edit."""
    first, second = default_policy(), default_policy()

    assert first == second
    assert first is not second


def test_the_header_alone_is_the_effective_policy() -> None:
    resolution = resolve(OPT_OUT, None)

    assert resolution.effective == OPT_OUT
    assert resolution.overridden is None


def test_the_frame_alone_is_the_effective_policy() -> None:
    """Explicit beats absent in BOTH directions — the header does not win by merely existing."""
    resolution = resolve(None, OPT_OUT)

    assert resolution.effective == OPT_OUT
    assert resolution.overridden is None


def test_carriers_that_agree_override_nothing() -> None:
    """A client that states the same intent twice is not in conflict with itself."""
    resolution = resolve(CachePolicy(participate=False), CachePolicy(participate=False))

    assert resolution.effective == OPT_OUT
    assert resolution.overridden is None


def test_the_header_overrides_a_disagreeing_frame_and_the_loser_is_reported() -> None:
    resolution = resolve(OPT_IN, OPT_OUT)

    assert resolution.effective == OPT_IN
    # The displaced policy is carried out of the resolver rather than merely flagged: the warning
    # has to be able to name what was dropped, or a client cannot tell WHICH of its two statements
    # lost.
    assert resolution.overridden == OPT_OUT


def test_a_freshness_bound_the_gateway_cannot_honour_degrades_to_opt_out() -> None:
    """Owner decision 2026-08-06 (spec §3.5): while `GATEWAY_REPORTS_AGE` is False, a stated
    `max-age` opts the run out at convergence rather than participating and revalidating.

    Honouring it after the fact would cost a second gateway call and a discarded body on EVERY
    bounded hit — inside the tool loop, so a four-iteration turn becomes eight calls. And D6
    invites intermediaries to inject the header, so `max-age=0` from a browser reload would
    trigger it accidentally.
    """
    resolution = resolve(BOUNDED, None)

    assert resolution.effective.participate is False
    assert resolution.effective.max_age == 60, "the bound is preserved, only participation flips"


def test_the_bound_is_honoured_the_day_the_gateway_reports_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D11's honouring half, dormant behind one flag. `requires_revalidation` and its tests are
    already written and correct; this pins that flipping the flag is all that reaches them."""
    monkeypatch.setattr(cache_policy, "GATEWAY_REPORTS_AGE", True)

    resolution = resolve(BOUNDED, None)

    assert resolution.effective.participate is True
    assert resolution.effective.max_age == 60


def test_carriers_agreeing_on_participation_but_not_on_the_bound_still_conflict() -> None:
    """Participate, and participate-but-nothing-older-than-60s, are different statements."""
    resolution = resolve(BOUNDED, OPT_IN)

    # The header still WINS and the frame is still reported as overridden — the disagreement is
    # judged on what the carriers STATED, before the gateway-capability degrade rewrites it.
    assert resolution.effective.max_age == 60
    assert resolution.effective.participate is False, "degraded: no age source (spec §3.5)"
    assert resolution.overridden == OPT_IN


# --- the route: the resolved policy reaches `_schedule` -----------------------------------------


def _token(topic: str) -> str:
    return JwtCodec(secret=SECRET, iat_window_s=WINDOW_S, capability_lifetime_s=LIFETIME_S).sign(
        topic, T0
    )


@pytest.fixture
def scheduled(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the keyword arguments `start_run` hands `_schedule` (see the module docstring)."""
    calls: list[dict[str, Any]] = []

    async def _spy(deps: object, topic: str, url4: str, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(routes, "_schedule", _spy)
    return calls


def _gated_app() -> FastAPI:
    """An app whose subscriber gate always passes — no socket, so no frame carrier either."""
    return create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=InMemoryEventStream(),
        job_runner=RecordingJobRunner(),
        clock=lambda: T0,
        interest=FixedGate(),
    )


async def _start(app: FastAPI, topic: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            "/",
            params={"q": "gpt(hi)"},
            headers={
                "URL4-Capability": _token(topic),
                "Prefer": "respond-async",
                **headers,
            },
        )


@pytest.mark.asyncio
async def test_a_run_declaring_nothing_is_scheduled_participating(
    scheduled: list[dict[str, Any]],
) -> None:
    """The ON default is applied at convergence, so nothing downstream sees `None` and guesses."""
    resp = await _start(_gated_app(), "conv-default")

    assert resp.status_code == 202
    assert scheduled[0]["cache"] == CachePolicy(participate=True)


@pytest.mark.asyncio
async def test_the_headers_opt_out_reaches_the_scheduled_run(
    scheduled: list[dict[str, Any]],
) -> None:
    await _start(_gated_app(), "conv-no-store", **{"Cache-Control": "no-store"})

    assert scheduled[0]["cache"] == CachePolicy(participate=False)


@pytest.mark.asyncio
async def test_a_headers_freshness_bound_reaches_the_scheduled_run(
    scheduled: list[dict[str, Any]],
) -> None:
    await _start(_gated_app(), "conv-max-age", **{"Cache-Control": "max-age=60"})

    # Degraded at convergence, so what reaches the run — and therefore the gateway — is an
    # opt-out. The bound rides along unused until `GATEWAY_REPORTS_AGE` flips.
    assert scheduled[0]["cache"] == CachePolicy(participate=False, max_age=60)


@pytest.mark.asyncio
async def test_a_malformed_header_falls_back_to_the_default_rather_than_failing_the_run(
    scheduled: list[dict[str, Any]],
) -> None:
    """A cache directive is a hint about cost; it must never be the reason an ensemble run dies."""
    resp = await _start(_gated_app(), "conv-garbage", **{"Cache-Control": "%%% not a directive"})

    assert resp.status_code == 202
    assert scheduled[0]["cache"] == CachePolicy(participate=True)


@pytest.mark.asyncio
async def test_the_cache_policy_travels_beside_profile_and_identity_not_instead_of_them(
    scheduled: list[dict[str, Any]],
) -> None:
    """One more per-run value on the same hop — it must not displace the ones already there."""
    await _start(
        _gated_app(),
        "conv-beside",
        **{"Cache-Control": "no-store", "X-Profile": "prod", "X-User-Email": "a@b.c"},
    )

    call = scheduled[0]
    assert call["profile"] == "prod"
    assert call["identity"] == {"X-User-Email": "a@b.c"}
    assert call["cache"] == CachePolicy(participate=False)


# --- the route + the socket: the frame carrier, and the override warning ------------------------


def _socket_app(stream: InMemoryEventStream) -> FastAPI:
    """No injected gate: the real registry is BOTH the subscriber gate and the frame's session."""
    return create_app(
        Settings(jwt_secret=SECRET, iat_window_s=WINDOW_S),
        stream=stream,
        job_runner=RecordingJobRunner(),
        clock=lambda: T0,
    )


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


def _terminated(topic: str) -> TerminatedEvent:
    return TerminatedEvent(
        id=f"t-{topic}",
        source=f"/trace/{topic}/node/root",
        subject=topic,
        data=TerminatedData(status="succeeded"),
    )


def _attach(cache: CachePolicy | None) -> dict[str, Any]:
    event = AttachEvent(
        id="att",
        source="/client",
        subject="t",
        data=AttachData(from_sequence=None, cache=cache),
    )
    return event.model_dump(mode="json", by_alias=True)


def _get(client: TestClient, topic: str, **headers: str) -> httpx.Response:
    return client.get(
        "/",
        params={"q": "gpt()"},
        headers={"URL4-Capability": _token(topic), "Prefer": "respond-async", **headers},
    )


def test_the_frames_declaration_reaches_the_scheduled_run(
    scheduled: list[dict[str, Any]],
) -> None:
    topic = "conv-frame-only"
    stream = InMemoryEventStream()
    app = _socket_app(stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            assert _get(client, topic).status_code == 202

    assert scheduled[0]["cache"] == OPT_OUT


def test_a_conflicting_header_wins_and_the_attached_client_is_told(
    scheduled: list[dict[str, Any]],
) -> None:
    topic = "conv-conflict"
    stream = InMemoryEventStream()
    app = _socket_app(stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            assert _get(client, topic, **{"Cache-Control": "url4-use-cache"}).status_code == 202
            warned = ws.receive_json()

    assert scheduled[0]["cache"] == OPT_IN
    assert warned["type"] == "ai.url4.log"
    assert warned["data"]["severity_text"] == "WARN"
    assert warned["subject"] == topic
    attributes = warned["data"]["attributes"]
    # The same two attribute names the re-attach warning uses. One vocabulary for one question —
    # "what did I ask for, and what actually applies?" — regardless of which carrier lost.
    assert attributes["cache.declared"] == '{"participate":false}'
    assert attributes["cache.effective"] == '{"participate":true}'


def test_carriers_that_agree_warn_about_nothing(scheduled: list[dict[str, Any]]) -> None:
    """A warning would have been queued BEFORE this seeded frame, so the frame arriving first is
    proof none was emitted — an assertion about ORDER, which cannot flake, rather than about time.
    """
    topic = "conv-agree"
    stream = InMemoryEventStream()
    app = _socket_app(stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            assert _get(client, topic, **{"Cache-Control": "no-store"}).status_code == 202
            _seed(client, stream, topic, [_terminated(topic)])
            assert ws.receive_json()["type"] == "ai.url4.terminated"

    assert scheduled[0]["cache"] == OPT_OUT


def test_a_silent_header_does_not_override_the_frame_and_warns_about_nothing(
    scheduled: list[dict[str, Any]],
) -> None:
    """Absent is not a statement. If it were, no frame declaration could ever survive a GET."""
    topic = "conv-silent-header"
    stream = InMemoryEventStream()
    app = _socket_app(stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            assert _get(client, topic).status_code == 202
            _seed(client, stream, topic, [_terminated(topic)])
            assert ws.receive_json()["type"] == "ai.url4.terminated"

    assert scheduled[0]["cache"] == OPT_OUT


def test_a_malformed_header_leaves_the_frames_declaration_standing(
    scheduled: list[dict[str, Any]],
) -> None:
    """Garbage parses to "not stated", so it must not shadow a perfectly good frame declaration."""
    topic = "conv-garbage-header"
    stream = InMemoryEventStream()
    app = _socket_app(stream)
    with TestClient(app) as client:
        _seed(client, stream, topic, [_started(topic)])
        with client.websocket_connect(f"/ws?ticket={_token(topic)}") as ws:
            ws.send_json(_attach(OPT_OUT))
            assert ws.receive_json()["type"] == "ai.url4.started"
            assert _get(client, topic, **{"Cache-Control": "=,=,="}).status_code == 202
            _seed(client, stream, topic, [_terminated(topic)])
            assert ws.receive_json()["type"] == "ai.url4.terminated"

    assert scheduled[0]["cache"] == OPT_OUT


# --- the notice channel the override warning travels down --------------------------------------


def _notice() -> StartedEvent:
    """Any frame will do — the channel is about DELIVERY, not about what is delivered."""
    return _started("notice")


def test_a_notice_reaches_every_connection_attached_to_the_topic() -> None:
    """Two sockets may legitimately observe one run, and a notice about it belongs to both."""
    registry = ConnectionRegistry()
    first: list[OutboundFrame] = []
    second: list[OutboundFrame] = []
    registry.add_notifier("t", first.append)
    registry.add_notifier("t", second.append)

    frame = _notice()
    registry.notify("t", frame)

    assert first == [frame]
    assert second == [frame]


def test_a_withdrawn_sink_stops_receiving() -> None:
    """A disconnected connection must not keep collecting frames nobody will ever read."""
    registry = ConnectionRegistry()
    received: list[OutboundFrame] = []
    registry.add_notifier("t", received.append)
    registry.remove_notifier("t", received.append)

    registry.notify("t", _notice())

    assert received == []


def test_withdrawing_a_sink_from_a_topic_that_is_already_gone_is_not_an_error() -> None:
    """A connection withdraws in `finally`, which also runs after the session was discarded."""
    registry = ConnectionRegistry()
    received: list[OutboundFrame] = []

    registry.remove_notifier("never-seen", received.append)


def test_notifying_a_topic_nobody_is_attached_to_is_a_silent_no_op() -> None:
    """A notice explains a request that was ALREADY accepted.

    Failing — or raising — because the explanation had nowhere to land would trade the answer for
    its footnote. The 428 gate means this cannot happen on the override path; it must still not be
    an exception waiting for the first caller that reaches it another way.
    """
    ConnectionRegistry().notify("never-seen", _notice())

"""`/readyz` is a readiness probe that can actually fail (OME-942).

Before this it returned `{"status": "ready"}` unconditionally, and the chart pointed BOTH
probes at `/healthz` — so the readiness probe could not fail, whatever the state of the pod's
NATS connection. That is a defect in the probe, established by reading the chart and the
endpoint; no incident is claimed here, and none was investigated. A probe that cannot fail is
not a probe; it is a constant the operator mistakes for evidence.

SCOPE, stated exactly (review round 2): this asks the App's OWN event-stream connection
(`app.state.stream`, the JetStream CONSUMER). The queue runner holds separate NATS connections
of its own and is NOT probed here — see the ledger's D7.

OWNER DECISION (2026-09-17): implement `/livez` and `/readyz` rather than delete them, and
point the chart's probes at them.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from nats.js import JetStreamContext

from screamingface_engine.adapters.jetstream import (
    READINESS_DIAL_TIMEOUT_S,
    JetStreamConsumer,
)
from screamingface_engine.app import create_app
from screamingface_engine.readiness import (
    MAX_REASON_CHARS,
    READINESS_TIMEOUT_S,
    StreamNotReadyError,
    stream_readiness,
)

pytestmark = pytest.mark.asyncio


class _ReadyStream:
    """A broker-backed stream that reports itself reachable."""

    def __init__(self) -> None:
        self.checks = 0

    async def check_ready(self) -> None:
        self.checks += 1


class _UnreachableStream:
    def __init__(self, reason: str = "nats://nats:4222 is not connected") -> None:
        self._reason = reason

    async def check_ready(self) -> None:
        raise StreamNotReadyError(self._reason)


class _BrokerlessStream:
    """The in-process stream: no broker, so nothing to be unreachable."""


def _client(stream: object | None) -> TestClient:
    return TestClient(create_app(stream=cast(Any, stream)))


# --- the endpoint ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/livez", "/readyz"])
async def test_the_ops_probes_are_served(path: str) -> None:
    """Both endpoints exist and are the two the chart now probes."""
    with _client(_ReadyStream()) as client:
        assert client.get(path).status_code == 200


async def test_livez_reports_the_process_is_up_regardless_of_the_broker() -> None:
    """INVARIANT: liveness is about THIS process. A broker outage must not restart every pod —
    that is the failure mode of conflating the two probes, and why they are separate."""
    with _client(_UnreachableStream()) as client:
        response = client.get("/livez")

    assert response.status_code == 200
    assert response.json()["status"] == "live"


async def test_readyz_is_ready_when_the_stream_is_reachable() -> None:
    stream = _ReadyStream()
    with _client(stream) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert stream.checks == 1, "the probe must actually ask the stream, not answer from memory"


async def test_readyz_refuses_when_the_stream_cannot_reach_the_broker() -> None:
    # STORY: as the cluster, I stop sending runs to a pod that cannot publish them.
    with _client(_UnreachableStream("nats://nats:4222 is not connected")) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["reason"] == "nats://nats:4222 is not connected"


async def test_an_app_with_no_stream_wired_is_ready() -> None:
    """INVARIANT: the probe reports BROKER reachability, not composition. `create_app_from_env`
    always wires a stream, so an unwired one is a composition-time choice (a test App, an
    embedding host) and not an outage — and `test_docs_ops.py` has pinned this shape as 200
    since before the endpoint could fail at all."""
    with _client(None) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_a_brokerless_stream_is_ready() -> None:
    """INVARIANT: readiness is asked of the PORT, not of a concrete adapter. The in-process
    stream (`--local`) has no broker to be unreachable from, so it is ready — the endpoint must
    not require every implementer to grow a `check_ready`."""
    with _client(_BrokerlessStream()) as client:
        assert client.get("/readyz").status_code == 200


# --- the readiness helper -------------------------------------------------------------------


async def test_stream_readiness_names_the_reason_it_is_not_ready() -> None:
    reason = await stream_readiness(_UnreachableStream("broker refused the connection"))

    assert reason == "broker refused the connection"


async def test_stream_readiness_returns_no_reason_when_ready() -> None:
    assert await stream_readiness(_ReadyStream()) is None


# --- the JetStream adapter ------------------------------------------------------------------


async def test_a_connected_jetstream_binding_is_ready() -> None:
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, object())  # noqa: SLF001
    stream._nc = cast(Any, SimpleNamespace(is_closed=False, is_connected=True))  # noqa: SLF001

    await stream.check_ready()  # must not raise


async def test_a_partitioned_jetstream_binding_is_not_ready() -> None:
    """The failure this probe exists for: nats-py keeps the client object alive and retrying
    while `is_connected` is False. `is_closed` only flips once the reconnect budget is spent, so
    a check written against `is_closed` alone reports ready throughout an outage."""
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, object())  # noqa: SLF001
    stream._nc = cast(Any, SimpleNamespace(is_closed=False, is_connected=False))  # noqa: SLF001

    with pytest.raises(StreamNotReadyError):
        await stream.check_ready()


async def test_a_binding_that_cannot_dial_the_broker_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pod that has never reached NATS is the cold-start case: it must not join the Service's
    endpoints before its connection exists."""

    async def _refuse(*args: object, **kwargs: object) -> object:
        raise OSError("connection refused")

    monkeypatch.setattr("nats.connect", _refuse)
    stream = JetStreamConsumer("nats://unused:4222")

    with pytest.raises(StreamNotReadyError):
        await stream.check_ready()


async def test_a_timeout_dialling_the_broker_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: a probe never propagates the transport's own exception type — the endpoint
    would answer 500, which Kubernetes treats as a failed probe but an operator reads as a bug
    in the App rather than an outage in the broker."""

    async def _hang(*args: object, **kwargs: object) -> object:
        raise TimeoutError

    monkeypatch.setattr("nats.connect", _hang)
    stream = JetStreamConsumer("nats://unused:4222")

    with pytest.raises(StreamNotReadyError):
        await stream.check_ready()


async def test_a_directly_supplied_context_without_a_client_is_ready() -> None:
    """A `JetStreamContext` can be supplied without going through `nats.connect` (the adapter's
    `_is_closed` says so). Treating an absent client as unreachable would report a perfectly
    live injected context as down."""
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, object())  # noqa: SLF001

    await stream.check_ready()  # must not raise


async def test_readiness_never_blocks_on_a_broker_round_trip() -> None:
    """INVARIANT: kubelet probes every `periodSeconds`, forever. A check that issued an RPC
    would put a broker round trip on that timer for every pod; `check_ready` reads client state
    the connection already maintains."""
    stream = JetStreamConsumer("nats://unused:4222")
    stream._js = cast(JetStreamContext, object())  # noqa: SLF001
    stream._nc = cast(Any, SimpleNamespace(is_closed=False, is_connected=True))  # noqa: SLF001

    await asyncio.wait_for(stream.check_ready(), timeout=0.5)


# --- review round 2: the probe must not leak, and must not hang (OME-942) -------------------


class _LeakyStream:
    """A hypothetical adapter that ignores `StreamNotReadyError`'s contract and stuffs transport
    detail into the reason. The endpoint must still not render it unbounded."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def check_ready(self) -> None:
        raise StreamNotReadyError(self._reason)


async def test_the_dial_failure_reason_never_names_the_broker_url() -> None:
    """The reason reaches an UNAUTHENTICATED caller (`/readyz` has no auth dependency and the
    chart routes a single `/` PathPrefix to the App). `config.natsUrl` is free-form operator
    input and `nats://user:pass@host:4222` is the standard nats-py auth form, so the URL is a
    credential. The adapter's message is a fixed literal; the detail goes to the log."""
    secret_url = "nats://probe_user:sup3r_s3cret@broker.internal:4222"

    async def _refuse(*args: object, **kwargs: object) -> object:
        raise OSError(f"connection refused connecting to {secret_url}")

    stream = JetStreamConsumer(secret_url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("nats.connect", _refuse)
        with pytest.raises(StreamNotReadyError) as excinfo:
            await stream.check_ready()

    message = str(excinfo.value)
    assert "sup3r_s3cret" not in message
    assert "probe_user" not in message
    assert "broker.internal" not in message
    assert "connection refused" not in message


async def test_the_disconnected_reason_never_names_the_broker_url() -> None:
    secret_url = "nats://probe_user:sup3r_s3cret@broker.internal:4222"
    stream = JetStreamConsumer(secret_url)
    stream._js = cast(JetStreamContext, object())  # noqa: SLF001
    stream._nc = cast(Any, SimpleNamespace(is_closed=False, is_connected=False))  # noqa: SLF001

    with pytest.raises(StreamNotReadyError) as excinfo:
        await stream.check_ready()

    message = str(excinfo.value)
    assert "sup3r_s3cret" not in message
    assert "broker.internal" not in message


async def test_the_probe_response_never_carries_the_broker_url() -> None:
    """End to end, at the byte level: nothing of the URL or the broker's own text survives into
    the 503 body."""
    secret_url = "nats://probe_user:sup3r_s3cret@broker.internal:4222"

    async def _refuse(*args: object, **kwargs: object) -> object:
        raise OSError(f"connection refused connecting to {secret_url}")

    stream = JetStreamConsumer(secret_url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("nats.connect", _refuse)
        with _client(stream) as client:
            response = client.get("/readyz")

    assert response.status_code == 503
    raw = response.content.decode()
    for fragment in ("sup3r_s3cret", "probe_user", "broker.internal", "connection refused"):
        assert fragment not in raw


async def test_the_withheld_detail_is_logged_server_side(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """INVARIANT: withholding from the caller is not withholding from the operator. The reason
    the adapter raised is logged where only the cluster can read it."""

    caplog.set_level(logging.WARNING)
    reason = await stream_readiness(_UnreachableStream("broker refused the connection"))

    assert reason is not None
    messages = [record.getMessage() for record in caplog.records]
    assert any("broker refused the connection" in message for message in messages), messages


async def test_an_oversized_reason_is_bounded_before_it_is_rendered() -> None:
    """Defence in depth at the boundary: `StreamNotReadyError`'s contract says the message is a
    short operator-facing literal, but the endpoint is the last place to enforce it. An adapter
    that ignores the contract must not turn a probe into an unbounded reflector."""
    reason = await stream_readiness(_LeakyStream("x" * 5000))

    assert reason is not None
    assert len(reason) <= MAX_REASON_CHARS


async def test_control_characters_never_survive_into_a_rendered_reason() -> None:
    reason = await stream_readiness(_LeakyStream("bad\r\nInjected: header\x00end"))

    assert reason is not None
    assert "\r" not in reason
    assert "\n" not in reason
    assert "\x00" not in reason


async def test_a_hanging_dial_is_bounded_rather_than_parking_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finding this test exists for: `check_ready` awaits `_jetstream()`, which dials on the
    App's event loop under `_connect_lock` with no bound whenever `_js` is None — i.e. exactly
    during the outage the probe exists for. nats-py retries servers for its whole reconnect
    budget before raising, so an unbounded probe parks far past the kubelet's `timeoutSeconds`,
    and Starlette does not cancel the handler when the kubelet gives up: the next probe queues
    behind it on the lock, on the loop that pumps every WebSocket.

    Asserted as a BOUND, not as a duration: the dial below never returns at all, so a green run
    proves `check_ready` stopped waiting on its own.
    """

    async def _never_returns(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    monkeypatch.setattr("nats.connect", _never_returns)
    monkeypatch.setattr("screamingface_engine.adapters.jetstream.READINESS_DIAL_TIMEOUT_S", 0.05)
    stream = JetStreamConsumer("nats://unused:4222")

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(StreamNotReadyError):
        await asyncio.wait_for(stream.check_ready(), timeout=5.0)
    elapsed = loop.time() - started

    assert elapsed < 1.0, f"check_ready waited {elapsed:.3f}s on a dial that never returns"


async def test_a_hanging_dial_does_not_hold_the_connect_lock_for_the_next_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The queueing half of the same finding: if the bounded probe left `_connect_lock` held,
    every later probe would serialise behind the first for the whole outage. Cancelling the
    dial must release it, so a second probe fails on its own bound rather than the first's."""

    async def _never_returns(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    monkeypatch.setattr("nats.connect", _never_returns)
    monkeypatch.setattr("screamingface_engine.adapters.jetstream.READINESS_DIAL_TIMEOUT_S", 0.05)
    stream = JetStreamConsumer("nats://unused:4222")

    with pytest.raises(StreamNotReadyError):
        await asyncio.wait_for(stream.check_ready(), timeout=5.0)

    assert not stream._connect_lock.locked(), "the cancelled dial left the lock held"  # noqa: SLF001

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(StreamNotReadyError):
        await asyncio.wait_for(stream.check_ready(), timeout=5.0)

    assert loop.time() - started < 1.0, "the second probe queued behind the first"


async def test_an_adapter_that_never_returns_does_not_park_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary half of the hang finding: the adapter bounds its own dial, but `/readyz` must
    not depend on every adapter remembering to. Starlette does not cancel the handler when the
    kubelet's `timeoutSeconds` expires, so an unbounded check accumulates one pending handler
    per `periodSeconds` for the whole outage — on the loop that pumps every WebSocket."""

    class _NeverAnswers:
        async def check_ready(self) -> None:
            await asyncio.sleep(3600)

    monkeypatch.setattr("screamingface_engine.readiness.READINESS_TIMEOUT_S", 0.05)

    loop = asyncio.get_running_loop()
    started = loop.time()
    reason = await asyncio.wait_for(stream_readiness(_NeverAnswers()), timeout=5.0)
    elapsed = loop.time() - started

    assert reason == "event stream readiness check timed out"
    assert elapsed < 1.0, f"stream_readiness waited {elapsed:.3f}s on a check that never returns"


async def test_the_probe_answers_503_when_the_adapter_never_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same bound, seen through the endpoint: a parked check is NOT READY, not a hung
    request. TestClient has no timeout of its own, so a green run is the assertion."""

    class _NeverAnswers:
        async def check_ready(self) -> None:
            await asyncio.sleep(3600)

    monkeypatch.setattr("screamingface_engine.readiness.READINESS_TIMEOUT_S", 0.05)

    app = create_app(stream=cast(Any, _NeverAnswers()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        # Driven through httpx-on-ASGI rather than `TestClient` so the whole request can sit
        # under an `asyncio.wait_for`. That outer bound is the assertion's teeth: without it a
        # regression that removes the boundary bound HANGS the suite instead of failing it.
        response = await asyncio.wait_for(client.get("/readyz"), timeout=5.0)

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


async def test_the_dial_timeout_reason_never_names_the_broker_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The third message on the not-ready path, held to the same contract as the other two: the
    timeout branch is the one that fires during a real outage, so it is the one most likely to
    be read by someone who is not supposed to see the URL."""
    secret_url = "nats://probe_user:sup3r_s3cret@broker.internal:4222"

    async def _never_returns(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    monkeypatch.setattr("nats.connect", _never_returns)
    monkeypatch.setattr("screamingface_engine.adapters.jetstream.READINESS_DIAL_TIMEOUT_S", 0.05)
    stream = JetStreamConsumer(secret_url)

    with pytest.raises(StreamNotReadyError) as excinfo:
        await asyncio.wait_for(stream.check_ready(), timeout=5.0)

    message = str(excinfo.value)
    assert "sup3r_s3cret" not in message
    assert "probe_user" not in message
    assert "broker.internal" not in message


async def test_both_readiness_bounds_answer_before_the_kubelet_stops_listening() -> None:
    """The bounds are only worth anything if they are BELOW the probe's own timeout.

    Starlette cannot cancel the handler once the kubelet gives up, so a bound at or above
    `readinessProbe.timeoutSeconds` leaves exactly the handler pile-up the bound exists to
    prevent — the probe would simply be slow AND useless. Pinned against the chart's rendered
    value rather than a repeated literal, so raising one without the other fails here.
    """
    values = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "deploy/helm/values.yaml").read_text()
    )
    probe_timeout_s = float(values["readinessProbe"]["timeoutSeconds"])

    assert READINESS_DIAL_TIMEOUT_S < probe_timeout_s, (
        f"the adapter's dial bound ({READINESS_DIAL_TIMEOUT_S}s) must answer before the "
        f"kubelet's readinessProbe.timeoutSeconds ({probe_timeout_s}s)"
    )
    assert READINESS_TIMEOUT_S < probe_timeout_s, (
        f"the endpoint's boundary bound ({READINESS_TIMEOUT_S}s) must answer before the "
        f"kubelet's readinessProbe.timeoutSeconds ({probe_timeout_s}s)"
    )
    assert READINESS_DIAL_TIMEOUT_S < READINESS_TIMEOUT_S, (
        "the adapter's own bound must fire first, so its specific reason is what surfaces"
    )

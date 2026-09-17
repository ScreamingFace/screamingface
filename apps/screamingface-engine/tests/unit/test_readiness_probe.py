"""`/readyz` is a readiness probe that can actually fail (OME-942).

Before this it returned `{"status": "ready"}` unconditionally, and the chart pointed BOTH
probes at `/healthz` — so a pod whose NATS connection was dead told Kubernetes it was ready to
serve. Kubernetes believed it, kept it in the Service's endpoints, and every run routed there
was accepted and then went nowhere. A probe that cannot fail is not a probe; it is a constant
the operator mistakes for evidence.

OWNER DECISION (2026-09-17): implement `/livez` and `/readyz` rather than delete them, and
point the chart's probes at them.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from nats.js import JetStreamContext

from screamingface_engine.adapters.jetstream import JetStreamConsumer
from screamingface_engine.app import create_app
from screamingface_engine.readiness import StreamNotReadyError, stream_readiness

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

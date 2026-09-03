"""`auth_mode=disabled` serves loopback only — except the probes, which is the point.

Plan §11 conflict 9: the middleware this one is modelled on gates every path, and a deployed pod
whose kubelet dials the Pod IP would 403 its own liveness probe and CrashLoopBackOff. The CI
image job reaches the container through a published port and hits the same non-loopback peer, so
the exemption is what keeps that job honest rather than a special case for Kubernetes.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from report_intake.config import Settings
from report_intake.core.local_only import PROBE_PATHS, LoopbackOnlyMiddleware
from report_intake.core.problem import PROBLEM_MEDIA_TYPE
from report_intake.main import create_app

from .test_report_schema import a_report


@pytest.fixture
def remote_client(database_url: str) -> Generator[TestClient, None, None]:
    """A caller that is neither a loopback peer nor a loopback host — a kubelet, or CI's curl."""
    app = create_app(Settings(database_url=database_url))
    with TestClient(app, base_url="http://10.1.2.3:9109", client=("10.1.2.3", 50000)) as client:
        yield client


def test_a_network_caller_cannot_file_a_report_against_a_local_only_service(
    remote_client: TestClient,
) -> None:
    response = remote_client.post(
        "/v1/reports", json=a_report(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert "auth_mode=mesh_or_turnstile" in response.json()["detail"]


def test_the_probes_answer_from_a_non_loopback_caller(remote_client: TestClient) -> None:
    """Spec §10: `/healthz` answers 200 from a non-loopback caller in every auth posture. And
    `/readyz` reaches its own probe rather than being refused before it — the 200 is the store
    answering, which is the whole thing a readiness probe is for."""
    assert remote_client.get("/healthz").status_code == 200
    assert remote_client.get("/readyz").status_code == 200


def test_a_loopback_caller_is_served(client: TestClient) -> None:
    """The `client` fixture is a loopback peer on a loopback base URL — which is what a developer
    running `uv run report-intake` actually is."""
    response = client.post(
        "/v1/reports", json=a_report(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 202


def test_a_loopback_peer_reaching_this_service_under_another_name_is_refused(
    database_url: str,
) -> None:
    """DNS rebinding: a name that resolves to 127.0.0.1 is how a page loaded elsewhere gets a
    browser to post here, and the peer check alone would not see it."""
    app = create_app(Settings(database_url=database_url))
    with TestClient(app, base_url="http://reports.example.test", client=("127.0.0.1", 50000)) as c:
        assert c.post("/v1/reports", json=a_report()).status_code == 403


def test_localhost_counts_as_loopback(database_url: str) -> None:
    app = create_app(Settings(database_url=database_url))
    with TestClient(app, base_url="http://localhost:9109", client=("127.0.0.1", 50000)) as c:
        assert c.get("/healthz").status_code == 200
        assert c.post("/v1/reports", json=a_report()).status_code == 202


def test_the_deployed_posture_installs_no_loopback_guard(mesh_client: TestClient) -> None:
    """`mesh_or_turnstile` is meant to be reached over a network; binding it to loopback would
    break the deployment it exists for. The gate at the route is what answers there instead."""
    response = mesh_client.get("/healthz")

    assert response.status_code == 200


def test_every_exempt_path_is_a_real_route(client: TestClient) -> None:
    """The exemption is a literal set, so a renamed probe would silently stop being exempt — and
    the pod that discovers that is a pod in CrashLoopBackOff. Read out of the OpenAPI document
    rather than by walking `app.routes`, which nests included routers."""
    declared = set(client.get("/openapi.json").json()["paths"])

    assert PROBE_PATHS <= declared


# --- the fail-closed edges, at the ASGI level ------------------------------------------------
#
# A request with no `Host` header, or with a peer that is not an address, cannot be produced
# through an HTTP client — httpx always sets one and uvicorn always sets the other. They are
# reachable through a hand-built scope, and each is a place where "cannot tell" must mean "no".


async def _refused_by(scope: Scope) -> list[Message]:
    sent: list[Message] = []

    async def app(inner: Scope, receive: Receive, send: Send) -> None:  # pragma: no cover
        raise AssertionError("a refused caller must never reach the app")

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:  # pragma: no cover - a refusal reads no body
        raise AssertionError("a refused body must not be drained")

    await LoopbackOnlyMiddleware(app)(scope, receive, send)
    return sent


def _scope(*, client: object, headers: list[tuple[bytes, bytes]]) -> Scope:
    return {
        "type": "http",
        "method": "POST",
        "path": "/v1/reports",
        "headers": headers,
        "client": client,
    }


@pytest.mark.asyncio
async def test_a_request_with_no_host_header_is_refused() -> None:
    """HTTP/1.1 requires one and every client sends one, so its absence is a request nothing
    ordinary produced — and there is no name to check against loopback."""
    sent = await _refused_by(_scope(client=("127.0.0.1", 50000), headers=[]))

    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_a_host_header_that_cannot_be_parsed_is_refused() -> None:
    """An unterminated IPv6 literal makes `urlsplit` raise, and a name this cannot read is a name
    it cannot compare — so it refuses rather than falling through."""
    sent = await _refused_by(_scope(client=("127.0.0.1", 50000), headers=[(b"host", b"[::1")]))

    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_a_peer_that_is_not_an_address_is_refused() -> None:
    """Starlette's own TestClient defaults to the string `testclient`, and anything unparseable
    is refused rather than guessed at."""
    sent = await _refused_by(
        _scope(client=("testclient", 50000), headers=[(b"host", b"127.0.0.1")])
    )

    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_a_request_with_no_peer_at_all_is_refused() -> None:
    sent = await _refused_by(_scope(client=None, headers=[(b"host", b"127.0.0.1")]))

    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_a_websocket_scope_is_passed_straight_through() -> None:
    """The middleware is mounted on the whole app, and a scope with no `path` in `PROBE_PATHS`
    and no client must not raise on the way past."""
    reached: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(scope["type"])

    async def receive() -> Message:  # pragma: no cover - never called
        raise AssertionError("a passed-through scope must not be read")

    async def send(message: Message) -> None:  # pragma: no cover - never called
        raise AssertionError("a passed-through scope must not be written")

    await LoopbackOnlyMiddleware(app)({"type": "websocket", "path": "/ws"}, receive, send)

    assert reached == ["websocket"]

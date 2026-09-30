"""SC-21 — the engine freeze route proxies to AI Gateway with the caller identity.

FEATURE: OME-1307 (E14) reproducible submissions, contracts C2a (SDK -> engine) and C2b
(engine -> gateway). The REAL route and the REAL adapter run here; only the gateway is fake
(`httpx.MockTransport`).
INVARIANT: the engine relays the gateway receipt unchanged, forwards only the verified identity
(never `Authorization`, `Cookie` or `URL4-Capability`), and lets only a stable `code` cross.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.cache_versions.aigateway import AigatewayCacheVersions
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

EMAIL = "ana@example.org"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
# WHY literal: the receipt is opaque to the engine; it is never decoded.
RECEIPT = "eyJhbGciOiJFZERTQSJ9.e30.c2ln"
GATEWAY_BODY: dict[str, object] = {
    "receipt": RECEIPT,
    "cache_version_id": "3f2c8e0a-6f0e-4c3b-9d55-0c5b1c1d7a10",
    "entry_count": 412,
    "call_count": 420,
    "missing_count": 8,
    "coverage_status": "partial",
    "archive_sha256": "a" * 64,
}


def _run(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    gateway = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(capture)
    )
    app = create_app(
        Settings(jwt_secret="t"),
        stream=InMemoryEventStream(),
        cache_versions=AigatewayCacheVersions(gateway),
    )
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, seen


async def test_engine_cache_versions_route_proxies_with_caller_identity() -> None:
    client, seen = _run(lambda _r: httpx.Response(201, json=GATEWAY_BODY))

    async with client:
        response = await client.post(
            "/v1/cache-versions",
            json={"trace_id": TRACE_ID},
            headers={
                "X-User-Email": EMAIL,
                "traceparent": TRACEPARENT,
                "Authorization": "Bearer secret-token",
                "Cookie": "session=secret",
                "URL4-Capability": "secret-capability",
            },
        )

    assert response.status_code == 201
    (upstream,) = seen
    assert (upstream.method, upstream.url.path) == ("POST", "/v1/cache-versions")
    assert json.loads(upstream.content) == {"trace_id": TRACE_ID}
    assert upstream.headers["X-User-Email"] == EMAIL
    assert upstream.headers["traceparent"] == TRACEPARENT
    for forbidden in ("Authorization", "Cookie", "URL4-Capability", "X-Profile"):
        assert forbidden not in upstream.headers
    assert response.json() == GATEWAY_BODY


async def test_idempotent_refreeze_relays_200_and_the_same_receipt() -> None:
    client, _ = _run(lambda _r: httpx.Response(200, json=GATEWAY_BODY))

    async with client:
        response = await client.post(
            "/v1/cache-versions", json={"trace_id": TRACE_ID}, headers={"X-User-Email": EMAIL}
        )

    assert response.status_code == 200
    assert response.json()["receipt"] == RECEIPT
    assert response.json()["cache_version_id"] == GATEWAY_BODY["cache_version_id"]


async def test_trace_not_captured_is_a_404_problem_with_its_code() -> None:
    client, _ = _run(
        lambda _r: httpx.Response(
            404, json={"detail": {"code": "trace_not_captured", "message": "secret-text"}}
        )
    )

    async with client:
        response = await client.post(
            "/v1/cache-versions", json={"trace_id": TRACE_ID}, headers={"X-User-Email": EMAIL}
        )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "trace_not_captured"
    assert "secret-text" not in response.text


async def test_too_large_is_a_413_problem_with_its_code() -> None:
    client, _ = _run(
        lambda _r: httpx.Response(413, json={"detail": {"code": "cache_version_too_large"}})
    )

    async with client:
        response = await client.post(
            "/v1/cache-versions", json={"trace_id": TRACE_ID}, headers={"X-User-Email": EMAIL}
        )

    assert response.status_code == 413
    assert response.json()["code"] == "cache_version_too_large"


async def test_capture_disabled_is_a_503_problem_with_its_code() -> None:
    client, _ = _run(lambda _r: httpx.Response(503, json={"detail": {"code": "capture_disabled"}}))

    async with client:
        response = await client.post(
            "/v1/cache-versions", json={"trace_id": TRACE_ID}, headers={"X-User-Email": EMAIL}
        )

    assert response.status_code == 503
    assert response.json()["code"] == "capture_disabled"

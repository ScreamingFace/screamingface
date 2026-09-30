"""SC-21j..m — the engine freeze route's own contract, against a fake port.

FEATURE: OME-1307 (E14) contract C2a (SDK -> engine, the engine side).
INVARIANT: the request is validated, and a stated `X-Profile` refused, BEFORE any gateway call;
the answer is private and never cached.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.cache_versions.port import CacheVersionError, FrozenCacheVersion
from screamingface_engine.config import Settings
from screamingface_engine.connections.port import Caller
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

EMAIL = "ana@example.org"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
RECEIPT = "eyJhbGciOiJFZERTQSJ9.e30.c2ln"
FROZEN = FrozenCacheVersion(
    receipt=RECEIPT,
    cache_version_id="3f2c8e0a-6f0e-4c3b-9d55-0c5b1c1d7a10",
    entry_count=412,
    call_count=420,
    missing_count=8,
    coverage_status="partial",
    archive_sha256="c" * 64,
    created=True,
)


class FakeCacheVersions:
    def __init__(self) -> None:
        self.calls: list[tuple[Caller, str]] = []
        self.result = FROZEN
        self.error: CacheVersionError | None = None

    async def freeze(self, caller: Caller, trace_id: str) -> FrozenCacheVersion:
        self.calls.append((caller, trace_id))
        if self.error is not None:
            raise self.error
        return self.result

    async def aclose(self) -> None:
        return None


def _app(service: FakeCacheVersions | None) -> FastAPI:
    return create_app(
        Settings(jwt_secret="route-secret"),
        stream=InMemoryEventStream(),
        cache_versions=service,
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_INVALID_BODIES = [
    pytest.param({"trace_id": TRACE_ID.upper()}, id="uppercase-hex"),
    pytest.param({"trace_id": TRACE_ID[:31]}, id="31-chars"),
    pytest.param({"trace_id": TRACE_ID + "0"}, id="33-chars"),
    pytest.param({"trace_id": "0" * 32}, id="all-zeros"),
    pytest.param({"trace_id": TRACE_ID, "extra": 1}, id="extra-key"),
    pytest.param({}, id="missing-key"),
    pytest.param({"trace_id": 5}, id="not-a-string"),
]


@pytest.mark.parametrize("body", _INVALID_BODIES)
async def test_an_invalid_trace_id_is_a_422_problem_before_any_gateway_call(
    body: dict[str, Any],
) -> None:
    service = FakeCacheVersions()

    async with _client(_app(service)) as client:
        response = await client.post("/v1/cache-versions", json=body)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_freeze_request"
    assert service.calls == []
    # INVARIANT: the answer never echoes the input.
    sent = body.get("trace_id")
    if isinstance(sent, str):
        assert sent not in response.text


async def test_a_stated_x_profile_is_refused_before_the_port() -> None:
    service = FakeCacheVersions()

    async with _client(_app(service)) as client:
        response = await client.post(
            "/v1/cache-versions", json={"trace_id": TRACE_ID}, headers={"X-Profile": "p"}
        )

    assert response.status_code == 400
    assert response.json()["code"] == "x_profile_unsupported"
    assert service.calls == []


async def test_an_unconfigured_engine_answers_503() -> None:
    async with _client(_app(None)) as client:
        response = await client.post("/v1/cache-versions", json={"trace_id": TRACE_ID})

    assert response.status_code == 503
    assert response.json()["code"] == "cache_versions_unconfigured"


async def test_the_route_is_published_in_openapi_with_its_problems() -> None:
    operation = _app(None).openapi()["paths"]["/v1/cache-versions"]["post"]

    responses = operation["responses"]
    for status in ("200", "201", "400", "404", "413", "503"):
        assert status in responses
    refusal = responses["400"]
    assert refusal["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/Problem"
    }
    assert "x_profile_unsupported" in refusal["description"]
    (header,) = [p for p in operation["parameters"] if p["name"] == "X-Profile"]
    assert header["in"] == "header"
    assert header["deprecated"] is True


async def test_the_answer_is_private_and_never_cached() -> None:
    service = FakeCacheVersions()

    async with _client(_app(service)) as client:
        response = await client.post(
            "/v1/cache-versions", json={"trace_id": TRACE_ID}, headers={"X-User-Email": EMAIL}
        )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Vary"] == "X-User-Email"


async def test_the_port_gets_the_verified_identity_and_a_valid_traceparent_only() -> None:
    service = FakeCacheVersions()

    async with _client(_app(service)) as client:
        await client.post(
            "/v1/cache-versions",
            json={"trace_id": TRACE_ID},
            headers={"X-User-Email": EMAIL, "traceparent": "garbage", "X-Other": "x"},
        )
        await client.post(
            "/v1/cache-versions",
            json={"trace_id": TRACE_ID},
            headers={"traceparent": TRACEPARENT},
        )

    (first, trace), (second, _) = service.calls
    assert trace == TRACE_ID
    assert dict(first.identity) == {"X-User-Email": EMAIL}
    assert first.traceparent is None
    # Blank identity is still forwarded: the gateway decides.
    assert dict(second.identity) == {}
    assert second.traceparent == TRACEPARENT


async def test_a_created_false_result_answers_200_and_relays_every_field_but_created() -> None:
    service = FakeCacheVersions()
    service.result = FrozenCacheVersion(
        receipt=FROZEN.receipt,
        cache_version_id=FROZEN.cache_version_id,
        entry_count=1,
        call_count=2,
        missing_count=1,
        coverage_status="complete",
        archive_sha256=FROZEN.archive_sha256,
        created=False,
    )

    async with _client(_app(service)) as client:
        response = await client.post("/v1/cache-versions", json={"trace_id": TRACE_ID})

    assert response.status_code == 200
    assert response.json() == {
        "receipt": FROZEN.receipt,
        "cache_version_id": FROZEN.cache_version_id,
        "entry_count": 1,
        "call_count": 2,
        "missing_count": 1,
        "coverage_status": "complete",
        "archive_sha256": FROZEN.archive_sha256,
    }


async def test_a_port_error_maps_to_its_public_problem_without_the_internal_detail() -> None:
    from screamingface_engine.cache_versions.port import CacheVersionRateLimited

    service = FakeCacheVersions()
    service.error = CacheVersionRateLimited("internal upstream text")

    async with _client(_app(service)) as client:
        response = await client.post("/v1/cache-versions", json={"trace_id": TRACE_ID})

    assert response.status_code == 429
    assert response.json().get("code") is None
    assert "internal upstream text" not in response.text


async def test_local_composition_wires_the_freeze_port_and_closes_it_on_shutdown() -> None:
    from screamingface_engine.cache_versions.aigateway import AigatewayCacheVersions
    from screamingface_engine.local import create_local_app

    app = create_local_app(
        Settings(jwt_secret="local-test", aigateway_base_url="http://aigateway.test"), env={}
    )

    port = app.state.cache_versions
    assert isinstance(port, AigatewayCacheVersions)
    assert port.aclose in app.router.on_shutdown


async def test_no_gateway_address_builds_no_freeze_port() -> None:
    from screamingface_engine.cache_versions import build_cache_versions

    assert build_cache_versions(Settings(jwt_secret="t", aigateway_base_url=None)) is None

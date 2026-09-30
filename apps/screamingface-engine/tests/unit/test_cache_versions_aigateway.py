"""SC-21f..i — the AI Gateway freeze adapter: no retry, body validation, the status map.

FEATURE: OME-1307 (E14) contract C2b (engine -> gateway).
INVARIANT: no engine retry (the SDK owns it); a malformed success body is never relayed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from screamingface_engine.cache_versions.aigateway import AigatewayCacheVersions
from screamingface_engine.cache_versions.port import (
    CacheVersionBadResponse,
    CacheVersionError,
    CacheVersionForbidden,
    CacheVersionRateLimited,
    CacheVersions,
    CacheVersionsUnavailable,
    CacheVersionTimeout,
    CacheVersionTooLarge,
    CacheVersionUnauthorized,
    CaptureDisabled,
    FrozenCacheVersion,
    TraceNotCaptured,
)
from screamingface_engine.connections.port import Caller

pytestmark = pytest.mark.asyncio

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
CALLER = Caller({"X-User-Email": "ana@example.org"})
RECEIPT = "eyJhbGciOiJFZERTQSJ9.e30.c2ln"
GOOD: dict[str, Any] = {
    "receipt": RECEIPT,
    "cache_version_id": "3f2c8e0a-6f0e-4c3b-9d55-0c5b1c1d7a10",
    "entry_count": 412,
    "call_count": 420,
    "missing_count": 8,
    "coverage_status": "partial",
    "archive_sha256": "b" * 64,
}


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[AigatewayCacheVersions, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(capture)
    )
    return AigatewayCacheVersions(client), seen


async def test_a_timeout_is_a_504_and_is_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    adapter, seen = _adapter(handler)

    with pytest.raises(CacheVersionTimeout):
        await adapter.freeze(CALLER, TRACE_ID)

    assert len(seen) == 1


async def test_a_transport_error_is_unavailable_and_is_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    adapter, seen = _adapter(handler)

    with pytest.raises(CacheVersionsUnavailable):
        await adapter.freeze(CALLER, TRACE_ID)

    assert len(seen) == 1


def _without(key: str) -> dict[str, Any]:
    return {k: v for k, v in GOOD.items() if k != key}


_MALFORMED = [
    pytest.param(httpx.Response(201, json=_without("receipt")), id="missing-key"),
    pytest.param(httpx.Response(201, json={**GOOD, "extra": 1}), id="extra-key"),
    pytest.param(httpx.Response(201, json={**GOOD, "cache_version_id": "nope"}), id="bad-uuid"),
    pytest.param(httpx.Response(201, json={**GOOD, "entry_count": -1}), id="negative-count"),
    pytest.param(httpx.Response(201, json={**GOOD, "call_count": True}), id="bool-count"),
    pytest.param(httpx.Response(201, json={**GOOD, "missing_count": 1.5}), id="float-count"),
    pytest.param(httpx.Response(201, json={**GOOD, "coverage_status": "full"}), id="bad-coverage"),
    pytest.param(httpx.Response(201, json={**GOOD, "archive_sha256": "A" * 64}), id="upper-sha"),
    pytest.param(httpx.Response(201, json={**GOOD, "archive_sha256": "b" * 63}), id="short-sha"),
    pytest.param(httpx.Response(201, json={**GOOD, "receipt": "  "}), id="blank-receipt"),
    pytest.param(httpx.Response(201, json={**GOOD, "receipt": 5}), id="non-str-receipt"),
    pytest.param(httpx.Response(200, json=[GOOD]), id="non-object"),
    pytest.param(httpx.Response(201, content=b"not json"), id="non-json"),
    pytest.param(httpx.Response(202, json=GOOD), id="2xx-other-than-200-201"),
]


@pytest.mark.parametrize("answer", _MALFORMED)
async def test_a_malformed_success_body_is_a_bad_response(answer: httpx.Response) -> None:
    adapter, _ = _adapter(lambda _r: answer)

    with pytest.raises(CacheVersionBadResponse):
        await adapter.freeze(CALLER, TRACE_ID)


def _coded(status: int, code: str | None) -> httpx.Response:
    if code is None:
        return httpx.Response(status)
    return httpx.Response(status, json={"detail": {"code": code, "message": "secret"}})


_STATUS_MAP = [
    pytest.param(404, "trace_not_captured", TraceNotCaptured, id="404-coded"),
    pytest.param(404, None, TraceNotCaptured, id="404-uncoded"),
    pytest.param(413, "cache_version_too_large", CacheVersionTooLarge, id="413"),
    pytest.param(503, "capture_disabled", CaptureDisabled, id="503-capture-disabled"),
    pytest.param(503, "other", CacheVersionsUnavailable, id="503-other-code"),
    pytest.param(503, None, CacheVersionsUnavailable, id="503-no-code"),
    pytest.param(401, None, CacheVersionUnauthorized, id="401"),
    pytest.param(403, None, CacheVersionForbidden, id="403"),
    pytest.param(429, None, CacheVersionRateLimited, id="429"),
    pytest.param(504, None, CacheVersionTimeout, id="504"),
    pytest.param(400, None, CacheVersionBadResponse, id="400"),
    pytest.param(409, None, CacheVersionBadResponse, id="409"),
    pytest.param(422, None, CacheVersionBadResponse, id="422"),
    pytest.param(500, None, CacheVersionBadResponse, id="500"),
    pytest.param(502, None, CacheVersionBadResponse, id="502"),
    pytest.param(302, None, CacheVersionBadResponse, id="3xx"),
]


@pytest.mark.parametrize(("status", "code", "error"), _STATUS_MAP)
async def test_the_status_map(
    status: int, code: str | None, error: type[CacheVersionError]
) -> None:
    adapter, seen = _adapter(lambda _r: _coded(status, code))

    with pytest.raises(error) as raised:
        await adapter.freeze(CALLER, TRACE_ID)

    assert type(raised.value) is error
    assert "secret" not in str(raised.value)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(httpx.Response(503, content=b"<html>"), id="non-json"),
        pytest.param(httpx.Response(503, json=["x"]), id="non-object"),
        pytest.param(httpx.Response(503, json={"detail": "capture_disabled"}), id="str-detail"),
        pytest.param(httpx.Response(503, json={"detail": {"code": 7}}), id="non-str-code"),
    ],
)
async def test_an_unreadable_error_body_means_no_code(answer: httpx.Response) -> None:
    adapter, _ = _adapter(lambda _r: answer)

    with pytest.raises(CacheVersionsUnavailable):
        await adapter.freeze(CALLER, TRACE_ID)


@pytest.mark.parametrize(("status", "created"), [(201, True), (200, False)])
async def test_a_valid_body_is_returned_with_its_created_flag(status: int, created: bool) -> None:
    adapter, seen = _adapter(lambda _r: httpx.Response(status, json=GOOD))

    frozen = await adapter.freeze(CALLER, TRACE_ID)

    assert frozen == FrozenCacheVersion(created=created, **GOOD)
    (request,) = seen
    assert json.loads(request.content) == {"trace_id": TRACE_ID}
    assert request.headers["X-User-Email"] == "ana@example.org"


async def test_the_receipt_is_kept_as_sent_not_stripped() -> None:
    padded = f" {RECEIPT} "
    adapter, _ = _adapter(lambda _r: httpx.Response(201, json={**GOOD, "receipt": padded}))

    assert (await adapter.freeze(CALLER, TRACE_ID)).receipt == padded


async def test_the_adapter_satisfies_the_port_and_closes_its_client() -> None:
    adapter, _ = _adapter(lambda _r: httpx.Response(201, json=GOOD))

    assert isinstance(adapter, CacheVersions)
    await adapter.aclose()
    assert adapter._client.is_closed  # noqa: SLF001


async def test_the_freeze_sends_identity_first_and_the_gateway_owned_headers_last() -> None:
    caller = Caller(
        {"X-User-Email": "ana@example.org", "traceparent": "forged", "X-Profile": "forged"},
        traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    )
    adapter, seen = _adapter(lambda _r: httpx.Response(201, json=GOOD))

    await adapter.freeze(caller, TRACE_ID)

    (request,) = seen
    assert request.headers["X-User-Email"] == "ana@example.org"
    assert request.headers["traceparent"] == caller.traceparent
    # The profile carrier is retired: a forged `X-Profile` in the identity mapping is not forwarded.
    assert "X-Profile" not in request.headers

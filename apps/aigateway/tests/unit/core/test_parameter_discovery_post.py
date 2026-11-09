"""OME-1537 — the bounded POST sibling of the discovery transport port.

Same envelope as ``get``: no redirect followed, identity encoding, body capped (counted
before retained), a TOTAL wall-clock deadline, and every fault a sanitized
``DiscoveryError``. Only the method and a JSON body differ.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

import httpx
import pytest

from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryPostClient,
    HttpxDiscoveryClient,
)

_URL = "http://localhost:11434/api/show"


def _client(handler) -> HttpxDiscoveryClient:
    return HttpxDiscoveryClient(transport=httpx.MockTransport(handler))


def test_the_production_adapter_satisfies_both_ports() -> None:
    adapter = HttpxDiscoveryClient()
    assert isinstance(adapter, DiscoveryPostClient)
    port: DiscoveryHttpClient = adapter
    assert port is adapter


@pytest.mark.asyncio
async def test_post_sends_the_json_body_and_passes_the_response_through() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"capabilities": ["vision"]})

    resp = await _client(handler).post(
        _URL, json_body={"model": "m:1b"}, timeout_s=3.0, max_bytes=1_000
    )
    assert resp.status == 200
    assert resp.content_type.startswith("application/json")
    assert json.loads(resp.body) == {"capabilities": ["vision"]}
    (request,) = seen
    assert request.method == "POST"
    assert json.loads(request.content) == {"model": "m:1b"}
    assert request.headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_post_does_not_follow_redirects() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "https://evil.example/x"})

    resp = await _client(handler).post(_URL, json_body={}, timeout_s=3.0, max_bytes=1_000)
    assert resp.status == 307


@pytest.mark.asyncio
async def test_post_rejects_an_oversized_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2_000)

    with pytest.raises(DiscoveryError) as exc:
        await _client(handler).post(_URL, json_body={}, timeout_s=3.0, max_bytes=1_000)
    assert exc.value.reason == "oversized"


@pytest.mark.asyncio
async def test_post_transport_fault_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused: secret-host-internal", request=request)

    with pytest.raises(DiscoveryError) as exc:
        await _client(handler).post(_URL, json_body={}, timeout_s=3.0, max_bytes=1_000)
    assert exc.value.reason == "unreachable"
    assert exc.value.__cause__ is None
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_post_slow_drip_hits_the_total_deadline() -> None:
    async def drip() -> AsyncIterator[bytes]:
        while True:
            yield b" "
            await asyncio.sleep(0.01)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=drip())

    started = time.monotonic()
    with pytest.raises(DiscoveryError) as exc:
        await _client(handler).post(_URL, json_body={}, timeout_s=0.25, max_bytes=1_000_000)
    assert exc.value.reason == "timeout"
    assert time.monotonic() - started < 3.0

"""The Engine's ``GET /v1/cache/entries``: the community cache, proxied (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted community cache via the
hosted Engine, which is the only door to the gateway that has one.

Pinned here: the route hands the caller's verified identity, trace context, query parameters and
gzip preference to the port, and streams the page back byte for byte with its content headers
passed through and private cache headers added; it closes the upstream page once the stream
ends; it answers 503 when not configured; each failure is problem+json with its own status; and
``build_community_cache`` builds the adapter only when a gateway address is configured.
"""

from __future__ import annotations

import gzip
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.community_cache import build_community_cache
from screamingface_engine.community_cache.aigateway import AigatewayCommunityCache
from screamingface_engine.community_cache.port import (
    CachePageRequest,
    CommunityCacheBadResponse,
    CommunityCacheInvalidRequest,
    CommunityCacheRejected,
    CommunityCacheTimeout,
    CommunityCacheUnavailable,
)
from screamingface_engine.config import Settings
from screamingface_engine.connections.port import Caller
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

_URL = "/v1/cache/entries"
_EMAIL = "researcher@example.com"
_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
_PAGE = b'{"schema":"screamingface.cache-page.v1","revisions":{}}\n{"next":null}\n'


class _Page:
    def __init__(self, chunks: list[bytes], *, encoding: str | None) -> None:
        self._chunks = chunks
        self.content_type = "application/x-ndjson"
        self.content_encoding = encoding
        self.closed = False

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _FakeCache:
    def __init__(self, page: _Page | None = None, error: Exception | None = None) -> None:
        self.page = page or _Page([_PAGE[:20], _PAGE[20:]], encoding=None)
        self.error = error
        self.calls: list[tuple[Caller, CachePageRequest]] = []

    async def open_page(self, caller: Caller, request: CachePageRequest) -> _Page:
        self.calls.append((caller, request))
        if self.error is not None:
            raise self.error
        return self.page

    async def aclose(self) -> None:
        return None


def _app(cache: _FakeCache | None) -> FastAPI:
    return create_app(
        Settings(jwt_secret="route-secret"),
        stream=InMemoryEventStream(),
        community_cache=cache,
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- the page ------------------------------------------------------------------------------------


async def test_the_page_streams_back_unchanged_with_private_headers() -> None:
    cache = _FakeCache()

    async with _client(_app(cache)) as client:
        response = await client.get(
            _URL, headers={"X-User-Email": _EMAIL, "Accept-Encoding": "identity"}
        )

    assert response.status_code == 200
    assert response.content == _PAGE
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Accept-Encoding, X-User-Email"
    assert "content-encoding" not in response.headers
    assert cache.page.closed


async def test_a_gzip_page_is_passed_through_still_compressed() -> None:
    zipped = gzip.compress(_PAGE)
    cache = _FakeCache(_Page([zipped], encoding="gzip"))

    async with (
        _client(_app(cache)) as client,
        client.stream(
            "GET", _URL, headers={"X-User-Email": _EMAIL, "Accept-Encoding": "gzip"}
        ) as response,
    ):
        raw = b"".join([chunk async for chunk in response.aiter_raw()])

    assert response.headers["content-encoding"] == "gzip"
    assert raw == zipped
    assert cache.calls[0][1].gzip is True


async def test_the_callers_identity_trace_and_parameters_reach_the_port() -> None:
    cache = _FakeCache()

    async with _client(_app(cache)) as client:
        await client.get(
            _URL,
            params=[
                ("after", "abc"),
                ("limit", "10"),
                ("count", "true"),
                ("model", "m1"),
                ("model", "m2"),
            ],
            headers={
                "X-User-Email": _EMAIL,
                "traceparent": _TRACEPARENT,
                "Accept-Encoding": "identity",
            },
        )

    [(caller, request)] = cache.calls
    assert caller.identity == {"X-User-Email": _EMAIL}
    assert caller.traceparent == _TRACEPARENT
    assert request == CachePageRequest(
        after="abc", limit=10, count=True, models=("m1", "m2"), gzip=False
    )


async def test_no_parameters_ask_for_the_first_page_of_everything() -> None:
    cache = _FakeCache()

    async with _client(_app(cache)) as client:
        await client.get(_URL, headers={"X-User-Email": _EMAIL, "Accept-Encoding": "identity"})

    assert cache.calls[0][1] == CachePageRequest()


# --- refusals ------------------------------------------------------------------------------------


async def test_an_engine_without_a_gateway_answers_503() -> None:
    async with _client(_app(None)) as client:
        response = await client.get(_URL, headers={"X-User-Email": _EMAIL})

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (CommunityCacheRejected(), 401),
        (CommunityCacheInvalidRequest(), 422),
        (CommunityCacheBadResponse(), 502),
        (CommunityCacheUnavailable(), 503),
        (CommunityCacheTimeout(), 504),
    ],
)
async def test_each_failure_is_problem_json_with_its_status(error: Exception, status: int) -> None:
    async with _client(_app(_FakeCache(error=error))) as client:
        response = await client.get(_URL, headers={"X-User-Email": _EMAIL})

    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == status


# --- composition ---------------------------------------------------------------------------------


async def test_no_gateway_address_builds_no_adapter() -> None:
    assert build_community_cache(Settings(jwt_secret="s")) is None


async def test_a_gateway_address_builds_the_adapter() -> None:
    cache = build_community_cache(
        Settings(jwt_secret="s", aigateway_base_url="http://aigateway.test")
    )

    assert isinstance(cache, AigatewayCommunityCache)
    await cache.aclose()

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

import anyio
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
    CommunityCacheRateLimited,
    CommunityCacheRejected,
    CommunityCacheTimeout,
    CommunityCacheUnavailable,
)
from screamingface_engine.config import Settings
from screamingface_engine.connections.port import Caller
from screamingface_engine.rest.cache_entries import _body
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


class _FailingPage(_Page):
    def __init__(self, error: Exception) -> None:
        super().__init__([_PAGE[:20]], encoding=None)
        self._error = error

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        yield _PAGE[:20]
        raise self._error


class _StallingPage(_Page):
    """A page whose upstream stalls after one chunk, and whose close needs an await to finish."""

    def __init__(self) -> None:
        super().__init__([_PAGE[:20]], encoding=None)

    async def aiter_raw(self) -> AsyncIterator[bytes]:
        yield _PAGE[:20]
        await anyio.sleep(60)

    async def aclose(self) -> None:
        await anyio.sleep(0)
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


def _assert_private(response: httpx.Response) -> None:
    # WHY on every answer: a shared cache in front of the Engine must never store one caller's
    # answer — a refusal included — and serve it to another.
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "X-User-Email"


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


@pytest.mark.parametrize(
    ("accept_encoding", "gzip_accepted"),
    [
        ("gzip", True),
        ("GZIP", True),
        ("br, Gzip;q=0.5", True),
        ("gzip;q=0", False),
        ("gzip;q=0.000, identity", False),
        ("gzip;q=bogus", False),
        ("*", True),
        ("*;q=0", False),
        ("gzip;q=0, *", False),
        ("identity", False),
        ("", False),
    ],
)
async def test_gzip_is_asked_for_only_when_the_caller_accepts_it(
    accept_encoding: str, gzip_accepted: bool
) -> None:
    cache = _FakeCache()

    async with _client(_app(cache)) as client:
        await client.get(_URL, headers={"X-User-Email": _EMAIL, "Accept-Encoding": accept_encoding})

    assert cache.calls[0][1].gzip is gzip_accepted


async def test_a_failure_mid_page_aborts_the_response_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # WHY abort, not end cleanly: the 200 is already sent, so a dropped connection is the only
    # way the caller's HTTP client can tell the page is incomplete.
    page = _FailingPage(CommunityCacheTimeout())

    with pytest.raises(CommunityCacheTimeout):
        async with _client(_app(_FakeCache(page))) as client:
            await client.get(_URL, headers={"X-User-Email": _EMAIL, "Accept-Encoding": "identity"})

    assert page.closed
    assert "community-cache page failed mid-stream: CommunityCacheTimeout" in caplog.text


async def test_a_client_that_goes_away_still_gets_the_upstream_page_closed() -> None:
    # WHY: Starlette cancels the stream's task group when the client disconnects, and anyio
    # cancels every later await in that scope — the close included, unless it is shielded.
    page = _StallingPage()
    body = _body(page)

    with anyio.CancelScope() as scope:
        await anext(body)
        scope.cancel()
        await anext(body)

    assert page.closed


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
    _assert_private(response)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (CommunityCacheRejected(), 401),
        (CommunityCacheInvalidRequest(), 422),
        (CommunityCacheRateLimited(), 429),
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
    _assert_private(response)


@pytest.mark.parametrize("params", [{"limit": "abc-SECRETISH"}, {"count": "maybe-SECRETISH"}])
async def test_an_invalid_parameter_is_a_private_problem_json_422_that_echoes_nothing(
    params: dict[str, str],
) -> None:
    cache = _FakeCache()

    async with _client(_app(cache)) as client:
        response = await client.get(_URL, params=params, headers={"X-User-Email": _EMAIL})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "the community-cache page request is invalid"
    assert "SECRETISH" not in response.text
    _assert_private(response)
    assert cache.calls == []


@pytest.mark.parametrize(
    ("params", "configured"),
    [({}, True), ({"limit": "abc"}, True), ({}, False)],
    ids=["valid", "before-validation", "before-not-configured"],
)
async def test_a_stated_profile_is_refused_before_anything_else(
    params: dict[str, str], configured: bool
) -> None:
    # INVARIANT (OME-1381): every Engine surface refuses the retired selector the same way, ahead
    # of its 422 and its 503, and never reaches the gateway.
    cache = _FakeCache() if configured else None

    async with _client(_app(cache)) as client:
        response = await client.get(
            _URL, params=params, headers={"X-User-Email": _EMAIL, "X-Profile": "work"}
        )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "x_profile_unsupported"
    _assert_private(response)
    if cache is not None:
        assert cache.calls == []


async def test_a_blank_profile_is_not_a_selector() -> None:
    cache = _FakeCache()

    async with _client(_app(cache)) as client:
        response = await client.get(
            _URL,
            headers={"X-User-Email": _EMAIL, "X-Profile": " ", "Accept-Encoding": "identity"},
        )

    assert response.status_code == 200
    assert len(cache.calls) == 1


async def test_a_rate_limit_tells_the_caller_when_to_retry() -> None:
    cache = _FakeCache(error=CommunityCacheRateLimited(retry_after=30))

    async with _client(_app(cache)) as client:
        response = await client.get(_URL, headers={"X-User-Email": _EMAIL})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    _assert_private(response)


async def test_a_rate_limit_without_a_hint_sends_no_retry_after() -> None:
    async with _client(_app(_FakeCache(error=CommunityCacheRateLimited()))) as client:
        response = await client.get(_URL, headers={"X-User-Email": _EMAIL})

    assert response.status_code == 429
    assert "retry-after" not in response.headers


# --- composition ---------------------------------------------------------------------------------


async def test_no_gateway_address_builds_no_adapter() -> None:
    assert build_community_cache(Settings(jwt_secret="s")) is None


async def test_a_gateway_address_builds_the_adapter() -> None:
    cache = build_community_cache(
        Settings(jwt_secret="s", aigateway_base_url="http://aigateway.test")
    )

    assert isinstance(cache, AigatewayCommunityCache)
    await cache.aclose()

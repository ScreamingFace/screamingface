"""OME-1045 — the engine's client for the aigateway Tavily retrieval cache."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from screamingface_engine.world.tavily_retrieval_cache import (
    TavilyLookup,
    TavilyRetrievalCache,
    fetch_description,
    search_description,
)

pytestmark = pytest.mark.asyncio

_LOOKUP = "/v1/retrieval/tavily/cache/lookup"
_FILL = "/v1/retrieval/tavily/cache/entries"
_HEADERS = {"X-User-Email": "a@example.test"}


def _cache(handler) -> tuple[TavilyRetrievalCache, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record), base_url="http://gw.test")
    return TavilyRetrievalCache(client, _HEADERS), seen


def test_search_description_carries_exactly_the_arguments_that_shape_the_request() -> None:
    assert search_description(
        query="q", search_depth="advanced", max_results=5, excluded_domains=("a.test", "b.test")
    ) == {
        "provider": "tavily",
        "tool": "web_search",
        "query": "q",
        "search_depth": "advanced",
        "max_results": 5,
        "excluded_domains": ["a.test", "b.test"],
    }


def test_fetch_description_carries_the_url_and_no_search_knobs() -> None:
    assert fetch_description(url="https://x.test/p", excluded_domains=()) == {
        "provider": "tavily",
        "tool": "web_fetch",
        "url": "https://x.test/p",
        "excluded_domains": [],
    }


async def test_a_hit_returns_the_stored_result_and_the_response_headers() -> None:
    cache, seen = _cache(
        lambda _: httpx.Response(
            200,
            headers={"Cache-Status": 'aigateway; hit; key="a1b2c3d4"'},
            json={"status": "hit", "result": "Title: T"},
        )
    )

    lookup = await cache.lookup(search_description("q", "advanced", 5, ()))

    assert lookup.status == "hit"
    assert lookup.result == "Title: T"
    assert lookup.headers["cache-status"] == 'aigateway; hit; key="a1b2c3d4"'
    assert seen[0].url.path == _LOOKUP
    assert seen[0].headers["x-user-email"] == "a@example.test"
    assert json.loads(seen[0].content)["query"] == "q"


async def test_a_miss_and_a_gateway_bypass_carry_no_result() -> None:
    miss, _ = _cache(lambda _: httpx.Response(200, json={"status": "miss", "result": None}))
    bypass, _ = _cache(
        lambda _: httpx.Response(
            200, json={"status": "bypass", "reason": "cache_unavailable", "result": None}
        )
    )
    description = fetch_description("https://x.test", ())

    missed = await miss.lookup(description)
    bypassed = await bypass.lookup(description)

    assert (missed.status, missed.result) == ("miss", None)
    assert (bypassed.status, bypassed.result) == ("bypass", None)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"detail": "boom"}),
        httpx.Response(422, json={"detail": {"code": "unknown_tool", "message": "x"}}),
        httpx.Response(200, content=b"<html>login</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"status": "weird", "result": None}),
        httpx.Response(200, json={"status": "hit", "result": None}),
        httpx.Response(200, json={"status": "hit", "result": 7}),
    ],
    ids=["5xx", "422", "not-json", "not-object", "unknown-status", "hit-no-result", "hit-bad-type"],
)
async def test_a_lookup_failure_degrades_to_a_bypass(response: httpx.Response) -> None:
    cache, _ = _cache(lambda _: response)

    assert await cache.lookup(fetch_description("https://x.test", ())) == TavilyLookup(
        "bypass", None, {}
    )


async def test_a_lookup_transport_error_degrades_to_a_bypass() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    cache, _ = _cache(boom)

    assert await cache.lookup(fetch_description("https://x.test", ())) == TavilyLookup(
        "bypass", None, {}
    )


async def test_lookup_and_fill_each_use_a_five_second_timeout() -> None:
    cache, seen = _cache(
        lambda _: httpx.Response(200, json={"status": "miss", "outcome": "stored"})
    )
    description = fetch_description("https://x.test", ())

    await cache.lookup(description)
    await cache.fill(description, "r")

    assert [r.extensions["timeout"] for r in seen] == [
        {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}
    ] * 2


@pytest.mark.parametrize("outcome", ["stored", "race_lost", "not_stored"])
async def test_a_fill_returns_the_gateway_outcome(outcome: str) -> None:
    cache, seen = _cache(lambda _: httpx.Response(200, json={"outcome": outcome}))

    assert await cache.fill(search_description("q", "advanced", 5, ()), "the result") == outcome
    assert seen[0].url.path == _FILL
    body = json.loads(seen[0].content)
    assert body["result"] == "the result"
    assert body["query"] == "q"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"detail": "boom"}),
        httpx.Response(422, json={"detail": {"code": "result_too_large", "message": "x"}}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"outcome": "mystery"}),
        httpx.Response(200, json={"no": "outcome"}),
    ],
    ids=["5xx", "422", "not-json", "unknown-outcome", "no-outcome"],
)
async def test_a_fill_failure_is_none(response: httpx.Response) -> None:
    cache, _ = _cache(lambda _: response)

    assert await cache.fill(fetch_description("https://x.test", ()), "r") is None


async def test_a_fill_transport_error_is_none() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    cache, _ = _cache(boom)

    assert await cache.fill(fetch_description("https://x.test", ()), "r") is None


async def test_cancellation_propagates_from_lookup_and_fill() -> None:
    def cancelled(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    cache, _ = _cache(cancelled)
    description = fetch_description("https://x.test", ())

    with pytest.raises(asyncio.CancelledError):
        await cache.lookup(description)
    with pytest.raises(asyncio.CancelledError):
        await cache.fill(description, "r")


async def test_a_failure_log_names_the_error_type_and_never_the_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache, _ = _cache(lambda _: httpx.Response(500, json={"detail": "boom"}))

    with caplog.at_level("WARNING"):
        await cache.lookup(search_description("a secret query", "advanced", 5, ()))
        await cache.fill(search_description("a secret query", "advanced", 5, ()), "secret result")

    assert "HTTPStatusError" in caplog.text
    assert "secret" not in caplog.text

"""OME-1045 — the Tavily tools consult the gateway retrieval cache before they pay Tavily."""

from __future__ import annotations

import json
from collections.abc import Mapping

import httpx
import pytest

from screamingface_engine.world.connector import AigatewayConfig
from screamingface_engine.world.tavily_retrieval_cache import TavilyLookup
from screamingface_engine.world.web_tools import WebToolRuntime, append_tool_results

pytestmark = pytest.mark.asyncio

_KEY = "tvly-test-key"  # noqa: S105 - not a real credential


class _FakeCache:
    """Records what the tools ask of the cache; answers lookups from a fixed script."""

    def __init__(self, lookup: TavilyLookup | None = None) -> None:
        self._lookup = lookup or TavilyLookup("miss", None, {})
        self.lookups: list[Mapping[str, object]] = []
        self.fills: list[tuple[Mapping[str, object], str]] = []

    async def lookup(self, description: Mapping[str, object]) -> TavilyLookup:
        self.lookups.append(description)
        return self._lookup

    async def fill(self, description: Mapping[str, object], result: str) -> str | None:
        self.fills.append((description, result))
        return "stored"


class _Tavily:
    def __init__(self, search: dict | None = None, extract: dict | None = None, status: int = 200):
        self.search = search if search is not None else {"results": []}
        self.extract = extract if extract is not None else {"results": [], "failed_results": []}
        self.status = status
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = self.search if request.url.path == "/search" else self.extract
        return httpx.Response(self.status, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="https://tavily.test"
        )


_ROW = {"title": "T", "url": "https://ok.test/a", "content": "C"}
_ROW_TEXT = "Title: T\nURL: https://ok.test/a\nContent: C"


async def _run(
    tavily: _Tavily,
    cache: _FakeCache | None,
    name: str,
    args: dict,
    *,
    excluded: tuple[str, ...] = (),
    config: AigatewayConfig | None = None,
) -> str:
    cfg = config or AigatewayConfig()
    async with tavily.client() as client:
        runtime = WebToolRuntime(client, cfg, _KEY, excluded, cache)  # type: ignore[arg-type]
        messages: list[dict] = []
        call = {"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}
        await append_tool_results(messages, [call], runtime, cfg)
    return messages[0]["content"]


async def test_a_search_hit_returns_the_cached_string_and_makes_no_tavily_request() -> None:
    tavily = _Tavily()
    cache = _FakeCache(TavilyLookup("hit", "cached text", {}))

    out = await _run(tavily, cache, "web_search", {"query": "q"})

    assert out == "cached text"
    assert tavily.requests == []
    assert cache.fills == []


async def test_a_fetch_hit_returns_the_cached_string_and_makes_no_tavily_request() -> None:
    tavily = _Tavily()
    cache = _FakeCache(TavilyLookup("hit", "cached page", {}))

    out = await _run(tavily, cache, "web_fetch", {"url": "https://x.test/p"})

    assert out == "cached page"
    assert tavily.requests == []


async def test_a_search_miss_calls_tavily_then_fills_the_formatted_string() -> None:
    tavily = _Tavily(search={"results": [_ROW]})
    cache = _FakeCache()

    out = await _run(tavily, cache, "web_search", {"query": "q"}, excluded=("bad.test",))

    assert out == _ROW_TEXT
    description = {
        "provider": "tavily",
        "tool": "web_search",
        "query": "q",
        "search_depth": "advanced",
        "max_results": 5,
        "excluded_domains": ["bad.test"],
    }
    assert cache.lookups == [description]
    assert cache.fills == [(description, _ROW_TEXT)]


async def test_a_fetch_miss_calls_tavily_then_fills_the_raw_content() -> None:
    tavily = _Tavily(extract={"results": [{"raw_content": "page body"}], "failed_results": []})
    cache = _FakeCache()

    out = await _run(tavily, cache, "web_fetch", {"url": "https://x.test/p"})

    assert out == "page body"
    description = {
        "provider": "tavily",
        "tool": "web_fetch",
        "url": "https://x.test/p",
        "excluded_domains": [],
    }
    assert cache.lookups == [description]
    assert cache.fills == [(description, "page body")]


async def test_the_filled_string_is_pre_truncation_and_post_exclusion() -> None:
    rows = [
        {"title": "Bad", "url": "https://sub.bad.test/x", "content": "leak"},
        {"title": "T", "url": "https://ok.test/a", "content": "C" * 500},
    ]
    tavily = _Tavily(search={"results": rows})
    cache = _FakeCache()
    config = AigatewayConfig(web_tool_max_result_bytes=100)

    out = await _run(
        tavily, cache, "web_search", {"query": "q"}, excluded=("bad.test",), config=config
    )

    (_, filled) = cache.fills[0]
    assert "leak" not in filled
    assert filled.endswith("C" * 500)
    assert out.endswith("…[truncated]")
    assert len(out.encode("utf-8")) <= 100


async def test_a_gateway_bypass_still_calls_tavily_and_does_not_fill() -> None:
    tavily = _Tavily(search={"results": [_ROW]})
    cache = _FakeCache(TavilyLookup("bypass", None, {}))

    out = await _run(tavily, cache, "web_search", {"query": "q"})

    assert out == _ROW_TEXT
    assert len(tavily.requests) == 1
    assert cache.fills == []


@pytest.mark.parametrize(
    ("name", "args", "tavily"),
    [
        ("web_search", {"query": "q"}, _Tavily(search={"results": []})),
        (
            "web_search",
            {"query": "q"},
            _Tavily(search={"results": [{"title": "x", "url": "https://bad.test/a"}]}),
        ),
        ("web_fetch", {"url": "https://x.test"}, _Tavily()),
        (
            "web_fetch",
            {"url": "https://x.test"},
            _Tavily(extract={"results": [], "failed_results": [{"url": "u", "error": "403"}]}),
        ),
        ("web_search", {"query": "q"}, _Tavily(status=500)),
        ("web_fetch", {"url": "https://x.test"}, _Tavily(status=500)),
    ],
    ids=["no-results", "all-excluded", "no-content", "extract-failed", "search-5xx", "fetch-5xx"],
)
async def test_only_a_success_fills_never_a_failure_string(
    name: str, args: dict, tavily: _Tavily
) -> None:
    cache = _FakeCache()

    await _run(tavily, cache, name, args, excluded=("bad.test",))

    assert cache.fills == []


async def test_a_blocked_fetch_url_never_reaches_the_cache() -> None:
    tavily = _Tavily()
    cache = _FakeCache()

    out = await _run(
        tavily, cache, "web_fetch", {"url": "https://a.bad.test/x"}, excluded=("bad.test",)
    )

    assert "blocked" in out
    assert cache.lookups == []


async def test_two_exclusion_sets_send_two_different_descriptions() -> None:
    cache = _FakeCache()

    await _run(_Tavily(search={"results": [_ROW]}), cache, "web_search", {"query": "q"})
    await _run(
        _Tavily(search={"results": [_ROW]}),
        cache,
        "web_search",
        {"query": "q"},
        excluded=("arxiv.org",),
    )

    assert [d["excluded_domains"] for d in cache.lookups] == [[], ["arxiv.org"]]
    assert [d["excluded_domains"] for d, _ in cache.fills] == [[], ["arxiv.org"]]


async def test_no_cache_means_tavily_is_called_exactly_as_today() -> None:
    tavily = _Tavily(search={"results": [_ROW]})

    out = await _run(tavily, None, "web_search", {"query": "q"})

    assert out == _ROW_TEXT
    assert [r.url.path for r in tavily.requests] == ["/search"]
    assert json.loads(tavily.requests[0].content) == {
        "query": "q",
        "search_depth": "advanced",
        "max_results": 5,
    }


async def test_the_tavily_key_is_sent_to_tavily_and_never_into_a_description() -> None:
    tavily = _Tavily(search={"results": [_ROW]})
    cache = _FakeCache()

    await _run(tavily, cache, "web_search", {"query": "q"})

    assert tavily.requests[0].headers["authorization"] == f"Bearer {_KEY}"
    assert _KEY not in json.dumps([cache.lookups, cache.fills])

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


# --- through the connector: the world wires the cache from its own aigateway client -----------

_MODEL = "anthropic/claude-haiku-4-5"
_LOOKUP = "/v1/retrieval/tavily/cache/lookup"
_FILL = "/v1/retrieval/tavily/cache/entries"


class _Gateway:
    """An aigateway that asks for one web_search, then answers; it serves the cache routes too."""

    def __init__(self, lookup: httpx.Response) -> None:
        self.lookup = lookup
        self.requests: list[httpx.Request] = []
        self._turn = 0

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == _LOOKUP:
            return self.lookup
        if request.url.path == _FILL:
            return httpx.Response(200, json={"outcome": "stored"})
        assert request.url.path == "/v1/chat/completions"
        self._turn += 1
        if self._turn % 2 == 1:
            call = {
                "id": "c1",
                "type": "function",
                "function": {"name": "web_search", "arguments": json.dumps({"query": "q"})},
            }
            message = {"role": "assistant", "content": None, "tool_calls": [call]}
        else:
            message = {"role": "assistant", "content": "done"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handle), base_url="http://aigateway.test"
        )

    def on(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == path]


async def _answer(gateway: _Gateway, tavily: _Tavily) -> str:
    from screamingface_engine.world.config import ModelSpec
    from screamingface_engine.world.connector import build_aigateway_world
    from url4.dag import run as url4_run

    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL, web_search=True),), default_model=_MODEL)
    async with gateway.client() as client, tavily.client() as tclient:
        world = await build_aigateway_world(
            cfg, client=client, tavily_api_key=_KEY, tavily_client=tclient
        )
        return await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)


def _tool_message(gateway: _Gateway) -> str:
    chats = gateway.on("/v1/chat/completions")
    return json.loads(chats[1].content)["messages"][-1]["content"]


async def test_the_world_fills_the_gateway_after_a_miss_and_never_sends_it_the_key() -> None:
    gateway = _Gateway(httpx.Response(200, json={"status": "miss", "result": None}))
    tavily = _Tavily(search={"results": [_ROW]})

    await _answer(gateway, tavily)

    assert len(tavily.requests) == 1
    assert json.loads(gateway.on(_FILL)[0].content)["result"] == _ROW_TEXT
    for request in gateway.requests:
        assert "authorization" not in request.headers
        assert _KEY not in str(request.headers) + request.content.decode("utf-8", errors="ignore")


async def test_the_world_serves_a_gateway_hit_with_no_tavily_request() -> None:
    gateway = _Gateway(httpx.Response(200, json={"status": "hit", "result": "cached text"}))
    tavily = _Tavily(search={"results": [_ROW]})

    await _answer(gateway, tavily)

    assert tavily.requests == []
    assert gateway.on(_FILL) == []
    assert _tool_message(gateway) == "cached text"


async def test_a_failing_gateway_cache_still_completes_the_run_through_tavily() -> None:
    gateway = _Gateway(httpx.Response(500, json={"detail": "boom"}))
    tavily = _Tavily(search={"results": [_ROW]})

    await _answer(gateway, tavily)

    assert len(tavily.requests) == 1
    assert gateway.on(_FILL) == []
    assert _tool_message(gateway) == _ROW_TEXT


async def test_the_fill_helper_returns_the_gateway_outcome_only_after_a_miss() -> None:
    from screamingface_engine.world.web_tools import _cache_fill

    description = {"provider": "tavily", "tool": "web_fetch", "url": "u", "excluded_domains": []}
    async with _Tavily().client() as client:
        runtime = WebToolRuntime(client, AigatewayConfig(), _KEY, (), _FakeCache())  # type: ignore[arg-type]
        miss = TavilyLookup("miss", None, {})
        bypass = TavilyLookup("bypass", None, {})

        assert await _cache_fill(runtime, miss, description, "r") == "stored"
        assert await _cache_fill(runtime, bypass, description, "r") is None

"""E14 F-B3 — capture mode stores every web-tool result the model reads (design §5.2 item 3).

FEATURE: OME-1307 — after `_execute_tool` returns its string and BEFORE truncation, the tool loop
posts the description and the string to the copy and records the outcome. Success, "no results"
and failure strings are all posted: the copy holds exactly what the model saw. A failed post never
raises into the tool loop; only a cancellation escapes.
STORY: as someone who replays a score, the web results are the ones the original model read.

A separate module (append-only gate).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    COPY,
    TOOL_RESULTS,
    Gateway,
    Tavily,
    capture_scope,
    chat,
    run_call,
    stored,
    tool_call,
)

from screamingface_engine.capture_outcomes import capture_outcomes
from screamingface_engine.world.connector import AigatewayConfig
from screamingface_engine.world.tavily_retrieval_cache import fetch_description, search_description
from screamingface_engine.world.web_tools import (
    FrozenToolResults,
    WebToolRuntime,
    append_tool_results,
    truncate_tool_result,
)

_CFG = AigatewayConfig()
_SEARCH = search_description("q", _CFG.tavily_search_depth, _CFG.tavily_max_results, [])


def _tool_outcomes(tally: Any) -> list[str]:
    return [o.status for o in tally.outcomes if o.lane == "tool"]


@pytest.mark.asyncio
async def test_tool_results_posted_before_truncation_including_failure_strings() -> None:
    big = "x" * (_CFG.web_tool_max_result_bytes + 5_000)
    tavily = Tavily(
        httpx.Response(
            200, json={"results": [{"title": "T", "url": "https://ok.test", "content": big}]}
        )
    )
    gateway = Gateway([tool_call("web_search", {"query": "q"}, stored()), chat("done", stored())])

    tally, answer, failure = await run_call(gateway, capture_scope(), tavily=tavily)

    assert failure is None and answer == "done"
    ((headers, body),) = gateway.calls(TOOL_RESULTS)
    assert body["description"] == _SEARCH
    # The copy holds the whole result; the model got the truncated one.
    assert body["result"] == f"Title: T\nURL: https://ok.test\nContent: {big}"
    assert len(body["result"].encode()) > _CFG.web_tool_max_result_bytes
    sent_to_model = gateway.calls(CHAT)[1][1]["messages"][-1]["content"]
    assert sent_to_model == truncate_tool_result(body["result"], _CFG.web_tool_max_result_bytes)
    assert "X-AIGW-Frozen-Copy" not in headers
    assert _tool_outcomes(tally) == ["stored"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "tavily", "description", "result"),
    [
        (
            tool_call("web_search", {"query": "q"}, stored()),
            Tavily(httpx.Response(200, json={"results": []})),
            _SEARCH,
            "no results",
        ),
        (
            tool_call("web_search", {"query": "q"}, stored()),
            Tavily(httpx.Response(500)),
            _SEARCH,
            "web_search failed: Server error '500 Internal Server Error' for url "
            "'https://tavily.test/search'\nFor more information check: "
            "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500",
        ),
        (
            tool_call("web_fetch", {"url": "https://a.test/p"}, stored()),
            Tavily(httpx.Response(200, json={"results": [{"raw_content": "page"}]})),
            fetch_description("https://a.test/p", []),
            "page",
        ),
        (
            tool_call("calculator", {"x": 1}, stored()),
            Tavily(),
            {"tool": "calculator", "arguments": {"x": 1}},
            "unknown tool: calculator",
        ),
        (
            tool_call("web_search", "not-an-object", stored()),
            Tavily(),
            {"tool": "web_search", "arguments": None},
            "invalid arguments for web_search",
        ),
    ],
    ids=["no-results", "tavily-failure", "web-fetch", "unknown-tool", "invalid-arguments"],
)
async def test_every_kind_of_result_string_is_stored_as_the_model_saw_it(
    step: httpx.Response, tavily: Tavily, description: dict[str, Any], result: str
) -> None:
    gateway = Gateway([step, chat("done", stored())])

    tally, _answer, failure = await run_call(gateway, capture_scope(), tavily=tavily)

    assert failure is None
    ((_headers, body),) = gateway.calls(TOOL_RESULTS)
    assert body == {"description": description, "result": result}
    assert _tool_outcomes(tally) == ["stored"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "store",
    [
        lambda _r: httpx.Response(200, json={"outcome": "failed"}),
        lambda _r: httpx.Response(500),
        lambda _r: httpx.Response(409, json={"detail": {"code": "frozen_copy_sealed"}}),
        lambda _r: httpx.Response(200, content=b"not json"),
        lambda _r: httpx.Response(200, json={"outcome": "surprise"}),
    ],
    ids=["outcome-failed", "http-500", "sealed-409", "not-json", "unknown-outcome"],
)
async def test_a_failed_tool_result_post_is_recorded_and_never_raised_into_the_tool_loop(
    store: Any,
) -> None:
    gateway = Gateway(
        [tool_call("web_search", {"query": "q"}, stored()), chat("done", stored())],
        tool_store=store,
    )

    tally, answer, failure = await run_call(gateway, capture_scope(), tavily=Tavily())

    assert failure is None
    assert answer == "done"
    assert _tool_outcomes(tally) == ["failed"]


@pytest.mark.asyncio
async def test_a_tool_result_post_that_times_out_is_failed_not_raised() -> None:
    def store(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    gateway = Gateway(
        [tool_call("web_search", {"query": "q"}, stored()), chat("done", stored())],
        tool_store=store,
    )

    tally, answer, failure = await run_call(gateway, capture_scope(), tavily=Tavily())

    assert failure is None and answer == "done"
    assert _tool_outcomes(tally) == ["failed"]


@pytest.mark.asyncio
async def test_a_cancelled_tool_result_post_is_an_error_outcome_and_the_cancellation_escapes() -> (
    None
):
    def store(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(store), base_url="http://aigateway.test"
    )
    runtime = WebToolRuntime(
        client=None,
        config=_CFG,
        api_key=None,
        excluded_domains=(),
        frozen=FrozenToolResults(client, {}, COPY, replay=False),
    )
    messages: list[dict] = []
    call = {"id": "c", "function": {"name": "calculator", "arguments": "{}"}}

    with capture_outcomes() as tally:
        with pytest.raises(asyncio.CancelledError):
            await append_tool_results(messages, [call], runtime, _CFG)

    assert _tool_outcomes(tally) == ["error"]
    await client.aclose()

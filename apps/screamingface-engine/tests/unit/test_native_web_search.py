"""Provider-side web search, and the expression-level toggle that selects it.

FEATURE: a route declares only THAT it may search (`web_search`, default true); the Engine
derives WHICH mechanism from the provider, and an expression turns retrieval on or off per
call with `;web_search=`.
STORY: as a benchmark author, a published score was produced on the provider's own server-side
search — a client-side loop over a different backend is a different experiment, so I need the
same surface, and I need to switch it off for the judge in the same expression.

TWO MECHANISMS, chosen by provider (`world_config.WEB_SEARCH_NATIVE_PROVIDERS`):
  * the TAVILY loop  — the RUNNER declares OpenAI functions and executes them against Tavily.
                       Serves every provider with no server-side search of its own.
  * the NATIVE path  — the PROVIDER executes the search and answers with it already done.
                       The runner asks the GATEWAY for it (`web_search: true`) and never
                       spells one provider's envelope itself.

INVARIANT: never both on one route. The request would carry two tool populations and
double-dispatch — searching twice per turn and billing for both. This is now structural
rather than validated: one flag cannot name two mechanisms (see
`test_web_search_routing.test_mechanisms_partition_the_flag`).
"""

from __future__ import annotations

import json

import httpx
import pytest

from screamingface_engine.retrieval_policy import RetrievalPolicy, retrieval_scope
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.web_tools import build_runtime
from url4.core.errors import ResolutionError

_NATIVE = "openrouter/anthropic/claude-opus-4.8"
_TAVILY = "claude-opus-4-8"
_PLAIN = "claude-haiku-4-5"


async def _bodies(expression: str, *, cfg: AigatewayConfig | None = None) -> list[dict]:
    """Evaluate against a mock gateway; return every captured chat-completions body."""
    captured: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "usage": {}})

    # `_NATIVE` is an openrouter route, so it delegates; `_TAVILY` is unprefixed (anthropic) and
    # takes the loop. `_PLAIN` has to OPT OUT now that searching is the default.
    config = cfg or AigatewayConfig(
        default_model=_PLAIN,
        models=(
            ModelSpec(id=_NATIVE),
            ModelSpec(id=_TAVILY),
            ModelSpec(id=_PLAIN, web_search=False),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(
            config, client=client, tavily_client=client, tavily_api_key="tv-key"
        )
        try:
            await world.node.evaluate(expression)
        finally:
            await world.aclose()
    return captured


def _call(route: str, chain: str = "") -> str:
    # `anchor` keeps the all-calls rule from firing the per-row reduce onto default_route.
    return f"(v:1.0:/{route}(a:1.0:'x')!'answer'{chain},anchor:1.0:'a')!'go'"


# --- the native surface ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_native_route_asks_the_gateway_for_retrieval() -> None:
    """INVARIANT: a provider-AGNOSTIC flag, not a provider payload.

    The gateway owns which provider can retrieve and how its envelope is spelled (OpenRouter's
    is `plugins: [{"id": "web"}]`, an extensibility envelope no caller may address). Building
    that here would put provider knowledge in the runner and fork a contract the gateway
    already owns.
    """
    body = (await _bodies(_call(_NATIVE)))[0]

    assert body["web_search"] is True
    assert "plugins" not in body
    assert "tools" not in body


@pytest.mark.asyncio
async def test_a_native_route_sends_no_tool_choice() -> None:
    """`tool_choice` is the OpenAI selection control and does not govern a provider-run
    plugin; sending it would advertise a control the provider does not honor here."""
    body = (await _bodies(_call(_NATIVE)))[0]

    assert "tool_choice" not in body


@pytest.mark.asyncio
async def test_a_native_route_runs_no_client_side_loop() -> None:
    """The provider answers with retrieval already done — one request, not a tool round trip."""
    assert len(await _bodies(_call(_NATIVE))) == 1


@pytest.mark.asyncio
async def test_absent_operator_parameters_omit_the_field_entirely() -> None:
    """An empty exclusion list must not be SENT as an empty list — that reads to the provider as
    'exclude nothing' rather than 'use your default'."""
    body = (await _bodies(_call(_NATIVE)))[0]

    assert "web_search_excluded_domains" not in body


@pytest.mark.asyncio
async def test_benchmark_policy_enables_native_search_and_carries_its_exclusions() -> None:
    with retrieval_scope(
        RetrievalPolicy(web_search=True, excluded_domains=("rubric.test", "paper.test"))
    ):
        body = (await _bodies(_call(_NATIVE)))[0]

    assert body["web_search"] is True
    assert body["web_search_excluded_domains"] == ["paper.test", "rubric.test"]


# --- the expression toggle -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_toggle_switches_a_native_route_off() -> None:
    body = (await _bodies(_call(_NATIVE, ";web_search=false")))[0]

    assert "web_search" not in body


@pytest.mark.asyncio
async def test_the_toggle_switches_a_tavily_route_off() -> None:
    body = (await _bodies(_call(_TAVILY, ";web_search=false")))[0]

    assert "tools" not in body


@pytest.mark.asyncio
async def test_a_tavily_route_still_declares_openai_functions() -> None:
    """The client-side mechanism is unchanged — it is what a provider with no server-side
    search of its own still needs."""
    body = (await _bodies(_call(_TAVILY)))[0]

    assert [t["function"]["name"] for t in body["tools"]] == ["web_search", "web_fetch"]
    assert body["tool_choice"] == "auto"
    assert "web_search" not in body


@pytest.mark.asyncio
async def test_saying_nothing_keeps_the_routes_declared_behaviour() -> None:
    """Absent means 'as declared' — for `_NATIVE` and `_TAVILY` that is unchanged from before
    this toggle existed, but `_PLAIN` used to stay silent by default and now must opt out
    explicitly to keep doing so."""
    assert "web_search" in (await _bodies(_call(_NATIVE)))[0]
    assert "tools" in (await _bodies(_call(_TAVILY)))[0]
    assert "tools" not in (await _bodies(_call(_PLAIN)))[0]
    assert "web_search" not in (await _bodies(_call(_PLAIN)))[0]


@pytest.mark.asyncio
async def test_asking_a_route_with_no_mechanism_to_search_is_loud() -> None:
    """The silent alternative is an expression that reads as though it retrieved and an answer
    written from weights alone — indistinguishable in the result."""
    with pytest.raises(ResolutionError, match="declares web_search = false"):
        await _bodies(_call(_PLAIN, ";web_search=true"))


@pytest.mark.asyncio
async def test_the_toggle_is_consumed_and_never_reaches_the_gateway() -> None:
    """The url4 toggle is consumed by `_wants_web_search`, never forwarded as a raw param — the
    gateway field it produces is set by the connector, not copied from the expression."""
    body = (await _bodies(_call(_NATIVE, ";web_search=true;temperature=0.2")))[0]

    assert body["web_search"] is True
    assert body["temperature"] == 0.2


# --- the declared world ----------------------------------------------------------


# SUPERSEDED (OME-797) — three tests stood here; their guarantees moved to
# `test_web_search_routing.test_mechanisms_partition_the_flag`,
# `.test_web_search_defaults_to_true`, and `.test_web_search_must_be_a_boolean`.


@pytest.mark.asyncio
async def test_a_default_on_search_route_still_honours_caller_exclusions() -> None:
    """A Tavily-loop route searches by DEFAULT, so a caller reaches the tool loop without ever
    writing `web_search=true`. Their exclusion list must still bind: a silently ignored exclusion
    is indistinguishable from an honoured one, which is the worst failure mode a privacy control
    can have."""
    client = httpx.AsyncClient(base_url="https://tavily.test")
    try:
        runtime = build_runtime(
            spec=ModelSpec(id=_TAVILY),
            wants_search=True,
            tavily_http=client,
            tavily_api_key="key",
            config=AigatewayConfig(),
            policy=None,
            params={"web_search_exclude": "evil.test"},
        )
    finally:
        await client.aclose()

    assert runtime is not None
    assert runtime.excluded_domains == ("evil.test",)

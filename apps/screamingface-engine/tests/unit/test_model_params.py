"""Expression-level model parameters reaching the gateway request body.

FEATURE: a url4 expression can pin a model call's sampling parameters —
`/judge(…)!'grade';temperature=0.2;max_tokens=8192` — and they reach aigateway.
STORY: as a benchmark author, the DRACO paper pins `judge_temperature: 0.2`
(arXiv:2602.11685 §4.2), and a judge run at the provider's default temperature
is a different benchmark from the one the paper defines.

Before this, `_ModelEndpoint.__call__` read `path`/`context`/`intent` and never
`params`, so every `;k=v` in an expression was parsed, carried to the endpoint, and
silently dropped at the wire — the run still succeeded, at the wrong temperature.

INVARIANT: the gateway is the AUTHORITY on which parameters exist and what values are
legal (`core/standard_parameters.py` + each provider's rules, which fail closed on an
unknown field). The runner keeps NO second allowlist — it rejects only the fields IT
owns, and forwards the rest for the gateway to validate.
"""

from __future__ import annotations

import json

import httpx
import pytest

from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world_config import ModelSpec
from url4.core.errors import ResolutionError

_MODEL = "openrouter/google/gemini-3.1-pro-preview"
_TAVILY_MODEL = "google/gemini-3.1-pro-preview"
"""`_MODEL` minus the OpenRouter prefix: provider `google` carries no native envelope, so a
route declared on this id takes the Tavily loop — needed by the tool-loop tests below, which
must not silently resolve to `_MODEL`'s native mechanism instead."""


# Every probe expression carries `anchor:1.0:'a'` beside the model call: with the call as the
# body's ONLY source, the all-calls rule fires the per-row reduce and `default_route` adds a
# gateway hop these assertions do not expect. One data sibling degrades it to a join.
async def _evaluate(
    expression: str, *, model: str = _MODEL, web_search: bool = False, tavily: bool = False
):
    """Run one expression against a mock gateway; return the captured request bodies."""
    bodies: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}], "usage": {}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                default_model=model, models=(ModelSpec(id=model, web_search=web_search),)
            ),
            client=client,
            tavily_client=client if tavily else None,
            tavily_api_key="tv-key" if tavily else None,
        )
        try:
            await world.node.evaluate(expression)
        finally:
            await world.aclose()
    return bodies


# --- the parameters reach the wire, correctly typed ------------------------------


@pytest.mark.asyncio
async def test_temperature_reaches_the_request_body_as_a_number() -> None:
    """INVARIANT: coerced, not passed through as text.

    url4 hands params over as `Mapping[str, str]`, but the gateway's schemas are strictly
    typed — `isinstance(v, (int, float)) and not isinstance(v, bool)` — so the string
    "0.2" fails closed against `TEMPERATURE_SCHEMA`. A forwarded parameter that the
    gateway then rejects is no better than a dropped one.
    """
    bodies = await _evaluate(
        f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade';temperature=0.2,anchor:1.0:'a')!'go'"
    )

    assert bodies[0]["temperature"] == 0.2
    assert isinstance(bodies[0]["temperature"], float)


@pytest.mark.asyncio
async def test_max_tokens_reaches_the_request_body_as_an_integer() -> None:
    """Integer-valued URL4 parameters must remain integers at the Gateway boundary."""
    bodies = await _evaluate(
        f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade';max_tokens=8192,anchor:1.0:'a')!'go'"
    )

    assert bodies[0]["max_tokens"] == 8192
    assert isinstance(bodies[0]["max_tokens"], int)


@pytest.mark.asyncio
async def test_an_enum_valued_parameter_stays_a_string() -> None:
    """Coercion must not mangle a value the gateway expects as text: `stop` is a
    `string | array[string]` union, and an enum ladder like `reasoning_effort` is a
    plain string. Only JSON-shaped values become JSON."""
    bodies = await _evaluate(f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade';stop=END,anchor:1.0:'a')!'go'")

    assert bodies[0]["stop"] == "END"


@pytest.mark.asyncio
async def test_several_parameters_are_all_forwarded() -> None:
    bodies = await _evaluate(
        f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade';temperature=0.2;max_tokens=8192;seed=7,anchor:1.0:'a')!'go'"
    )

    assert bodies[0]["temperature"] == 0.2
    assert bodies[0]["max_tokens"] == 8192
    assert bodies[0]["seed"] == 7


@pytest.mark.asyncio
async def test_no_parameters_leaves_the_body_untouched() -> None:
    """A call with no `;k=v` chain must send exactly what it always sent — no phantom
    keys the gateway would then have to classify."""
    bodies = await _evaluate(f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade',anchor:1.0:'a')!'go'")

    assert set(bodies[0]) == {"model", "messages"}


# --- the fields the RUNNER owns --------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["model", "messages", "tools", "tool_choice", "stream", "web_search_excluded_domains"],
)
@pytest.mark.asyncio
async def test_a_runner_owned_field_is_rejected(field: str) -> None:
    """INVARIANT: these are the runner's, not the caller's, and rejection is LOUD.

    `model` would let an expression address one route and run another model, breaking the
    "route path is exactly '/' + gateway id" invariant that `url4.json` and
    `test_declared_models_match_aigateway.py` exist to hold. `tools`/`tool_choice` would
    bypass the route's own resolved mechanism (`ModelSpec.uses_web_tools`) that keeps a
    configured Tavily key from silently changing every model's payload. `stream` would break
    response parsing.

    Dropping them silently would be worse than forwarding them: the expression would read
    as though it had pinned something it had not.
    """
    with pytest.raises(ResolutionError, match=field):
        await _evaluate(f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade';{field}=x,anchor:1.0:'a')!'go'")


@pytest.mark.asyncio
async def test_an_unknown_parameter_is_forwarded_for_the_gateway_to_judge() -> None:
    """The runner keeps no allowlist: enabling a parameter must stay a gateway-local edit.

    The gateway fails closed on an unknown field ("unsupported chat parameters: …"), so a
    typo surfaces there with a named 400 rather than being swallowed here — one authority,
    no drift.
    """
    bodies = await _evaluate(
        f"(v:1.0:/{_MODEL}(a:1.0:'x')!'grade';not_a_real_param=1,anchor:1.0:'a')!'go'"
    )

    assert bodies[0]["not_a_real_param"] == 1


# --- interaction with the web-tool loop ------------------------------------------


@pytest.mark.asyncio
async def test_web_tools_still_win_over_a_caller_supplied_payload() -> None:
    """The route's resolved tools must be what ships, on a route whose mechanism is Tavily."""
    bodies = await _evaluate(
        f"(v:1.0:/{_TAVILY_MODEL}(a:1.0:'x')!'grade';temperature=0.2,anchor:1.0:'a')!'go'",
        model=_TAVILY_MODEL,
        web_search=True,
        tavily=True,
    )

    assert bodies[0]["temperature"] == 0.2
    assert bodies[0]["tool_choice"] == "auto"
    assert isinstance(bodies[0]["tools"], list)


@pytest.mark.asyncio
async def test_parameters_apply_to_every_round_trip_of_the_tool_loop() -> None:
    """A tool-calling turn re-posts; sampling parameters must hold on each hop, or the
    answer is produced under different settings from the ones the expression pinned."""
    calls: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/chat/completions"):
            calls.append(json.loads(request.content))
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "c1",
                                            "type": "function",
                                            "function": {
                                                "name": "web_search",
                                                "arguments": '{"query": "x"}',
                                            },
                                        }
                                    ],
                                }
                            }
                        ],
                        "usage": {},
                    },
                )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "FINAL"}}], "usage": {}}
            )
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                default_model=_TAVILY_MODEL,
                models=(ModelSpec(id=_TAVILY_MODEL, web_search=True),),
            ),
            client=client,
            tavily_client=client,
            tavily_api_key="tv-key",
        )
        try:
            await world.node.evaluate(
                f"(v:1.0:/{_TAVILY_MODEL}(a:1.0:'x')!'grade';temperature=0.2,anchor:1.0:'a')!'go'"
            )
        finally:
            await world.aclose()

    assert len(calls) == 2
    assert [c["temperature"] for c in calls] == [0.2, 0.2]

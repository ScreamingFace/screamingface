"""A model id with a colon on the tools path, end to end (tool-calls §3.2).

FEATURE: tool-calls §3.2. A gateway id with a colon is written with `~` in a route
(`prov/c:free` has the route id `prov/c~free`). The final-step route of such a model is registered
under the `~` path, the re-point of a recipe that names `/prov/c~free` reaches it, and the one
final-step request carries the decoded id. Through the HTTP route, the recipe and each accepted
spelling of the bare id schedule a recipe that runs this way.
"""

from __future__ import annotations

import tomllib
from typing import Any

import httpx
import pytest
from _chat_app import ToolCatalog, answered, body, chat_app, post, stored_record
from _chat_final_world import (
    INPUT_MESSAGES,
    TOOL,
    Reply,
    ToolGateway,
    call_final,
    final_route,
    final_turn,
    tool_call,
    tools_world,
)
from _chat_tools_reachable import tools_reachable  # noqa: F401
from _chat_world import chat_store, ingest_chat_input, run_turn

from screamingface_engine.chat import wire
from screamingface_engine.chat.recipe import FINAL_STEP_ROUTE, one_model_recipe
from screamingface_engine.chat.result import ChatResult
from screamingface_engine.world.config import ModelSpec, parse_config
from screamingface_engine.world.factory import build_world, direct_mount_paths
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from url4.peer.server import Url4Node

pytestmark = pytest.mark.asyncio

REAL = "prov/c:free"
ROUTE = "prov/c~free"
RECIPE = f"(model_1:0.0:/{ROUTE}($input)!'Answer with the tools.')!'$model_1'"
CALLS = [tool_call("call_1"), tool_call("call_2", arguments='{"city":"Rome"}')]


def _gateway() -> ToolGateway:
    return ToolGateway(
        {REAL: Reply(content=None, tool_calls=CALLS, finish_reason="tool_calls"), "m": Reply()}
    )


def _dumped(calls: list[wire.ToolCall]) -> list[dict[str, Any]]:
    return [call.model_dump(mode="json", exclude_unset=True) for call in calls]


async def _turn(recipe: str) -> tuple[ChatResult, ToolGateway]:
    gateway = _gateway()
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])
    models = (ModelSpec(id=ROUTE, web_search=False), ModelSpec(id="m", web_search=False))
    async with tools_world(gateway, models=models) as node:
        result = await run_turn(node, recipe, ref, reader)
    return result, gateway


def _assert_one_final_request(result: ChatResult, gateway: ToolGateway) -> None:
    (sent,) = gateway.seen
    assert sent["model"] == REAL
    assert sent["tools"] == [TOOL]
    assert result.status == "answered"
    assert _dumped(result.tool_calls) == CALLS
    assert result.finish_reason == "tool_calls"
    assert result.final_step is not None
    assert result.final_step.binding == "model_1"
    assert result.final_step.model == REAL


@pytest.mark.parametrize("model", [REAL, ROUTE])
async def test_final_route_helper_takes_either_form(model: str) -> None:
    assert final_route(model) == FINAL_STEP_ROUTE + "/" + ROUTE


async def test_final_route_of_a_colon_id_is_registered_under_the_tilde_path() -> None:
    declared = f'[aigateway]\ndefault_route = "/m"\nmodels = ["m", "{ROUTE}"]\n'
    config = parse_config(tomllib.loads(declared), {}, registry=EMPTY_MODEL_WORLD)
    gateway = _gateway()
    transport = httpx.MockTransport(gateway.handle)
    async with httpx.AsyncClient(transport=transport, base_url="http://aigateway.test") as client:
        node, aclose = await build_world(env={}, config=config, client=client)
        assert aclose is not None
        try:
            assert isinstance(node, Url4Node)
            path = FINAL_STEP_ROUTE + "/" + ROUTE
            assert path in node.processor_routes()
            assert path not in direct_mount_paths(node)
            await call_final(node, ROUTE, turn=final_turn())
        finally:
            await aclose()

    (sent,) = gateway.seen
    assert sent["model"] == REAL
    assert sent["tools"] == [TOOL]


@pytest.mark.parametrize(
    "recipe",
    [
        pytest.param(RECIPE, id="recipe-names-the-tilde-route"),
        pytest.param(one_model_recipe(REAL), id="one-model-recipe"),
    ],
)
async def test_a_turn_with_tools_sends_one_final_request_with_the_decoded_id(recipe: str) -> None:
    result, gateway = await _turn(recipe)

    _assert_one_final_request(result, gateway)


@pytest.mark.parametrize(
    ("model", "scheduled"),
    [
        pytest.param(RECIPE, RECIPE, id="recipe"),
        pytest.param(REAL, one_model_recipe(REAL), id="colon-id"),
        pytest.param(ROUTE, one_model_recipe(REAL), id="tilde-id"),
    ],
)
async def test_the_http_route_schedules_a_recipe_that_reaches_the_final_route(
    model: str, scheduled: str
) -> None:
    ca = chat_app(answered(), known=(REAL, ROUTE), catalog=ToolCatalog({REAL: ["tools"]}))

    resp = await post(ca.app, body(model, tools=[TOOL]))

    assert resp.status_code == 200
    (run,) = ca.runner.scheduled
    assert run["url4"] == scheduled
    assert stored_record(ca.runner.inputs[0])["tools"] == [TOOL]
    result, gateway = await _turn(run["url4"])
    _assert_one_final_request(result, gateway)

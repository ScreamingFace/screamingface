"""An argmax-by-cost Fusion runs end to end in the engine world (OME-1289 E4a gap-closure, 10E).

FEATURE: the cheapest member's text is the answer; the cost of each member comes from the model
call that made it, found by the call's fingerprint (path and params).
STORY: as a researcher, I see ``cost_usd`` and its order on ``op_synthesis_1`` and the three costs
on the member rows, and the Fusion answers with the cheapest member's own text.
INVARIANT defended: the signal numbers reach the combine core through the route adapter. If any
number is None here, the adapter or the connector lost a call's accounting (a unit 1 or 7 defect).
The catalog lists the four signal operators with exactly the published schemas.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from combine_signal_support import argmax_spec
from combine_support import spec_text

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text

_MODELS = ("provider/alpha", "provider/beta", "provider/gamma")
_COSTS = {"provider/alpha": "0.004", "provider/beta": "0.001", "provider/gamma": "0.002"}


def _answer(model: str) -> str:
    return f"{model.rpartition('/')[2]} says: the answer is 42"


def _cost(amount: str) -> dict[str, str]:
    return {"status": "reported", "amount": amount, "unit": "openrouter_credits", "source": "x"}


def _attempt(tokens: tuple[int, int], latency_ms: int, cost: str) -> dict[str, Any]:
    return {
        "outcome": "succeeded",
        "provider": "openrouter",
        "response_model": "m",
        "latency_ms": latency_ms,
        "usage": {"input": {"total": tokens[0]}, "output": {"total": tokens[1]}},
        "direct_cost": _cost(cost),
    }


def _miss_body(content: str, cost: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "complete",
                "omitted_attempts": 0,
                "attempts": [_attempt((10, 4), 30, cost)],
                "cache": {"status": "miss", "reference": None},
            },
            "request_economics": {
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [_cost(cost)],
            },
        },
    }


def _respond(request: httpx.Request) -> httpx.Response:
    model = json.loads(request.content)["model"]
    return httpx.Response(
        200,
        headers={"X-AIGW-Cache": "miss"},
        json=_miss_body(_answer(model), _COSTS[model]),
    )


def _fusion_context() -> str:
    call_sources = {
        f"member_{index}": {f"model_{index}": {"path": f"/{model}", "params": ""}}
        for index, model in enumerate(_MODELS, start=1)
    }
    return render(
        struct(
            {
                "input": "$input",
                "outputs": {f"member_{index}": f"$model_{index}" for index in range(1, 4)},
                "sources": call_sources,
            }
        )
    )


def _pipeline() -> str:
    members = [
        src(
            RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, model in enumerate(_MODELS, start=1)
    ]
    synthesis = src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=_fusion_context(),
            intent=Text(spec_text(argmax_spec(3, "cost_usd", "min"))),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(*members, synthesis, intent=text("$synthesis_1")))


@pytest.mark.asyncio
async def test_argmax_by_cost_answers_with_the_cheapest_member_text() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_MODELS[0], models=tuple(ModelSpec(id=m) for m in _MODELS)),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        record = await evaluate_candidate_recipe(world.node, _pipeline(), "what is it?")
    finally:
        await world.aclose()
        await client.aclose()

    decoded = decode_candidate_invocation_record(record)

    assert decoded.output == _answer("provider/beta")
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    synthesis = by_id["op_synthesis_1"]
    assert synthesis.output == _answer("provider/beta")
    assert synthesis.accounting is None
    combine = synthesis.combine
    assert combine is not None
    assert combine.signal is not None
    assert (combine.signal.key, combine.signal.order) == ("cost_usd", "min")
    assert [member.signals["cost_usd"] for member in combine.members] == [0.004, 0.001, 0.002]
    assert [member.score for member in combine.members] == [0.004, 0.001, 0.002]
    assert combine.chosen == ["member_2"]
    assert (combine.kind, combine.reducer, combine.built) == ("answer", "pick", False)


@pytest.mark.asyncio
async def test_catalog_lists_the_signal_operators() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        listed = (await client.get("/v1/operators")).json()["data"]

    by_id = {entry["id"]: entry for entry in listed}
    stages = {"by_signal@1": "reduce", "best_holder@1": "select", "filter@1": "reduce"}
    stages["kept@1"] = "select"
    assert {op_id: by_id[op_id]["stage"] for op_id in stages} == stages
    orders = {"enum": ["max", "min"]}
    assert by_id["by_signal@1"]["args_schema"] == {
        "type": "object",
        "properties": {"key": {"type": "string"}, "order": orders},
        "required": ["key", "order"],
        "additionalProperties": False,
    }
    assert by_id["best_holder@1"]["args_schema"] == {
        "type": "object",
        "properties": {"order": orders},
        "required": ["order"],
        "additionalProperties": False,
    }
    assert by_id["filter@1"]["args_schema"] == {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "cmp": {"enum": ["gt", "ge", "lt", "le", "eq"]},
                    "value": {"type": ["number", "boolean"]},
                },
                "required": ["key", "cmp", "value"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 256},
                    "ignore_case": {"type": "boolean"},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        ]
    }
    assert by_id["kept@1"]["args_schema"] == {}

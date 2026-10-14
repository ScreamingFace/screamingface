"""A quorum panel runs end to end through url4 and the gateway world (OME-1289 E4a x OME-1557).

FEATURE: three members in a broadcast ``panel_1`` (the third optional) feed one combine vote over
the built-in operators, wired like the SDK's compiled Fusion.
STORY: as a researcher, the vote answers when the optional member's provider fails, the evidence
names that member ``missing``, a quorum that is not met stops before the combine call, and a
required member that fails fails the Fusion.
INVARIANT defended: url4 enforces the quorum and the required members; the combine call reads only
the members that answered.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest
from combine_support import spec_text, vote_spec

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text
from url4.core.errors import ResolutionError

# --- QR-8 and QR-9: end to end through url4 and the gateway world -----------------------------

_ANSWERS = {
    "provider/alpha": "alpha reasons, so 12",
    "provider/beta": "beta says 12",
    "provider/gamma": "gamma says 7",
}
_VOTE = {
    "extract": {"op": "last_number@1", "args": {}},
    "normalize": {"op": "numeric@1", "args": {}},
    "reduce": {"op": "mode@1", "args": {}},
    "select": {"op": "first_holder@1", "args": {}},
}


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _responder(failing: Sequence[str]) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model in failing:
            return httpx.Response(400, json={"error": {"message": "bad"}})
        return _completion(_ANSWERS[model])

    return respond


def _candidate(quorum: int, optional: Sequence[int]) -> str:
    """The compiled shape: a broadcast panel of three members, then the combine call."""
    slots = [
        src(
            expr(
                src(
                    RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
                    name=f"model_{index}",
                    weight=0.0,
                ),
                intent=Text(f"$model_{index}"),
            ),
            name=f"member_{index}",
            weight=1.0,
            required=index not in optional,
        )
        for index, model in enumerate(_ANSWERS, start=1)
    ]
    panel = src(
        expr(*slots, intent=Text(""), broadcast=True, params={"quorum": quorum}),
        name="panel_1",
        weight=0.0,
    )
    synthesis = src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=render(struct({"input": "$input", "panel": "$panel_1"})),
            intent=Text(spec_text(vote_spec(3, **_VOTE))),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(panel, synthesis, intent=text("$synthesis_1")))


async def _evaluate(candidate: str, failing: Sequence[str]) -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_responder(failing)), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in _ANSWERS)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, candidate, "what is it?")
    finally:
        await world.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_an_optional_member_that_fails_is_missing_and_the_others_vote() -> None:
    encoded = await _evaluate(_candidate(quorum=2, optional=[3]), failing=["provider/gamma"])

    decoded = decode_candidate_invocation_record(encoded)

    assert decoded.output == _ANSWERS["provider/alpha"]
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert by_id["op_model_1"].output == _ANSWERS["provider/alpha"]
    assert by_id["op_model_3"].output is None
    combine = by_id["op_synthesis_1"].combine
    assert combine is not None
    assert [(m.member_id, m.status, m.reason) for m in combine.members] == [
        ("member_1", "answered", None),
        ("member_2", "answered", None),
        ("member_3", "fail", "missing"),
    ]
    assert combine.dropped == 1


@pytest.mark.asyncio
async def test_a_quorum_that_is_not_met_stops_before_the_combine_call() -> None:
    with pytest.raises(ResolutionError) as caught:
        await _evaluate(
            _candidate(quorum=2, optional=[2, 3]), failing=["provider/beta", "provider/gamma"]
        )

    assert caught.value.code == "quorum_not_met"


@pytest.mark.asyncio
async def test_a_required_member_that_fails_fails_the_fusion() -> None:
    with pytest.raises(ResolutionError) as caught:
        await _evaluate(_candidate(quorum=1, optional=[3]), failing=["provider/alpha"])

    assert caught.value.code is not None
    assert caught.value.code.startswith("aigateway_")

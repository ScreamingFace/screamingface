"""A final merge that finds no usable value abstains, and the case is marked (OME-1289 E4a, 9E).

FEATURE: a Merge field rule that finds no usable value does not fail the case; the combine call
answers with an abstain, and the Candidate Invocation whose final node it is carries ``abstained``.
STORY: as a benchmark grader, I see a merge that could not build its object as an abstention, so
the Case can be scored 0.0 instead of being graded as if the model had answered with nothing.
INVARIANT defended: the abstain keeps every member ``answered`` and holds no field readings; the
mark reads only the final operation's own evidence (unit 3).
"""

from __future__ import annotations

import json

import httpx
import pytest
from combine_fields_support import merge_spec
from combine_support import spec_text

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.evidence import ResultRecord
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text

_ANSWERS = {
    "provider/alpha": '{"a": 1}',
    "provider/beta": '{"a": 2}',
    "provider/gamma": '{"a": 3}',
}


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _respond(request: httpx.Request) -> httpx.Response:
    return _completion(_ANSWERS[json.loads(request.content)["model"]])


def _expression() -> str:
    """Three members, then a merge whose only rule has no usable value; it is the final node."""
    members = [
        src(
            RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, model in enumerate(_ANSWERS, start=1)
    ]
    merge = merge_spec(3, [{"field": "x", "rule": "majority", "normalize": None}])
    combine = src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=render(
                struct(
                    {
                        "input": "$input",
                        "outputs": {f"member_{n}": f"$model_{n}" for n in range(1, 4)},
                    }
                )
            ),
            intent=Text(spec_text(merge)),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(*members, combine, intent=text("$synthesis_1")))


async def _evaluate() -> str:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in _ANSWERS)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, _expression(), "what is it?")
    finally:
        await world.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_a_final_merge_that_abstains_marks_the_case() -> None:
    encoded = await _evaluate()

    decoded = decode_candidate_invocation_record(encoded)

    assert decoded.abstained is True
    assert decoded.output == ""
    assert decoded.operations is not None
    synthesis = {op.operation_id: op for op in decoded.operations}["op_synthesis_1"]
    assert synthesis.combine is not None
    assert synthesis.combine.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert synthesis.combine.fields is None
    assert [member.status for member in synthesis.combine.members] == ["answered"] * 3

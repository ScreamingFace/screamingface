"""The combine route is wired into the engine world (OME-1289 E4a, unit 3).

FEATURE: every world that runs benchmarks serves ``/ensemble/combine/v1`` with the built-in
operators, and a Candidate that uses it returns the evidence on its per-operation record.
STORY: as a reducer Candidate, I call the members, combine their answers with no model call, and
the Case result shows the tally next to each member's own output and accounting.
INVARIANT defended: the combine route is engine capability (never a direct mount, never public),
and combine evidence reaches the envelope only on the combine operation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from combine_golden_support import builtin_vote_spec
from combine_support import context_text, spec_text, vote_spec
from test_benchmark_foundation import _benchmark

from screamingface_engine.benchmarks import BenchmarkRegistry
from screamingface_engine.benchmarks.contract import (
    OperationOutput,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec, WorldConfig, parse_config
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.factory import build_world, direct_mount_paths
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from url4 import RelExpr, Text, expr, render, src, struct, text
from url4.peer.server import Url4Node

_ANSWERS = {
    "provider/alpha": "alpha reasons, so 12",
    "provider/beta": "beta says 7",
    "provider/gamma": "gamma agrees: 12.",
}


def _answer_by_model() -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": _ANSWERS[body["model"]]}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    return respond


def _reducer_expression() -> str:
    """Three member sources plus a combine synthesis, shaped like the SDK's compiled Fusion."""
    members = [
        src(
            RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, model in enumerate(_ANSWERS, start=1)
    ]
    combine_context = render(
        struct(
            {
                "input": "$input",
                "outputs": {f"member_{index}": f"$model_{index}" for index in range(1, 4)},
            }
        )
    )
    synthesis = src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=combine_context,
            intent=Text(spec_text(builtin_vote_spec(3))),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(*members, synthesis, intent=text("$synthesis_1")))


@pytest.mark.asyncio
async def test_candidate_invocation_carries_combine_evidence_end_to_end() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_answer_by_model()), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in _ANSWERS)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        encoded = await evaluate_candidate_recipe(
            world.node, _reducer_expression(), "what is the number?"
        )
    finally:
        await world.aclose()
        await client.aclose()

    decoded = decode_candidate_invocation_record(encoded)

    assert decoded.output == _ANSWERS["provider/alpha"]
    assert decoded.finish_reason == "stop"
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert list(by_id) == ["op_model_1", "op_model_2", "op_model_3", "op_synthesis_1"]
    _assert_members_keep_output_and_accounting(by_id)
    _assert_synthesis_carries_the_tally(by_id["op_synthesis_1"])


def _assert_members_keep_output_and_accounting(by_id: dict[str, OperationOutput]) -> None:
    """EV-H3: the members' own records are untouched, and carry no combine evidence."""
    for index, model in enumerate(_ANSWERS, start=1):
        member = by_id[f"op_model_{index}"]
        assert member.output == _ANSWERS[model]
        assert member.accounting is not None
        assert member.accounting.usage.input_tokens == 4
        assert member.combine is None


def _assert_synthesis_carries_the_tally(synthesis: OperationOutput) -> None:
    assert synthesis.output == _ANSWERS["provider/alpha"]
    assert synthesis.accounting is None
    assert synthesis.combine is not None
    assert synthesis.combine.chosen == ["member_1"]
    assert synthesis.combine.agreement == pytest.approx(2 / 3)
    assert synthesis.combine.tally is not None
    assert [(row.value, row.score, row.holders) for row in synthesis.combine.tally] == [
        ("12", 2.0, ["member_1", "member_3"]),
        ("7", 1.0, ["member_2"]),
    ]


# --- FW-12 ------------------------------------------------------------------------------------

_AIGATEWAY = """
[aigateway]
default_route = "/m"
models = ["m"]
"""


def _world_config() -> WorldConfig:
    import tomllib

    return parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)


def _plain_vote_spec() -> dict[str, object]:
    return vote_spec(
        3,
        extract={"op": "whole@1", "args": {}},
        normalize={"op": "identity@1", "args": {}},
        reduce={"op": "mode@1", "args": {}},
        select={"op": "first_holder@1", "args": {}},
    )


@pytest.mark.asyncio
async def test_build_world_installs_the_combine_route(tmp_path: Path) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_answer_by_model()), base_url="http://aigateway.test"
    ) as client:
        node, aclose = await build_world(
            env={},
            config=_world_config(),
            client=client,
            benchmarks=BenchmarkRegistry((_benchmark(),)),
            benchmark_assets_root=tmp_path,
        )
        assert aclose is not None
        try:
            assert isinstance(node, Url4Node)
            assert COMBINE_ROUTE in node.processor_routes()
            assert COMBINE_ROUTE not in direct_mount_paths(node)
            expression = render(
                expr(
                    src(text(context_text(["Paris", "Lyon", "Paris"])), name="ctx", weight=0.0),
                    RelExpr(
                        path=COMBINE_ROUTE,
                        context="$ctx",
                        intent=Text(spec_text(_plain_vote_spec())),
                        params=(("binding", "synthesis_1"),),
                    ),
                    intent=Text(""),
                )
            )
            result = await node.evaluate(expression)
        finally:
            await aclose()

    # The built-in operators were passed in: the vote needs whole@1, identity@1 and the rest.
    assert result.text == "Paris"


@pytest.mark.asyncio
async def test_a_world_without_benchmarks_has_no_combine_route() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_answer_by_model()), base_url="http://aigateway.test"
    ) as client:
        node, aclose = await build_world(env={}, config=_world_config(), client=client)
        assert aclose is not None
        try:
            assert isinstance(node, Url4Node)
            assert COMBINE_ROUTE not in node.processor_routes()
        finally:
            await aclose()

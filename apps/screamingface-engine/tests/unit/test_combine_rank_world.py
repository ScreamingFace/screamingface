"""A rank Fusion runs end to end in the engine world, then a model writes (OME-1289 E4a, unit 10).

FEATURE: the rank step keeps k original member texts, and the Pipeline stage after it receives that
selection and nothing else from the panel.
STORY: as a researcher, I see the judge's raw scores on ``op_judge_1``, the parsed scores of all
four members and the kept ids on ``op_synthesis_1``, and the writer gets exactly the selection JSON.
INVARIANT defended (RK-D3): the next stage's context is the selection JSON only -- never a member
text that was cut, and never a ``$model_N`` reference. The judge's ``binding`` param never reaches
the gateway.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from combine_selection_support import concat_spec, rank_spec
from combine_support import spec_text

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.ports import canonical_json
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text

_MEMBER_MODELS = ("provider/alpha", "provider/beta", "provider/gamma", "provider/delta")
_WRITER = "provider/writer"
_FINAL = "the final answer"
_PROMPT = "Write the final answer from these drafts."
_TEMPLATE = "judge-template@1 returns=scores. Score every draft."
_SCORES = {"member_1": 0.1, "member_2": 0.8, "member_3": 0.3, "member_4": 0.9}
_JUDGE_REPLY = canonical_json(_SCORES)


def _answer(model: str) -> str:
    return f'{model.rpartition("/")[2]} says: $model_1 and café "quoted"\nline two'


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _responder(seen: list[dict[str, Any]], judge_reply: str) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        first = body["messages"][0]
        if first["role"] == "system" and first["content"].startswith("judge-template@1"):
            return _completion(judge_reply)
        if body["model"] == _WRITER:
            return _completion(_FINAL)
        return _completion(_answer(body["model"]))

    return respond


def _fusion_context(*, with_judge: bool) -> str:
    body: dict[str, Any] = {
        "input": "$input",
        "outputs": {f"member_{index}": f"$model_{index}" for index in range(1, 5)},
    }
    if with_judge:
        body["signals"] = {"judge": "$judge_1"}
    return render(struct(body))


def _pipeline(synthesis_spec: dict[str, Any], *, judged: bool) -> str:
    """Four members, an optional judge, the combine synthesis, then the writer (the SDK shape)."""
    members = [
        src(
            RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, model in enumerate(_MEMBER_MODELS, start=1)
    ]
    sources = list(members)
    if judged:
        sources.append(
            src(
                RelExpr(
                    path="/provider/alpha",
                    context=_fusion_context(with_judge=False),
                    intent=Text(_TEMPLATE),
                    params=(("binding", "judge_1"),),
                ),
                name="judge_1",
                weight=0.0,
            )
        )
    sources.append(
        src(
            RelExpr(
                path=COMBINE_ROUTE,
                context=_fusion_context(with_judge=judged),
                intent=Text(spec_text(synthesis_spec)),
                params=(("binding", "synthesis_1"),),
            ),
            name="synthesis_1",
            weight=0.0,
        )
    )
    sources.append(
        src(
            RelExpr(path=f"/{_WRITER}", context="$synthesis_1", intent=text(_PROMPT)),
            name="model_5",
            weight=0.0,
        )
    )
    return render(expr(*sources, intent=text("$model_5")))


async def _evaluate(expression: str, seen: list[dict[str, Any]], judge_reply: str) -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_responder(seen, judge_reply)),
        base_url="http://aigateway.test",
    )
    models = (*_MEMBER_MODELS, _WRITER)
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in models)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, expression, "what is it?")
    finally:
        await world.aclose()
        await client.aclose()


def _writer_call(seen: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [body for body in seen if body["model"] == _WRITER]
    assert len(calls) == 1
    return calls[0]


def _assert_rank_evidence(synthesis: Any, selection: str) -> None:
    """The synthesis record holds the selection JSON, no accounting, and the judge's parse."""
    assert synthesis.output == selection
    assert synthesis.accounting is None
    combine = synthesis.combine
    assert combine is not None
    assert combine.kind == "selection"
    assert combine.chosen == ["member_4", "member_2"]
    assert combine.built is True
    assert combine.presentation_order == "author"
    assert combine.judge is not None
    assert combine.judge.parsed == _SCORES
    assert [member.score for member in combine.members] == [0.1, 0.8, 0.3, 0.9]


@pytest.mark.asyncio
async def test_rank_keeps_judge_output_and_next_stage_sees_selection_only() -> None:
    """RK-9 and RK-4 (engine half): the writer's user message is the selection JSON, exactly."""
    seen: list[dict[str, Any]] = []
    expression = _pipeline(rank_spec(4, 2), judged=True)

    decoded = decode_candidate_invocation_record(await _evaluate(expression, seen, _JUDGE_REPLY))

    selection = canonical_json(
        {
            "selected": [
                {"id": "member_4", "text": _answer("provider/delta")},
                {"id": "member_2", "text": _answer("provider/beta")},
            ]
        }
    )
    writer = _writer_call(seen)
    assert writer["messages"] == [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": selection},
    ]
    assert decoded.output == _FINAL
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert list(by_id) == [
        "op_model_1",
        "op_model_2",
        "op_model_3",
        "op_model_4",
        "op_judge_1",
        "op_synthesis_1",
        "op_model_5",
    ]
    assert by_id["op_judge_1"].output == _JUDGE_REPLY
    assert by_id["op_judge_1"].accounting is not None
    _assert_rank_evidence(by_id["op_synthesis_1"], selection)
    # The cut members never reach the writer, and the judge's attribution param never leaves.
    for dropped in ("provider/alpha", "provider/gamma"):
        assert _answer(dropped) not in json.dumps(writer)
    assert all("binding" not in body for body in seen)


@pytest.mark.asyncio
async def test_concat_makes_no_model_call_and_next_stage_sees_the_joined_text_only() -> None:
    """CC-1 and CC-2 in the world: the combine step is no gateway call; the writer gets the join."""
    seen: list[dict[str, Any]] = []
    expression = _pipeline(concat_spec(4), judged=False)

    decoded = decode_candidate_invocation_record(await _evaluate(expression, seen, _JUDGE_REPLY))

    joined = "\n\n---\n\n".join(
        f"[member_{index}]\n{_answer(model)}" for index, model in enumerate(_MEMBER_MODELS, 1)
    )
    assert _writer_call(seen)["messages"][-1] == {"role": "user", "content": joined}
    assert [body["model"] for body in seen].count(_WRITER) == 1
    assert len(seen) == len(_MEMBER_MODELS) + 1  # four members and the writer; nothing for concat
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert by_id["op_synthesis_1"].output == joined
    assert by_id["op_synthesis_1"].accounting is None
    combine = by_id["op_synthesis_1"].combine
    assert combine is not None
    assert combine.kind == "selection"
    assert combine.chosen == [f"member_{index}" for index in range(1, 5)]
    assert combine.separator_collision is False
    assert combine.judge is None
    assert combine.presentation_order is None


async def _get(app: Any, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_catalog_lists_the_selection_operators() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    listed = (await _get(app, "/v1/operators")).json()["data"]

    by_id = {entry["id"]: entry for entry in listed}
    assert {"top_k@1": "select", "join@1": "reduce", "all@1": "select"}.items() <= {
        op_id: entry["stage"] for op_id, entry in by_id.items()
    }.items()
    assert by_id["top_k@1"]["args_schema"]["properties"] == {
        "k": {"type": "integer", "minimum": 1, "maximum": 256},
        "order": {"enum": ["max", "min"]},
    }
    assert by_id["top_k@1"]["args_schema"]["required"] == ["k"]
    assert by_id["join@1"]["args_schema"]["required"] == ["separator", "label"]
    assert by_id["all@1"]["args_schema"] == {}

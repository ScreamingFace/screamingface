"""A judge Candidate runs end to end in the engine world (OME-1289 E4a, unit 8).

FEATURE: a judge model call and the combine step that reads its reply, wired in one url4 expression
shaped like the SDK's compiled Fusion.
STORY: as a researcher, the Report shows the judge's raw reply on ``op_judge_1``, the parsed label
on ``op_synthesis_1``, and the chosen member's own text as the answer -- even when the judge runs
on the same model route as a member.
INVARIANT defended: the ``binding`` param keeps the judge call's attribution apart from a member on
the same route, and it never reaches the gateway. A provider failure of the judge keeps its own
code and never becomes ``judge_reply_invalid``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from combine_flow_support import judge_spec
from combine_support import spec_text, vote_spec

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
from url4.core.errors import ResolutionError

_ANSWERS = {
    "provider/alpha": "alpha reasons, so 12",
    "provider/beta": "beta says 7",
    "provider/gamma": "gamma agrees: 12.",
}
_TEMPLATE = "judge-template@1 returns=label. Pick the most correct answer."


def _completion(content: str | None, *, refusal: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": content, "refusal": refusal},
                    "finish_reason": "content_filter" if refusal else "stop",
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _is_judge_call(body: dict[str, Any]) -> bool:
    first = body["messages"][0]
    return first["role"] == "system" and first["content"].startswith("judge-template@1")


def _answering(
    judge: Callable[[], httpx.Response], seen: list[dict[str, Any]]
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if _is_judge_call(body):
            return judge()
        return _completion(_ANSWERS[body["model"]])

    return respond


def _fusion_context(*, with_judge: bool) -> str:
    body: dict[str, Any] = {
        "input": "$input",
        "outputs": {f"member_{index}": f"$model_{index}" for index in range(1, 4)},
    }
    if with_judge:
        body["signals"] = {"judge": "$judge_1"}
    return render(struct(body))


def _expression(
    judge_path: str, *, spec: dict[str, Any] | None = None, template: str = _TEMPLATE
) -> str:
    """Three members, a judge on ``judge_path``, and the combine synthesis (the compiled shape)."""
    members = [
        src(
            RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, model in enumerate(_ANSWERS, start=1)
    ]
    judge = src(
        RelExpr(
            path=judge_path,
            context=_fusion_context(with_judge=False),
            intent=Text(template),
            params=(("binding", "judge_1"),),
        ),
        name="judge_1",
        weight=0.0,
    )
    synthesis = src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=_fusion_context(with_judge=True),
            intent=Text(spec_text(judge_spec(3, "label") if spec is None else spec)),
            params=(("binding", "synthesis_1"),),
        ),
        name="synthesis_1",
        weight=0.0,
    )
    return render(expr(*members, judge, synthesis, intent=text("$synthesis_1")))


async def _evaluate(
    responder: Callable[[httpx.Request], httpx.Response],
    judge_path: str,
    *,
    spec: dict[str, Any] | None = None,
    template: str = _TEMPLATE,
) -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in _ANSWERS)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        expression = _expression(judge_path, spec=spec, template=template)
        return await evaluate_candidate_recipe(world.node, expression, "what is it?")
    finally:
        await world.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_judge_on_a_member_route_keeps_both_operations() -> None:
    """EV-H3 and JG-10: the judge shares alpha's route with a member, and both records survive."""
    seen: list[dict[str, Any]] = []
    encoded = await _evaluate(_answering(lambda: _completion("member_3"), seen), "/provider/alpha")

    decoded = decode_candidate_invocation_record(encoded)

    assert decoded.output == _ANSWERS["provider/gamma"]
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert list(by_id) == ["op_model_1", "op_model_2", "op_model_3", "op_judge_1", "op_synthesis_1"]
    assert by_id["op_model_1"].output == _ANSWERS["provider/alpha"]
    assert by_id["op_model_1"].accounting is not None
    assert by_id["op_judge_1"].output == "member_3"
    assert by_id["op_judge_1"].accounting is not None
    assert by_id["op_synthesis_1"].output == _ANSWERS["provider/gamma"]
    assert by_id["op_synthesis_1"].accounting is None
    combine = by_id["op_synthesis_1"].combine
    assert combine is not None
    assert combine.judge is not None
    assert combine.judge.parsed == "member_3"
    assert combine.judge.raw == "member_3"
    assert combine.presentation_order == "author"
    assert combine.chosen == ["member_3"]
    # The judge call reached the gateway, and no body carried the attribution-only param.
    assert sum(_is_judge_call(body) for body in seen) == 1
    assert all("binding" not in body for body in seen)


@pytest.mark.asyncio
async def test_judge_refusal_keeps_its_own_outcome_and_records_no_combine() -> None:
    """JG-9 (a): the judge model refuses, so the case is refused and no combine evidence exists."""
    seen: list[dict[str, Any]] = []
    responder = _answering(lambda: _completion(None, refusal="safety policy"), seen)

    decoded = decode_candidate_invocation_record(await _evaluate(responder, "/provider/alpha"))

    assert decoded.status == "refused"
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert by_id["op_synthesis_1"].combine is None
    assert by_id["op_judge_1"].finish_reason == "content_filter"


@pytest.mark.asyncio
async def test_judge_provider_failure_keeps_existing_code() -> None:
    """JG-9 (b): an HTTP 400 on the judge route keeps its gateway code."""
    seen: list[dict[str, Any]] = []
    responder = _answering(lambda: httpx.Response(400, json={"error": {"message": "bad"}}), seen)

    with pytest.raises(ResolutionError) as caught:
        await _evaluate(responder, "/provider/alpha")

    assert caught.value.code is not None
    assert caught.value.code.startswith("aigateway_")
    assert caught.value.code != "judge_reply_invalid"


@pytest.mark.asyncio
async def test_prose_from_the_judge_model_fails_the_case_with_judge_reply_invalid() -> None:
    """JG-3 end to end: a judge model that answers in prose fails the case, not a fallback."""
    seen: list[dict[str, Any]] = []
    responder = _answering(lambda: _completion("I think member 2 is best."), seen)

    with pytest.raises(ResolutionError) as caught:
        await _evaluate(responder, "/provider/alpha")

    assert caught.value.code == "judge_reply_invalid"
    assert caught.value.permanent is True
    assert "member 2 is best" not in str(caught.value)
    # One judge call for each case: a parse failure is not retried (PRD section 4).
    assert sum(_is_judge_call(body) for body in seen) == 1


async def _get(app: Any, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_catalog_lists_the_judge_operators() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    listed = (await _get(app, "/v1/operators")).json()["data"]

    stages = {entry["id"]: entry["stage"] for entry in listed}
    assert {
        "label@1": "reduce",
        "scores@1": "reduce",
        "by_label@1": "select",
        "max_score@1": "select",
    }.items() <= stages.items()


@pytest.mark.asyncio
async def test_vote_weighted_by_judge_scores_in_the_engine_world() -> None:
    """SR#11: the judge reply is read as score:judge, so it weights a vote; no judge evidence."""
    spec = vote_spec(
        3,
        extract={"op": "last_number@1", "args": {}},
        normalize={"op": "numeric@1", "args": {}},
        reduce={"op": "weighted_mode@1", "args": {}},
        select={"op": "max_weight_holder@1", "args": {}},
        weights={"signal": "score:judge"},
    )
    reply = '{"member_1": 1, "member_2": 5, "member_3": 3}'
    answers = {"provider/alpha": "alpha says 12", "provider/beta": "beta says 7"}
    answers["provider/gamma"] = "gamma says 12"
    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return _completion(reply if _is_judge_call(body) else answers[body["model"]])

    encoded = await _evaluate(
        respond,
        "/provider/alpha",
        spec=spec,
        template="judge-template@1 returns=scores. Score each answer.",
    )

    decoded = decode_candidate_invocation_record(encoded)
    assert decoded.output == "beta says 7"
    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    combine = by_id["op_synthesis_1"].combine
    assert combine is not None
    assert combine.tally is not None
    assert [(r.value, r.score, r.holders) for r in combine.tally] == [
        ("7", 5.0, ["member_2"]),
        ("12", 4.0, ["member_1", "member_3"]),
    ]
    assert [m.signals["score:judge"] for m in combine.members] == [1.0, 5.0, 3.0]
    assert combine.judge is None
    assert by_id["op_judge_1"].output == reply
    assert sum(_is_judge_call(body) for body in seen) == 1
    assert all("binding" not in body for body in seen)

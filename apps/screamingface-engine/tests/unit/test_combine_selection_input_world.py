"""The selection envelope in the engine world, for a Fusion that is not first (E4b unit 1).

FEATURE (ans:Q7, SI-D2, SI-D5): the ``input`` of a Rank envelope is the input of THAT Fusion, and
any stage that reads the selection gets the envelope as its context, a Fusion stage too.
STORY: as a benchmark author, a Rank after a drafting model hands the writer the draft (the Fusion's
input), not the Case question; I put the Case question into the drafter's answer if I need it.
INVARIANT defended: the engine adds no special case for the stage position or the next stage kind.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from combine_selection_support import rank_spec
from combine_support import spec_text

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.ports import canonical_json
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text

_CASE = "what is it?"
_DRAFTER = "provider/drafter"
_MEMBERS = ("provider/alpha", "provider/beta", "provider/gamma")
_NEXT = ("provider/next-1", "provider/next-2")
_SYNTH = "provider/synth"
_DRAFT = "DRAFT: what is 6*7?"
_TEMPLATE = "judge-template@1 returns=scores. Score every draft."
_JUDGE_REPLY = canonical_json({"member_1": 0.2, "member_2": 0.9, "member_3": 0.5})


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _reply(body: dict[str, Any]) -> str:
    first = body["messages"][0]
    if first["role"] == "system" and first["content"].startswith("judge-template@1"):
        return _JUDGE_REPLY
    if body["model"] == _DRAFTER:
        return _DRAFT
    return f"{body['model']} answer"


def _responder(seen: list[dict[str, Any]]) -> Any:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return _completion(_reply(body))

    return respond


def _model(path: str, context: str, name: str, prompt: str = "Answer plainly.") -> Any:
    return src(
        RelExpr(path=f"/{path}", context=context, intent=text(prompt)), name=name, weight=0.0
    )


def _panel(first: int, count: int, *, judge: bool) -> str:
    """The Fusion context: the Fusion input is the drafter's answer, not ``$input``."""
    body: dict[str, Any] = {
        "input": "$model_1",
        "outputs": {f"member_{i}": f"$model_{first + i - 1}" for i in range(1, count + 1)},
    }
    if judge:
        body["signals"] = {"judge": "$judge_1"}
    return render(struct(body))


def _rank_sources() -> list[Any]:
    """A drafter (model_1), then a Rank Fusion over three members (model_2..4) that reads it."""
    sources = [_model(_DRAFTER, "$input", "model_1", "Rewrite the request.")]
    sources += [
        _model(model, "$model_1", f"model_{index}") for index, model in enumerate(_MEMBERS, 2)
    ]
    sources.append(
        src(
            RelExpr(
                path="/provider/alpha",
                context=_panel(2, 3, judge=False),
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
                context=_panel(2, 3, judge=True),
                intent=Text(spec_text(rank_spec(3, 2))),
                params=(("binding", "synthesis_1"),),
            ),
            name="synthesis_1",
            weight=0.0,
        )
    )
    return sources


async def _evaluate(expression: str, seen: list[dict[str, Any]]) -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_responder(seen)), base_url="http://aigateway.test"
    )
    models = (_DRAFTER, *_MEMBERS, *_NEXT, _SYNTH)
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_DRAFTER, models=tuple(ModelSpec(id=m) for m in models)),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, expression, _CASE)
    finally:
        await world.aclose()
        await client.aclose()


def _user_messages(seen: list[dict[str, Any]], model: str) -> list[str]:
    return [body["messages"][-1]["content"] for body in seen if body["model"] == model]


# The envelope both tests expect: member_2 (beta, 0.9) then member_3 (gamma, 0.5), and the input is
# the drafter's answer -- the input of the Fusion -- not the Case question "what is it?".
_ENVELOPE = (
    '{"input":"DRAFT: what is 6*7?","selected":'
    '[{"id":"member_2","text":"provider/beta answer"},'
    '{"id":"member_3","text":"provider/gamma answer"}]}'
)


# --- SI#9 SI-D2 ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_envelope_input_is_the_fusion_input_in_a_later_stage() -> None:
    seen: list[dict[str, Any]] = []
    sources = [*_rank_sources(), _model(_NEXT[0], "$synthesis_1", "model_5", "Write it.")]

    decoded = decode_candidate_invocation_record(
        await _evaluate(render(expr(*sources, intent=text("$model_5"))), seen)
    )

    assert _user_messages(seen, _DRAFTER) == [_CASE]
    assert _user_messages(seen, _NEXT[0]) == [_ENVELOPE]
    assert decoded.output == "provider/next-1 answer"


# --- SI#12 SI-D5 --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selection_feeding_a_fusion_stage_gets_the_envelope() -> None:
    seen: list[dict[str, Any]] = []
    synth_context = render(
        struct(
            {"input": "$synthesis_1", "outputs": {"member_1": "$model_5", "member_2": "$model_6"}}
        )
    )
    sources = [
        *_rank_sources(),
        _model(_NEXT[0], "$synthesis_1", "model_5"),
        _model(_NEXT[1], "$synthesis_1", "model_6"),
        _model(_SYNTH, synth_context, "model_7", "Combine the answers."),
    ]

    await _evaluate(render(expr(*sources, intent=text("$model_7"))), seen)

    assert _user_messages(seen, _NEXT[0]) == [_ENVELOPE]
    assert _user_messages(seen, _NEXT[1]) == [_ENVELOPE]
    assert json.loads(_user_messages(seen, _SYNTH)[0])["input"] == _ENVELOPE

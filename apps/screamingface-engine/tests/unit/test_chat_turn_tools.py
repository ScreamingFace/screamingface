"""The chat turn with tools: the re-point, the bound turn and the collector (tool-calls §3.2).

FEATURE: tool-calls. With client tools, the turn route re-points each final model step of the
run's copy of the recipe to the final-step route. The other steps keep the text view on the model
route, and the CHAT_RESULT takes its tool calls, finish_reason and final step from the collector
of the final-step endpoint (erd §2.4). With no tools, nothing changes (TC-S14).
"""

from __future__ import annotations

from typing import Any

import pytest
from _chat_final_world import (
    INPUT_MESSAGES,
    TOOL,
    Reply,
    ToolGateway,
    final_turn,
    tool_call,
    tools_world,
)
from _chat_world import FAIL, Gateway, chat_store, chat_world, ingest_chat_input, run_turn
from _gate_world import fixture

import screamingface_engine.world.chat_turn
from screamingface_engine.benchmarks.contract import (
    CandidateInvocation,
    decode_candidate_invocation_record,
)
from screamingface_engine.benchmarks.operation_outputs import final_operation
from screamingface_engine.chat import wire
from screamingface_engine.chat.recipe import (
    FINAL_STEP_ROUTE,
    CheckedRecipe,
    check_recipe,
    one_model_recipe,
)
from screamingface_engine.chat.result import FinalStep
from screamingface_engine.chat.views import TOOLS_NOTE
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.world.chat_turn import tools_expression
from url4 import RelExpr, expr, render, src, text
from url4.core.errors import ResolutionError
from url4.core.nodes import Expression, Source
from url4.core.parser import build

pytestmark = pytest.mark.asyncio

MEMBER = "prov/m"
SYNTH = "prov/s"
MERGE = "Merge the answers."
HISTORY: list[dict[str, Any]] = [
    {"role": "user", "content": "Weather in Paris?"},
    {"role": "assistant", "content": None, "tool_calls": [tool_call("call_1")]},
    {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 21 C"},
]


def _fusion() -> str:
    """Two members on one route and a model synthesizer on another (TC-S2)."""
    return render(
        expr(
            src(
                RelExpr(path="/" + MEMBER, context="$input", intent=text("Answer A")),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(path="/" + MEMBER, context="$input", intent=text("Answer B")),
                name="model_2",
                weight=0.0,
            ),
            src(
                RelExpr(path="/" + SYNTH, context="$model_1 $model_2", intent=text(MERGE)),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


def _parsed(recipe: str) -> Expression:
    root = build(recipe)
    assert isinstance(root, Expression)
    return root


def _sources(root: Expression) -> dict[str, Source]:
    return {node.name: node for node in root.sources if isinstance(node, Source) and node.name}


def _dumped(calls: list[wire.ToolCall]) -> list[dict[str, Any]]:
    return [call.model_dump(mode="json", exclude_unset=True) for call in calls]


# --- TC-13: the re-point changes only the final model sources -----------------------------------


async def test_repoint_changes_only_final_model_sources() -> None:
    fusion = _fusion()
    original, moved = _parsed(fusion), _parsed(tools_expression(fusion))

    before, after = _sources(original), _sources(moved)
    assert after["model_1"] == before["model_1"]
    assert after["model_2"] == before["model_2"]
    assert moved.intent == original.intent
    synthesis = after["synthesis_1"].value
    assert isinstance(synthesis, RelExpr)
    assert synthesis.path == FINAL_STEP_ROUTE + "/" + SYNTH
    assert ("binding", "synthesis_1") in synthesis.params
    old = before["synthesis_1"].value
    assert isinstance(old, RelExpr)
    assert (synthesis.context, synthesis.intent) == (old.context, old.intent)
    # WHY no outcome-only case: no committed Gate fixture has only outcome branches.

    reducer = render(
        expr(
            src(RelExpr(path="/prov/a", context="$input", intent=text("")), name="model_1"),
            src(
                RelExpr(path=COMBINE_ROUTE, context="$model_1", intent=text("{}")),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )
    with pytest.raises(ResolutionError) as refused:
        tools_expression(reducer)
    assert refused.value.code == "final_step_not_model"
    assert refused.value.permanent is True


# --- TC-14: a Fusion with tools --------------------------------------------------------------


async def test_fusion_with_tools_members_get_text_view_and_synthesizer_gets_tools() -> None:
    calls = [tool_call("call_1"), tool_call("call_2", arguments='{"city":"Rome"}')]
    gateway = ToolGateway(
        {
            MEMBER: Reply(content="Sunny"),
            SYNTH: Reply(content=None, tool_calls=calls, finish_reason="tool_calls"),
        }
    )
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])

    async with tools_world(gateway) as node:
        result = await run_turn(node, _fusion(), ref, reader)

    members = [body for body in gateway.seen if body["model"] == MEMBER]
    assert len(members) == 2
    # WHY index 1: the model route puts the step instruction first, then the text view, whose
    # first message is the tools note.
    assert [body["messages"][0]["content"] for body in members] == ["Answer A", "Answer B"]
    for body in members:
        assert "tools" not in body
        assert "tool_choice" not in body
        assert body["messages"][1]["role"] == "system"
        assert body["messages"][1]["content"].startswith(TOOLS_NOTE)
    (synthesizer,) = [body for body in gateway.seen if body["model"] == SYNTH]
    assert synthesizer["tools"] == [TOOL]
    assert "tool_choice" not in synthesizer
    messages = synthesizer["messages"]
    client = [wire.message_dict(message) for message in final_turn(INPUT_MESSAGES).messages]
    assert messages[0] == {"role": "system", "content": MERGE}
    assert messages[1:-1] == client
    assert messages[-1]["role"] == "user"
    assert "Sunny" in messages[-1]["content"]
    assert _dumped(result.tool_calls) == calls
    assert result.finish_reason == "tool_calls"
    assert result.final_step is not None
    assert result.final_step.binding == "synthesis_1"


# --- TC-15: a Gate with tools --------------------------------------------------------------------


async def test_gate_with_tools_only_chosen_branch_calls_final_endpoint() -> None:
    calls = [tool_call()]
    gateway = ToolGateway(
        {
            "prov/math": Reply(content="M", tool_calls=calls, finish_reason="tool_calls"),
            "prov/coder": Reply(content="C"),
            "prov/general": Reply(content="G"),
        }
    )
    messages = [{"role": "user", "content": "An integral please: what is 2 + 2?"}]
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, messages, [TOOL])

    async with tools_world(gateway) as node:
        result = await run_turn(node, fixture("keyword_router.url4"), ref, reader)

    assert [body["model"] for body in gateway.seen] == ["prov/math"]
    assert gateway.seen[0]["tools"] == [TOOL]
    assert gateway.calls("prov/coder") == 0
    assert gateway.calls("prov/general") == 0
    assert result.status == "answered"
    assert result.content == "M"
    assert _dumped(result.tool_calls) == calls
    assert result.finish_reason == "tool_calls"
    assert result.final_step is not None
    assert result.final_step.binding == "model_1"


# --- TC-16: the tool calls reach the result unchanged --------------------------------------------


async def _one_model(reply: Reply) -> tuple[Any, ToolGateway]:
    gateway = ToolGateway({"prov/a": reply})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])
    async with tools_world(gateway) as node:
        result = await run_turn(node, one_model_recipe("prov/a"), ref, reader)
    return result, gateway


async def test_tool_calls_reach_response_unchanged_with_finish_reason_tool_calls() -> None:
    calls = [
        tool_call("call_1"),
        tool_call("call_2", arguments='{"city":"Rome"}', reasoning_details=[{"k": "v"}]),
    ]
    result, gateway = await _one_model(
        Reply(content=None, tool_calls=calls, finish_reason="tool_calls")
    )

    assert len(gateway.seen) == 1
    assert result.status == "answered"
    assert _dumped(result.tool_calls) == calls
    assert result.content == ""
    assert result.finish_reason == "tool_calls"
    assert result.final_step == FinalStep(
        binding="model_1",
        model="prov/a",
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    )

    unstated, _ = await _one_model(Reply(content=None, tool_calls=calls, finish_reason=None))
    assert unstated.finish_reason == "tool_calls"
    assert len(unstated.tool_calls) == 2

    cut, _ = await _one_model(Reply(content=None, tool_calls=calls, finish_reason="length"))
    assert cut.finish_reason == "length"
    assert _dumped(cut.tool_calls) == calls


# --- TC-20: attribution names the final step -----------------------------------------------------


async def test_attribution_names_final_step_with_its_output_and_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoded: list[CandidateInvocation] = []

    def recording(envelope: str) -> CandidateInvocation:
        invocation = decode_candidate_invocation_record(envelope)
        decoded.append(invocation)
        return invocation

    monkeypatch.setattr(
        screamingface_engine.world.chat_turn, "decode_candidate_invocation_record", recording
    )
    gateway = ToolGateway(
        {
            MEMBER: Reply(content="Sunny"),
            SYNTH: Reply(content="Checking.", tool_calls=[tool_call()], finish_reason="tool_calls"),
        }
    )
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])

    async with tools_world(gateway) as node:
        result = await run_turn(node, _fusion(), ref, reader)

    (invocation,) = decoded
    final = final_operation(tools_expression(_fusion()), invocation.operations)
    assert final is not None
    assert final.operation_id == "op_synthesis_1"
    assert final.output == "Checking."
    assert final.finish_reason == "tool_calls"
    assert final.accounting is not None
    assert result.content == "Checking."


# --- TC-24: tool history with no tools -----------------------------------------------------------


async def test_tool_history_without_tools_uses_text_view_for_final_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expressions: list[str] = []
    real = screamingface_engine.world.chat_turn.evaluate_candidate_recipe

    async def recording(node: Any, expression: str, *args: Any, **kwargs: Any) -> str:
        expressions.append(expression)
        return await real(node, expression, *args, **kwargs)

    monkeypatch.setattr(
        screamingface_engine.world.chat_turn, "evaluate_candidate_recipe", recording
    )
    recipe = one_model_recipe("prov/a")
    gateway = ToolGateway({"prov/a": Reply(content="ok")})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, HISTORY)
    async with tools_world(gateway) as node:
        result = await run_turn(node, recipe, ref, reader)

    plain = Gateway({"prov/a": "ok"})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, HISTORY)
    async with chat_world(plain) as node:
        await run_turn(node, recipe, ref, reader)

    assert expressions == [recipe, recipe]
    assert FINAL_STEP_ROUTE not in expressions[0]
    (body,) = gateway.seen
    assert "tools" not in body
    assert body == plain.seen[0]
    user = "\n".join(m["content"] for m in body["messages"] if m["role"] == "user")
    assert "[tool_call id=call_1 name=get_weather]" in "\n".join(
        m["content"] for m in body["messages"]
    )
    assert "[tool_result id=call_1]" in user
    assert result.content == "ok"
    assert result.tool_calls == []


# --- TC-26: a gateway 400 on the final step -----------------------------------------------------


async def test_gateway_400_on_final_step_is_502_with_code() -> None:
    gateway = ToolGateway({"prov/a": Reply(status=400)})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])
    async with tools_world(gateway) as node:
        with pytest.raises(ResolutionError) as with_tools:
            await run_turn(node, one_model_recipe("prov/a"), ref, reader)

    plain = Gateway({"prov/a": FAIL})
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES)
    async with chat_world(plain) as node:
        with pytest.raises(ResolutionError) as without:
            await run_turn(node, one_model_recipe("prov/a"), ref, reader)

    assert len(gateway.seen) == 1
    assert "tools" in gateway.seen[0]
    assert with_tools.value.code == without.value.code
    assert with_tools.value.permanent is True


# --- TC-S16: two final steps in one turn ---------------------------------------------------------

_TWO_SOURCES = "(model_1:0.0:/prov/a($input)!'x', model_1:0.0:/prov/b($input)!'y')!'$model_1'"


def _two_sources_gateway() -> ToolGateway:
    return ToolGateway({"prov/a": Reply(content="A"), "prov/b": Reply(content="B")})


async def test_two_sources_of_the_final_binding_are_refused_before_any_model_call() -> None:
    gateway = _two_sources_gateway()
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])

    async with tools_world(gateway) as node:
        with pytest.raises(ResolutionError) as caught:
            await run_turn(node, _TWO_SOURCES, ref, reader)

    assert gateway.seen == []
    assert caught.value.code == "recipe_not_supported"
    assert caught.value.permanent is True


async def test_two_final_steps_in_one_turn_fail_with_final_step_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY the check without tools: the with-tools check refuses two sources of one final binding,
    # so the test passes it by the no-tools check to reach the last guard at run time. The
    # re-point moves each source of the final binding, so both run on the final-step route.
    def no_tools_check(recipe: str, *, with_tools: bool) -> CheckedRecipe:
        return check_recipe(recipe, with_tools=False)

    monkeypatch.setattr(screamingface_engine.world.chat_turn, "check_recipe", no_tools_check)
    gateway = _two_sources_gateway()
    store, _ = chat_store()
    ref, reader = ingest_chat_input(store, INPUT_MESSAGES, [TOOL])

    async with tools_world(gateway) as node:
        with pytest.raises(ResolutionError) as caught:
            await run_turn(node, _TWO_SOURCES, ref, reader)

    assert len(gateway.seen) == 2
    assert all(body["tools"] == [TOOL] for body in gateway.seen)
    assert caught.value.code == "final_step_ambiguous"
    assert caught.value.permanent is True

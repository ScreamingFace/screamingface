"""The final-step endpoint of a chat turn with tools (tool-calls PRD §3.2, §3.5; contracts C8).

FEATURE: tool-calls. The endpoint sends exactly one gateway request with the native messages and
the client tools, runs no tool, records the model outcome and one operation call, and fails
closed when no chat turn is bound.
"""

from __future__ import annotations

import json

import pytest
from _chat_conversations import provider_state_conversation
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

from screamingface_engine.chat.recipe import FINAL_SEARCH_MESSAGE
from screamingface_engine.chat.views import CONVERSATION_MARKER
from screamingface_engine.chat.wire import ToolCall
from screamingface_engine.model_outcomes import ModelOutcome, capture_model_outcomes
from screamingface_engine.operation_calls import capture_operation_calls
from screamingface_engine.world.chat_final import FinalCall
from screamingface_engine.world.config import ModelSpec
from url4.core.errors import ErrorCode, ResolutionError

pytestmark = pytest.mark.asyncio

MODEL = "prov/a"
TOOL_ROUTE = ModelSpec(id=MODEL, web_search=True)
NATIVE = "openrouter/prov/x"


async def test_final_endpoint_sends_one_request_with_client_tools_and_no_tool_choice() -> None:
    gateway = ToolGateway({MODEL: Reply(content="Sunny")})
    turn = final_turn(
        request_extra={
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "temperature": 1.5,
            "max_tokens": 5,
        }
    )
    async with tools_world(gateway) as node:
        answer = await call_final(
            node,
            MODEL,
            turn=turn,
            intent="Answer",
            params=(("binding", "model_1"), ("temperature", "0.2")),
        )

    assert answer == "Sunny"
    assert len(gateway.seen) == 1
    body = gateway.seen[0]
    assert body["tools"] == [TOOL]
    for key in ("tool_choice", "parallel_tool_calls", "stream", "binding", "max_tokens"):
        assert key not in body
    assert body["temperature"] == 0.2
    assert set(body) <= {"model", "messages", "tools", "temperature", "cache"}
    assert body["model"] == MODEL
    assert body["messages"] == [{"role": "system", "content": "Answer"}, *INPUT_MESSAGES]


async def test_final_endpoint_sends_unknown_client_keys_unchanged() -> None:
    messages, tools = provider_state_conversation()
    gateway = ToolGateway({MODEL: Reply(content="done")})
    async with tools_world(gateway) as node:
        await call_final(node, MODEL, turn=final_turn(messages, tools))

    body = gateway.seen[0]
    assert body["messages"] == messages
    assert body["tools"] == tools


async def test_final_endpoint_never_executes_a_tool_call() -> None:
    calls = [tool_call("call_1"), tool_call("call_2", arguments='{"city":"Rome"}')]
    gateway = ToolGateway(
        {MODEL: Reply(content=None, tool_calls=calls, finish_reason="tool_calls")}
    )
    turn = final_turn()
    async with tools_world(gateway, models=[TOOL_ROUTE]) as node:
        answer = await call_final(node, MODEL, turn=turn)

    assert answer == ""
    assert len(gateway.seen) == 1
    body = gateway.seen[0]
    assert body["tools"] == [TOOL]
    assert "tool_choice" not in body
    assert "web_search" not in body
    assert len(turn.calls) == 1


async def test_final_endpoint_records_outcome_operation_and_usage() -> None:
    calls = [tool_call()]
    gateway = ToolGateway(
        {MODEL: Reply(content="Checking.", tool_calls=calls, finish_reason="tool_calls")}
    )
    turn = final_turn()
    async with tools_world(gateway) as node:
        with capture_model_outcomes() as outcomes, capture_operation_calls() as operations:
            answer = await call_final(node, MODEL, turn=turn)

    assert answer == "Checking."
    assert outcomes == [ModelOutcome("tool_calls", None)]
    assert len(operations) == 1
    operation = operations[0]
    assert operation.path == final_route(MODEL)
    assert ("binding", "model_1") in operation.params
    assert operation.output == "Checking."
    assert operation.finish_reason == "tool_calls"
    assert operation.accounting is not None
    assert operation.accounting.usage.input_tokens == 10
    assert operation.accounting.usage.output_tokens == 4

    final = turn.calls.result()
    assert isinstance(final, FinalCall)
    assert final.binding == "model_1"
    assert final.accounting is not None
    assert final.tool_calls == (ToolCall.model_validate(calls[0]),)
    assert final.finish_reason == "tool_calls"
    assert final.accounting == operation.accounting


async def test_final_step_with_explicit_web_search_on_engine_tool_route_is_refused_and_default_is_not() -> (  # noqa: E501
    None
):
    gateway = ToolGateway({MODEL: Reply(content="ok")})
    async with tools_world(gateway, models=[TOOL_ROUTE]) as node:
        with pytest.raises(ResolutionError) as refused:
            await call_final(
                node,
                MODEL,
                turn=final_turn(),
                params=(("binding", "model_1"), ("web_search", "true")),
            )
        assert refused.value.code == "recipe_not_supported"
        assert refused.value.permanent is True
        assert FINAL_SEARCH_MESSAGE in str(refused.value)
        assert gateway.seen == []

        await call_final(node, MODEL, turn=final_turn())
    assert len(gateway.seen) == 1
    assert "web_search" not in gateway.seen[0]
    assert gateway.seen[0]["tools"] == [TOOL]

    native = ToolGateway({NATIVE: Reply(content="ok")})
    async with tools_world(native, models=[ModelSpec(id=NATIVE, web_search=True)]) as node:
        await call_final(node, NATIVE, turn=final_turn())
        await call_final(
            node,
            NATIVE,
            turn=final_turn(),
            params=(("binding", "model_1"), ("web_search_exclude", "example.com")),
        )
    plain, excluded = native.seen
    assert plain["web_search"] is True
    assert plain["tools"] == [TOOL]
    assert "web_search_excluded_domains" not in plain
    assert excluded["web_search"] is True
    assert excluded["web_search_excluded_domains"] == ["example.com"]


async def test_length_finish_with_tool_calls_passes_through() -> None:
    gateway = ToolGateway(
        {
            MODEL: [
                Reply(content=None, tool_calls=[tool_call()], finish_reason="length"),
                Reply(content=None, tool_calls=[tool_call()], finish_reason=None),
            ]
        }
    )
    cut, unstated = final_turn(), final_turn()
    async with tools_world(gateway) as node:
        await call_final(node, MODEL, turn=cut)
        await call_final(node, MODEL, turn=unstated)

    cut_call, unstated_call = cut.calls.result(), unstated.calls.result()
    assert cut_call is not None and unstated_call is not None
    assert cut_call.finish_reason == "length"
    assert cut_call.tool_calls == (ToolCall.model_validate(tool_call()),)
    assert unstated_call.finish_reason is None
    assert len(unstated_call.tool_calls) == 1


async def test_final_endpoint_without_bound_chat_turn_fails_closed() -> None:
    gateway = ToolGateway({MODEL: Reply(content="ok")})
    async with tools_world(gateway) as node:
        with pytest.raises(ResolutionError) as refused:
            await call_final(node, MODEL, turn=None)

    assert refused.value.code == ErrorCode.ENDPOINT_NOT_FOUND
    assert refused.value.permanent is True
    assert gateway.seen == []


async def test_final_endpoint_without_chat_run_marker_fails_closed() -> None:
    gateway = ToolGateway({MODEL: Reply(content="ok")})
    async with tools_world(gateway) as node:
        with pytest.raises(ResolutionError) as refused:
            await call_final(node, MODEL, turn=final_turn(), in_chat_run=False)

    assert refused.value.code == ErrorCode.ENDPOINT_NOT_FOUND
    assert refused.value.permanent is True
    assert gateway.seen == []


async def test_empty_step_context_adds_no_last_user_message() -> None:
    gateway = ToolGateway({MODEL: Reply(content="ok")})
    turn = final_turn()
    shown = json.dumps({"input": turn.input_text, "members": ["Sunny", "Rain"]})
    async with tools_world(gateway) as node:
        await call_final(node, MODEL, turn=turn, context="", intent="Answer")
        await call_final(node, MODEL, turn=final_turn(), context="")
        await call_final(node, MODEL, turn=final_turn(), context=shown, intent="Pick one")

    empty, bare, member_context = (body["messages"] for body in gateway.seen)
    assert empty == [{"role": "system", "content": "Answer"}, *INPUT_MESSAGES]
    assert bare == INPUT_MESSAGES
    assert member_context[:-1] == [{"role": "system", "content": "Pick one"}, *INPUT_MESSAGES]
    last = member_context[-1]
    assert last["role"] == "user"
    assert CONVERSATION_MARKER in last["content"]
    assert turn.input_text not in last["content"]
    assert json.loads(last["content"])["members"] == ["Sunny", "Rain"]

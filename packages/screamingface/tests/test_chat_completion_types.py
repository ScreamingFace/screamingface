"""MI-26: the reply types of the chat calls have the OpenAI keys and cannot change.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.3).
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from typing import Any

import pytest

from screamingface.chat_completion import (
    ChatChoice,
    ChatChunkChoice,
    ChatCompletion,
    ChatCompletionChunk,
    ChatDelta,
    ChatDeltaToolCall,
    ChatFunctionCall,
    ChatMessage,
    ChatToolCall,
    ChatUsage,
    FinalStep,
    InferenceInfo,
)


def _usage() -> ChatUsage:
    return ChatUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)


def _call() -> ChatToolCall:
    return ChatToolCall(
        id="call_1",
        type="function",
        function=ChatFunctionCall(name="get_weather", arguments='{"city":"Paris"}'),
    )


def _info(cost: Decimal = Decimal("0.0012")) -> InferenceInfo:
    return InferenceInfo(
        status="answered",
        abstain_reason=None,
        cost_usd=cost,
        trace_id="0af7651916cd43dd8448eb211c80319c",
        final_step=FinalStep(binding="model_1", model="openrouter/a", usage=_usage()),
    )


def _reply(message: ChatMessage) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=1700000000,
        model="openrouter/a",
        choices=(ChatChoice(index=0, message=message, finish_reason="tool_calls"),),
        usage=_usage(),
        screamingface=_info(),
    )


def test_reply_to_dict_has_the_openai_keys() -> None:
    """MI-26: a reply with tool calls gives the OpenAI keys and the screamingface keys."""

    reply = _reply(
        ChatMessage(role="assistant", content="Let me check.", tool_calls=(_call(),), refusal=None)
    )

    assert reply.to_dict() == {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "openrouter/a",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Let me check.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                        }
                    ],
                    "refusal": None,
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        "screamingface": {
            "status": "answered",
            "abstain_reason": None,
            "cost_usd": "0.0012",
            "trace_id": "0af7651916cd43dd8448eb211c80319c",
            "final_step": {
                "binding": "model_1",
                "model": "openrouter/a",
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        },
    }
    assert json.loads(json.dumps(reply.to_dict())) == reply.to_dict()


def test_reply_to_dict_keeps_the_null_keys() -> None:
    """MI-26: a refused reply keeps every key, and a None value stays None, never omitted."""

    refused = ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=1700000000,
        model="openrouter/a",
        choices=(
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=None, tool_calls=None, refusal="no"),
                finish_reason="content_filter",
            ),
        ),
        usage=_usage(),
        screamingface=InferenceInfo(
            status="refused", abstain_reason=None, cost_usd=None, trace_id=None, final_step=None
        ),
    )

    assert refused.to_dict()["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": None, "tool_calls": None, "refusal": "no"},
            "finish_reason": "content_filter",
        }
    ]
    assert refused.to_dict()["screamingface"] == {
        "status": "refused",
        "abstain_reason": None,
        "cost_usd": None,
        "trace_id": None,
        "final_step": None,
    }
    assert FinalStep(binding="b", model="m", usage=None).to_dict() == {
        "binding": "b",
        "model": "m",
        "usage": None,
    }


@pytest.mark.parametrize(
    ("cost", "text"),
    [
        (Decimal("0.00000010"), "0.00000010"),
        (Decimal("1E-7"), "0.0000001"),
        (Decimal("12"), "12"),
    ],
)
def test_cost_usd_is_a_decimal_string_with_no_exponent(cost: Decimal, text: str) -> None:
    """MI-26: cost_usd is written in plain decimal text, with no exponent."""

    assert _info(cost).to_dict()["cost_usd"] == text


def test_short_forms_read_the_first_choice_and_the_info() -> None:
    """MI-26: the short forms text, tool_calls, cost_usd and trace_id read the reply."""

    reply = _reply(
        ChatMessage(role="assistant", content="Let me check.", tool_calls=(_call(),), refusal=None)
    )

    assert reply.text == "Let me check."
    assert reply.tool_calls == (_call(),)
    assert reply.cost_usd == Decimal("0.0012")
    assert reply.trace_id == "0af7651916cd43dd8448eb211c80319c"


def test_short_forms_with_no_choice_are_none() -> None:
    """MI-26: with no choice, the short forms text and tool_calls are None."""

    reply = ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=1700000000,
        model="openrouter/a",
        choices=(),
        usage=_usage(),
        screamingface=_info(),
    )

    assert reply.text is None
    assert reply.tool_calls is None


def test_chunk_text_is_the_delta_content_or_empty() -> None:
    """MI-26: the short form text of a chunk is the delta content, or an empty string."""

    with_text = ChatCompletionChunk(
        id="chatcmpl-1",
        object="chat.completion.chunk",
        created=1700000000,
        model="openrouter/a",
        choices=(
            ChatChunkChoice(
                index=0,
                delta=ChatDelta(role="assistant", content="Hi", tool_calls=None, refusal=None),
                finish_reason=None,
            ),
        ),
        usage=None,
        screamingface=None,
    )
    no_content = ChatCompletionChunk(
        id="chatcmpl-1",
        object="chat.completion.chunk",
        created=1700000000,
        model="openrouter/a",
        choices=(
            ChatChunkChoice(
                index=0,
                delta=ChatDelta(role=None, content=None, tool_calls=None, refusal=None),
                finish_reason="stop",
            ),
        ),
        usage=None,
        screamingface=None,
    )
    no_choice = ChatCompletionChunk(
        id="chatcmpl-1",
        object="chat.completion.chunk",
        created=1700000000,
        model="openrouter/a",
        choices=(),
        usage=_usage(),
        screamingface=_info(),
    )

    assert with_text.text == "Hi"
    assert no_content.text == ""
    assert no_choice.text == ""


def test_chunk_to_dict_has_the_openai_keys() -> None:
    """MI-26: a tool-call chunk keeps index in each call; a usage chunk keeps the empty choices."""

    tool_chunk = ChatCompletionChunk(
        id="chatcmpl-1",
        object="chat.completion.chunk",
        created=1700000000,
        model="openrouter/a",
        choices=(
            ChatChunkChoice(
                index=0,
                delta=ChatDelta(
                    role=None,
                    content=None,
                    tool_calls=(
                        ChatDeltaToolCall(
                            index=0,
                            id="call_1",
                            type="function",
                            function=ChatFunctionCall(
                                name="get_weather", arguments='{"city":"Paris"}'
                            ),
                        ),
                    ),
                    refusal=None,
                ),
                finish_reason=None,
            ),
        ),
        usage=None,
        screamingface=None,
    )
    usage_chunk = ChatCompletionChunk(
        id="chatcmpl-1",
        object="chat.completion.chunk",
        created=1700000000,
        model="openrouter/a",
        choices=(),
        usage=_usage(),
        screamingface=_info(),
    )

    assert tool_chunk.to_dict() == {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "openrouter/a",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": None,
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                        }
                    ],
                    "refusal": None,
                },
                "finish_reason": None,
            }
        ],
        "usage": None,
        "screamingface": None,
    }
    usage_dict = usage_chunk.to_dict()
    assert usage_dict["choices"] == []
    assert usage_dict["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert usage_dict["screamingface"] == _info().to_dict()


REPLY_TYPES = [
    pytest.param(_usage(), id="ChatUsage"),
    pytest.param(ChatFunctionCall(name="get_weather", arguments="{}"), id="ChatFunctionCall"),
    pytest.param(_call(), id="ChatToolCall"),
    pytest.param(
        ChatDeltaToolCall(
            index=0,
            id="call_1",
            type="function",
            function=ChatFunctionCall(name="get_weather", arguments="{}"),
        ),
        id="ChatDeltaToolCall",
    ),
    pytest.param(
        FinalStep(binding="model_1", model="openrouter/a", usage=_usage()), id="FinalStep"
    ),
    pytest.param(_info(), id="InferenceInfo"),
    pytest.param(
        ChatMessage(role="assistant", content="Hi", tool_calls=None, refusal=None),
        id="ChatMessage",
    ),
    pytest.param(
        ChatChoice(
            index=0,
            message=ChatMessage(role="assistant", content="Hi", tool_calls=None, refusal=None),
            finish_reason="stop",
        ),
        id="ChatChoice",
    ),
    pytest.param(
        _reply(ChatMessage(role="assistant", content="Hi", tool_calls=None, refusal=None)),
        id="ChatCompletion",
    ),
    pytest.param(ChatDelta(role=None, content="Hi", tool_calls=None, refusal=None), id="ChatDelta"),
    pytest.param(
        ChatChunkChoice(
            index=0,
            delta=ChatDelta(role=None, content="Hi", tool_calls=None, refusal=None),
            finish_reason=None,
        ),
        id="ChatChunkChoice",
    ),
    pytest.param(
        ChatCompletionChunk(
            id="chatcmpl-1",
            object="chat.completion.chunk",
            created=1700000000,
            model="openrouter/a",
            choices=(),
            usage=None,
            screamingface=None,
        ),
        id="ChatCompletionChunk",
    ),
]


@pytest.mark.parametrize("obj", REPLY_TYPES)
def test_reply_types_are_frozen(obj: Any) -> None:
    """MI-26: each reply type is frozen and has slots, so no field can change after the build."""

    name = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, name, None)
    assert not hasattr(obj, "__dict__")


def test_equal_replies_compare_and_hash_equal() -> None:
    """MI-26: two replies built the same way are equal and have the same hash."""

    first = _reply(ChatMessage(role="assistant", content="Hi", tool_calls=None, refusal=None))
    second = _reply(ChatMessage(role="assistant", content="Hi", tool_calls=None, refusal=None))

    assert first == second
    assert hash(first) == hash(second)

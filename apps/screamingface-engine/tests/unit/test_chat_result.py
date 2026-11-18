"""The CHAT_RESULT record: its finish_reason rule, its invariant, and its canonical encoding.

These tests pin erd section 2.4. The record is the one result body of a chat run, so a broken
rule here changes the body that the App turns into the OpenAI response.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine.chat.result import (
    CHAT_RESULT_SCHEMA,
    ChatResult,
    ChatResultError,
    FinalStep,
    decode_chat_result,
    encode_chat_result,
    finish_reason_of,
)
from screamingface_engine.chat.wire import FunctionCall, ToolCall


def _call() -> ToolCall:
    """One tool call of the final model step."""

    return ToolCall(
        id="call_1", type="function", function=FunctionCall(name="read", arguments="{}")
    )


@pytest.mark.parametrize(
    ("provider_value", "tool_calls", "expected"),
    [
        ("stop", [], "stop"),
        ("length", [_call()], "length"),
        ("stop", [_call()], "stop"),
        ("content_filter", [], "content_filter"),
    ],
)
def test_finish_reason_passes_the_provider_value_through(
    provider_value: str, tool_calls: list[ToolCall], expected: str
) -> None:
    assert finish_reason_of(provider_value, tool_calls) == expected


@pytest.mark.parametrize("provider_value", [None, ""])
def test_finish_reason_without_provider_value_is_tool_calls_when_calls_exist(
    provider_value: str | None,
) -> None:
    assert finish_reason_of(provider_value, [_call()]) == "tool_calls"


def test_finish_reason_without_value_and_without_calls_is_stop() -> None:
    assert finish_reason_of(None, []) == "stop"


def test_abstained_result_has_no_content_and_no_tool_calls() -> None:
    result = ChatResult(status="abstained", finish_reason="stop", abstain_reason="budget_refused")
    assert result.content == ""

    with pytest.raises(ValidationError):
        ChatResult(status="abstained", finish_reason="stop", content="x")

    with pytest.raises(ValidationError):
        ChatResult(status="abstained", finish_reason="tool_calls", tool_calls=[_call()])


def test_chat_result_round_trips_canonical_json() -> None:
    result = ChatResult(
        status="answered",
        content="Grüße",
        tool_calls=[_call()],
        finish_reason="tool_calls",
        final_step=FinalStep(
            binding="synthesis_1",
            model="openai/gpt-4o",
            usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        ),
    )

    data = encode_chat_result(result)

    assert decode_chat_result(data) == result
    assert data == json.dumps(
        json.loads(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert set(json.loads(data)) == {
        "schema",
        "status",
        "content",
        "tool_calls",
        "finish_reason",
        "refusal",
        "abstain_reason",
        "final_step",
    }


def test_chat_result_keeps_unknown_keys_of_a_provider_tool_call() -> None:
    """erd §2.4: a provider tool call passes unchanged, its unknown keys too."""

    provider_call: dict[str, Any] = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read", "arguments": "{}", "x_vendor": 1},
        "extra_content": {"google": {"thought_signature": "c2ln"}},
    }
    result = ChatResult(
        status="answered",
        tool_calls=[ToolCall.model_validate(provider_call)],
        finish_reason="tool_calls",
    )

    data = encode_chat_result(result)

    assert json.loads(data)["tool_calls"] == [provider_call]
    assert decode_chat_result(data) == result
    assert encode_chat_result(decode_chat_result(data)) == data


def test_chat_result_refuses_unknown_schema_by_name() -> None:
    body = json.loads(encode_chat_result(ChatResult(status="answered", finish_reason="stop")))

    body["schema"] = "screamingface.chat-result.v2"
    with pytest.raises(ChatResultError, match="screamingface.chat-result.v2"):
        decode_chat_result(json.dumps(body).encode("utf-8"))

    with pytest.raises(ChatResultError):
        decode_chat_result(b"[]")

    with pytest.raises(ChatResultError):
        decode_chat_result(b"not json")

    body["schema"] = CHAT_RESULT_SCHEMA
    body["status"] = "maybe"
    with pytest.raises(ChatResultError):
        decode_chat_result(json.dumps(body).encode("utf-8"))


@pytest.mark.parametrize(
    "body",
    [
        {"schema": CHAT_RESULT_SCHEMA, "finish_reason": "stop"},
        {"schema": CHAT_RESULT_SCHEMA, "status": "answered", "finish_reason": ""},
    ],
)
def test_chat_result_refuses_a_missing_or_empty_required_field(body: dict[str, object]) -> None:
    with pytest.raises(ChatResultError):
        decode_chat_result(json.dumps(body).encode("utf-8"))


def test_refused_result_carries_the_refusal_text() -> None:
    result = ChatResult(
        status="refused", finish_reason="content_filter", refusal="I can't help with that."
    )

    assert decode_chat_result(encode_chat_result(result)) == result


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "answered", "finish_reason": "stop", "refusal": "x"},
        {"status": "abstained", "finish_reason": "stop", "refusal": "x"},
        {"status": "answered", "finish_reason": "stop", "abstain_reason": "x"},
        {"status": "refused", "finish_reason": "content_filter", "abstain_reason": "x"},
    ],
)
def test_refusal_and_abstain_reason_belong_to_their_status(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ChatResult(**fields)

    data = json.dumps({"schema": CHAT_RESULT_SCHEMA, **fields}).encode("utf-8")
    with pytest.raises(ChatResultError):
        decode_chat_result(data)


def test_abstain_reason_round_trips() -> None:
    result = ChatResult(status="abstained", finish_reason="stop", abstain_reason="no_votes")

    assert decode_chat_result(encode_chat_result(result)) == result

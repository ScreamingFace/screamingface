"""The CHAT_INPUT record: the canonical encoding and the size rule (erd §2.1).

A chat request becomes one CHAT_INPUT record. These tests pin the round trip (CR-1), the schema
check that runs before any other field (CR-2), the refusal of broken records, and the 8,000,000
byte cap on the encoded record.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _chat_conversations import provider_state_conversation

from screamingface_engine.chat.input import (
    CHAT_INPUT_SCHEMA,
    MAX_CHAT_INPUT_BYTES,
    ChatInput,
    ChatInputError,
    ChatInputSchemaError,
    ChatInputTooLarge,
    chat_input_from_request,
    decode_chat_input,
    encode_chat_input,
)
from screamingface_engine.chat.wire import (
    ChatCompletionRequest,
    canonical_json,
    message_dict,
    tool_dict,
)

MESSAGES: list[dict[str, Any]] = [
    {"role": "system", "content": "Be brief."},
    {"role": "developer", "content": "Use metric units."},
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "What is shown?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        ],
    },
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "content": "print('Grüße')"},
]

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]

SECRET = "the-secret-sentence-7f3a"


def _request(**extra: Any) -> ChatCompletionRequest:
    """A request with the test conversation, plus any extra request fields."""

    return ChatCompletionRequest.model_validate({"model": "m", "messages": MESSAGES, **extra})


def _record(content: str) -> ChatInput:
    """A record of one user message whose text is content."""

    request = ChatCompletionRequest.model_validate(
        {"model": "m", "messages": [{"role": "user", "content": content}]}
    )
    return chat_input_from_request(request)


def test_chat_input_round_trips_canonical_json() -> None:
    """CR-1: the record is canonical JSON in UTF-8 and survives a decode and an encode."""

    data = encode_chat_input(chat_input_from_request(_request(tools=TOOLS)))

    assert data == json.dumps(
        json.loads(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert "Grüße".encode() in data
    assert b"\\u00fc" not in data
    decoded = decode_chat_input(data)
    assert encode_chat_input(decoded) == data
    assert [message_dict(message) for message in decoded.messages] == MESSAGES
    assert decoded.tools is not None
    assert [tool_dict(tool) for tool in decoded.tools] == TOOLS
    assert json.loads(data)["schema"] == CHAT_INPUT_SCHEMA


def test_chat_input_keeps_unknown_keys_of_messages_and_tools() -> None:
    """CR-1: provider state on a message, a part, a tool call or a tool survives the round trip."""

    messages, tools = provider_state_conversation()
    request = ChatCompletionRequest.model_validate(
        {"model": "m", "messages": messages, "tools": tools}
    )
    data = encode_chat_input(chat_input_from_request(request))
    decoded = decode_chat_input(data)

    assert json.loads(data) == {"schema": CHAT_INPUT_SCHEMA, "messages": messages, "tools": tools}
    assert [message_dict(message) for message in decoded.messages] == messages
    assert [tool_dict(tool) for tool in decoded.tools or []] == tools
    assert encode_chat_input(decoded) == data


def test_tools_key_is_absent_when_the_request_has_none() -> None:
    """CR-1: the tools key is left out when the request has no tools, or an empty list."""

    for request in (_request(), _request(tools=[])):
        data = encode_chat_input(chat_input_from_request(request))

        assert b'"tools"' not in data
        assert decode_chat_input(data).tools is None


def test_sampling_fields_are_not_in_the_record() -> None:
    """CR-1: sampling and streaming fields never reach the record (ans:Q14)."""

    request = _request(
        tools=TOOLS,
        temperature=0.2,
        max_tokens=50,
        tool_choice="auto",
        stream=True,
    )

    value = json.loads(encode_chat_input(chat_input_from_request(request)))

    assert set(value) == {"schema", "messages", "tools"}


def test_chat_input_refuses_unknown_schema_by_name() -> None:
    """CR-2: the schema is read first, and a refusal names it without echoing the content."""

    v2 = canonical_json({"schema": "screamingface.chat-input.v2", "messages": "broken"})
    with pytest.raises(ChatInputSchemaError) as v2_error:
        decode_chat_input(v2)
    assert "'screamingface.chat-input.v2'" in str(v2_error.value)

    missing = canonical_json({"messages": [{"role": "user", "content": "Hi"}]})
    with pytest.raises(ChatInputSchemaError) as missing_error:
        decode_chat_input(missing)
    assert "<NoneType>" in str(missing_error.value)

    long_name = "x" * 300
    long = canonical_json({"schema": long_name, "messages": [{"role": "user", "content": "Hi"}]})
    with pytest.raises(ChatInputSchemaError) as long_error:
        decode_chat_input(long)
    assert "<str>" in str(long_error.value)
    assert long_name not in str(long_error.value)


def test_chat_input_refuses_broken_records() -> None:
    """CR-2: bytes that are not a CHAT_INPUT record are refused, and no message text is shown."""

    secret_message = canonical_json(
        {
            "schema": CHAT_INPUT_SCHEMA,
            "messages": [{"role": "function", "content": SECRET}],
        }
    )
    broken = [
        b"not json",
        b"[1]",
        b"\xff",
        canonical_json({"schema": CHAT_INPUT_SCHEMA, "messages": []}),
        secret_message,
    ]

    for data in broken:
        with pytest.raises(ChatInputError) as caught:
            decode_chat_input(data)
        assert SECRET not in str(caught.value)


def test_encoded_record_at_the_cap_is_accepted_and_one_byte_more_is_refused() -> None:
    """Size rule (erd §2.1): a record of exactly the cap is accepted; one byte more is refused."""

    overhead = len(encode_chat_input(_record("")))
    fits = "x" * (MAX_CHAT_INPUT_BYTES - overhead)

    assert len(encode_chat_input(_record(fits))) == MAX_CHAT_INPUT_BYTES
    with pytest.raises(ChatInputTooLarge):
        encode_chat_input(_record(fits + "x"))
    with pytest.raises(ChatInputTooLarge):
        decode_chat_input(b" " * (MAX_CHAT_INPUT_BYTES + 1))

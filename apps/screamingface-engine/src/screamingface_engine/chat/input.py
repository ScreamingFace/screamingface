"""The CHAT_INPUT record: the conversation and the tools a chat run reads (erd §2.1).

The App writes one record for each chat request into the chat-input store, and the run reads it
back. The record is canonical JSON in UTF-8, and it holds only what the run needs: the validated
messages and, when the request has any, the validated function tools. A message, a part, a tool
call and a tool keep the keys the wire models do not declare. Sampling fields are not part of it.

A reader refuses an unknown schema by name and never guesses (erd §4). Extra keys are ignored, so
a newer writer can add an optional field. Logs carry the digest and the size of a record, never
its content.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from screamingface_engine.chat._codec import json_object, shown
from screamingface_engine.chat.wire import (
    ChatCompletionRequest,
    ChatMessage,
    ToolSpec,
    canonical_json,
    message_dict,
    tool_dict,
)

__all__ = [
    "CHAT_INPUT_MEDIA_TYPE",
    "CHAT_INPUT_SCHEMA",
    "MAX_CHAT_INPUT_BYTES",
    "ChatInput",
    "ChatInputError",
    "ChatInputSchemaError",
    "ChatInputTooLarge",
    "chat_input_from_request",
    "decode_chat_input",
    "encode_chat_input",
]

CHAT_INPUT_SCHEMA = "screamingface.chat-input.v1"
CHAT_INPUT_MEDIA_TYPE = "application/vnd.screamingface.chat-input+json"
MAX_CHAT_INPUT_BYTES = 8_000_000


class ChatInputError(ValueError):
    """The bytes are not a valid CHAT_INPUT record."""


class ChatInputSchemaError(ChatInputError):
    """The record names a schema that is not CHAT_INPUT_SCHEMA, or names none."""


class ChatInputTooLarge(ChatInputError):
    """The encoded record is above MAX_CHAT_INPUT_BYTES."""


class ChatInput(BaseModel):
    """The conversation and the tools the App hands to the run.

    There is no sampling field (ans:Q14). "tools" is absent when the request has none. Extra keys
    are ignored, so a newer writer can add an optional field.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)

    schema_: Literal["screamingface.chat-input.v1"] = Field(
        default=CHAT_INPUT_SCHEMA, alias="schema"
    )
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ToolSpec] | None = None


def chat_input_from_request(request: ChatCompletionRequest) -> ChatInput:
    """The record of one request: its messages, and its tools when it has any."""

    return ChatInput(messages=list(request.messages), tools=request.tools or None)


def encode_chat_input(record: ChatInput) -> bytes:
    """The record as canonical JSON in UTF-8.

    Raises:
        ChatInputTooLarge: the encoded record is above MAX_CHAT_INPUT_BYTES.
    """

    value: dict[str, object] = {
        "schema": CHAT_INPUT_SCHEMA,
        "messages": [message_dict(message) for message in record.messages],
    }
    if record.tools:
        value["tools"] = [tool_dict(tool) for tool in record.tools]
    data = canonical_json(value)
    if len(data) > MAX_CHAT_INPUT_BYTES:
        raise ChatInputTooLarge(
            f"the chat input is {len(data)} bytes; the limit is {MAX_CHAT_INPUT_BYTES}"
        )
    return data


def decode_chat_input(data: bytes) -> ChatInput:
    """Read a CHAT_INPUT record, or refuse it.

    The checks run in this order: the size, the JSON object, the schema (before any other
    field is read), and then the model.

    Raises:
        ChatInputTooLarge: the bytes are above MAX_CHAT_INPUT_BYTES.
        ChatInputSchemaError: the schema is not CHAT_INPUT_SCHEMA.
        ChatInputError: the bytes are not a valid CHAT_INPUT record.
    """

    if len(data) > MAX_CHAT_INPUT_BYTES:
        raise ChatInputTooLarge(
            f"the chat input is {len(data)} bytes; the limit is {MAX_CHAT_INPUT_BYTES}"
        )
    value = json_object(data, ChatInputError, "the chat input")
    _check_schema(value.get("schema"))
    try:
        return ChatInput.model_validate(value)
    except ValidationError:
        # WHY from None: a validation error quotes the input, and the content must not reach a log.
        raise ChatInputError("the chat input breaks the chat-input schema") from None


def _check_schema(schema: object) -> None:
    """Refuse any schema but CHAT_INPUT_SCHEMA, naming it only when it looks like a name."""

    if schema != CHAT_INPUT_SCHEMA:
        raise ChatInputSchemaError(f"unsupported chat-input schema {shown(schema)}")

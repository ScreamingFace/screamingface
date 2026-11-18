"""The CHAT_RESULT record: the one result body of a chat run (erd section 2.4).

The record holds no usage sum and no cost. The App reads them from the root cost-usage frame of
the run (CC-S3). finish_reason is a str and not a fixed set, because it is the provider value
with no change (P39).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from screamingface_engine.chat._codec import json_object, shown
from screamingface_engine.chat.wire import ChatStatus, ToolCall, canonical_json

__all__ = [
    "CHAT_RESULT_MEDIA_TYPE",
    "CHAT_RESULT_SCHEMA",
    "ChatResult",
    "ChatResultError",
    "FinalStep",
    "decode_chat_result",
    "encode_chat_result",
    "finish_reason_of",
]

CHAT_RESULT_SCHEMA = "screamingface.chat-result.v1"
CHAT_RESULT_MEDIA_TYPE = "application/vnd.screamingface.chat-result+json"


class ChatResultError(ValueError):
    """The bytes are not a valid CHAT_RESULT."""


class FinalStep(BaseModel):
    """The model step that gave the final answer.

    usage is the usage block of the gateway response of that call, as returned. For a cache hit it
    holds the stored counts.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    binding: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: dict[str, Any] | None = None


class ChatResult(BaseModel):
    """The one result body of a chat run.

    It holds no usage sum and no cost: the App reads them from the root cost-usage frame (CC-S3).
    """

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, populate_by_name=True)

    schema_: Literal["screamingface.chat-result.v1"] = Field(
        default=CHAT_RESULT_SCHEMA, alias="schema"
    )
    status: ChatStatus
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str = Field(min_length=1)
    refusal: str | None = None
    abstain_reason: str | None = None
    final_step: FinalStep | None = None

    @model_validator(mode="after")
    def _status_rules(self) -> ChatResult:
        if self.status == "abstained" and (self.content or self.tool_calls):
            raise ValueError("an abstained result has no content and no tool calls")
        if self.refusal is not None and self.status != "refused":
            raise ValueError("only a refused result has a refusal")
        if self.abstain_reason is not None and self.status != "abstained":
            raise ValueError("only an abstained result has an abstain reason")
        return self


def finish_reason_of(provider_value: str | None, tool_calls: Sequence[object]) -> str:
    """The finish_reason of a result: the provider value as it came, else tool_calls or stop.

    See erd section 2.4 and TC-S17: a provider can return tool calls with "stop" or "length", and
    that value passes through. The handler passes None for an answer from a reducer, which gives
    "stop".
    """

    if isinstance(provider_value, str) and provider_value:
        return provider_value
    if tool_calls:
        return "tool_calls"
    return "stop"


def encode_chat_result(result: ChatResult) -> bytes:
    """The canonical JSON of a result. Every field is written."""

    return canonical_json(result.model_dump(mode="json", by_alias=True))


def decode_chat_result(data: bytes) -> ChatResult:
    """Read a result from its bytes, refusing a bad schema name before any other field."""

    value = json_object(data, ChatResultError, "the chat result")
    schema: object = value.get("schema")
    if schema != CHAT_RESULT_SCHEMA:
        raise ChatResultError(f"unsupported chat-result schema {shown(schema)}")
    try:
        return ChatResult.model_validate(value)
    except ValidationError:
        raise ChatResultError("the chat result breaks the chat-result schema") from None

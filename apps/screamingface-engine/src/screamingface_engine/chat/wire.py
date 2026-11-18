"""The OpenAI-compatible wire models of POST /v1/chat/completions.

The top-level request keeps what the route reads and drops every other key. A message, a content
part, a tool call and a tool keep every key the client sent, so provider state reaches the final
step with no change (tool-calls §3.5). The response side is built by the Engine, so it forbids any
key the models do not define. Nothing here checks a model length,
a remote media URL or an error code: those belong to the route.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "AssistantMessage",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "ChatStatus",
    "Choice",
    "ClientMessage",
    "DeveloperMessage",
    "ErrorBody",
    "ErrorEnvelope",
    "FileData",
    "FilePart",
    "FinalStepInfo",
    "FunctionCall",
    "FunctionSpec",
    "ImagePart",
    "ImageUrl",
    "ResponseMessage",
    "ScreamingFaceInfo",
    "StreamOptions",
    "SystemMessage",
    "TextPart",
    "ToolCall",
    "ToolMessage",
    "ToolSpec",
    "Usage",
    "UserMessage",
    "UserPart",
    "canonical_json",
    "message_dict",
    "tool_dict",
]

ChatStatus = Literal["answered", "abstained", "refused"]


class _Wire(BaseModel):
    """A request model: unknown keys are dropped at validation."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class _Native(BaseModel):
    """A client shape that the final step gets as sent: unknown keys are kept at validation.

    INVARIANT: a declared field always takes its key and its validation; pydantic puts only the
    other keys in the model extras, which never back an attribute of a declared field.
    """

    model_config = ConfigDict(extra="allow", frozen=True, strict=True)


class _Out(BaseModel):
    """A response model: the Engine builds it, so unknown keys are refused."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FunctionCall(_Native):
    name: str
    arguments: str


class ToolCall(_Native):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: FunctionCall


class TextPart(_Native):
    type: Literal["text"]
    text: str


class ImageUrl(_Native):
    url: str
    detail: Literal["auto", "low", "high"] | None = None


class ImagePart(_Native):
    type: Literal["image_url"]
    image_url: ImageUrl


class FileData(_Native):
    file_data: str
    filename: str | None = Field(default=None, min_length=1)


class FilePart(_Native):
    type: Literal["file"]
    file: FileData


UserPart = Annotated[TextPart | ImagePart | FilePart, Field(discriminator="type")]


class SystemMessage(_Native):
    role: Literal["system"]
    content: str | list[TextPart]
    name: str | None = None


class DeveloperMessage(_Native):
    role: Literal["developer"]
    content: str | list[TextPart]
    name: str | None = None


class UserMessage(_Native):
    role: Literal["user"]
    content: str | list[UserPart]
    name: str | None = None


class AssistantMessage(_Native):
    role: Literal["assistant"]
    content: str | list[TextPart] | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    refusal: str | None = None


class ToolMessage(_Native):
    role: Literal["tool"]
    content: str | list[TextPart]
    tool_call_id: str = Field(min_length=1)


ClientMessage = SystemMessage | DeveloperMessage | UserMessage | AssistantMessage | ToolMessage


ChatMessage = Annotated[ClientMessage, Field(discriminator="role")]


class FunctionSpec(_Native):
    name: str = Field(min_length=1)
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ToolSpec(_Native):
    type: Literal["function"]
    function: FunctionSpec


class StreamOptions(_Wire):
    include_usage: bool = False


class ChatCompletionRequest(_Wire):
    """One chat completion request as the client sends it.

    Sampling and other unknown fields (temperature, max_tokens, store, metadata,
    parallel_tool_calls, tool_choice and so on) are dropped at validation. n, logprobs, modalities
    and audio are kept only so the route can refuse them.
    """

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ToolSpec] | None = None
    stream: bool = False
    stream_options: StreamOptions | None = None
    n: int | None = None
    logprobs: bool | None = None
    modalities: list[str] | None = None
    audio: dict[str, Any] | None = None

    @field_validator("tools")
    @classmethod
    def _unique_tool_names(cls, tools: list[ToolSpec] | None) -> list[ToolSpec] | None:
        # WHY a field validator: the error location is ("tools",), so the route names the param.
        names = [tool.function.name for tool in tools or []]
        if len(names) != len(set(names)):
            raise ValueError("each tool name must be unique")
        return tools


class Usage(_Out):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ResponseMessage(_Out):
    role: Literal["assistant"] = "assistant"
    content: str | None
    tool_calls: list[ToolCall] | None = None
    refusal: str | None = None


class Choice(_Out):
    index: int = 0
    finish_reason: str
    message: ResponseMessage


class FinalStepInfo(_Out):
    binding: str
    model: str
    usage: Usage | None = None


class ScreamingFaceInfo(_Out):
    status: ChatStatus
    abstain_reason: str | None = None
    cost_usd: str | None = None
    trace_id: str | None = None
    final_step: FinalStepInfo | None = None


class ChatCompletionResponse(_Out):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage
    screamingface: ScreamingFaceInfo


class ErrorBody(_Out):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class ErrorEnvelope(_Out):
    error: ErrorBody


def message_dict(message: ClientMessage) -> dict[str, Any]:
    """The client message as the client sent it, unknown keys included, at every level.

    A key the client set to null stays null, and a key it left out stays out.
    """

    return message.model_dump(mode="json", exclude_unset=True)


def tool_dict(tool: ToolSpec) -> dict[str, Any]:
    """The tool as the client sent it, with the same rules as message_dict."""

    return tool.model_dump(mode="json", exclude_unset=True)


def canonical_json(value: object) -> bytes:
    """The one encoding of the chat records: sorted keys, no extra white space, no ASCII escapes.

    The bytes are UTF-8 (erd §2.1).
    """

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")

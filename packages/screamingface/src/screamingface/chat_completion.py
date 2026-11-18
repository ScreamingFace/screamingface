"""The reply types of sf.ModelInference: a chat reply, its chunks and the two streams.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.3 and C1.4).
The field names are those of the OpenAI objects (ans:Q2).
AIDEV-NOTE: unit U5 adds the iteration, the close and the context manager of the two streams (C1.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatUsage:
    """The token counts of one reply, as the OpenAI ``usage`` object (contracts C1.3)."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def to_dict(self) -> dict[str, object]:
        """The usage as a new JSON-ready dict with the OpenAI keys."""

        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatFunctionCall:
    """The function of one tool call, as the OpenAI ``function`` object (contracts C1.3)."""

    name: str
    arguments: str

    def to_dict(self) -> dict[str, object]:
        """The function as a new JSON-ready dict with the OpenAI keys."""

        return {"name": self.name, "arguments": self.arguments}


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatToolCall:
    """One tool call of a reply, as an OpenAI ``tool_calls`` item (contracts C1.3)."""

    id: str
    type: str
    function: ChatFunctionCall

    def to_dict(self) -> dict[str, object]:
        """The tool call as a new JSON-ready dict with the OpenAI keys."""

        return {"id": self.id, "type": self.type, "function": self.function.to_dict()}


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatDeltaToolCall:
    """One tool call of a streamed delta, as an OpenAI ``tool_calls`` item (contracts C1.3).

    OpenAI loops that collect tool calls read ``index`` to join the parts of one call.
    """

    index: int
    id: str
    type: str
    function: ChatFunctionCall

    def to_dict(self) -> dict[str, object]:
        """The tool call delta as a new JSON-ready dict with the OpenAI keys."""

        return {
            "index": self.index,
            "id": self.id,
            "type": self.type,
            "function": self.function.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class FinalStep:
    """The model step that ended the run, as the screamingface ``final_step`` (contracts C1.3)."""

    binding: str
    model: str
    usage: ChatUsage | None

    def to_dict(self) -> dict[str, object]:
        """The final step as a new JSON-ready dict."""

        return {
            "binding": self.binding,
            "model": self.model,
            "usage": self.usage.to_dict() if self.usage is not None else None,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class InferenceInfo:
    """The screamingface object of a reply: the status, the cost and the trace (contracts C1.3)."""

    status: str
    abstain_reason: str | None
    cost_usd: Decimal | None
    trace_id: str | None
    final_step: FinalStep | None

    def to_dict(self) -> dict[str, object]:
        """The info as a new JSON-ready dict, with the cost as a decimal string."""

        # WHY: the Engine sends the cost as a decimal string with no exponent (format "f"), so the
        # dict has the same text.
        return {
            "status": self.status,
            "abstain_reason": self.abstain_reason,
            "cost_usd": format(self.cost_usd, "f") if self.cost_usd is not None else None,
            "trace_id": self.trace_id,
            "final_step": self.final_step.to_dict() if self.final_step is not None else None,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatMessage:
    """The message of one choice, as an OpenAI ``message`` object (contracts C1.3)."""

    role: str
    content: str | None
    tool_calls: tuple[ChatToolCall, ...] | None
    refusal: str | None

    def to_dict(self) -> dict[str, object]:
        """The message as a new JSON-ready dict with the OpenAI keys."""

        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": (
                [call.to_dict() for call in self.tool_calls]
                if self.tool_calls is not None
                else None
            ),
            "refusal": self.refusal,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatChoice:
    """One choice of a reply, as an OpenAI ``choices`` item (contracts C1.3)."""

    index: int
    message: ChatMessage
    finish_reason: str

    def to_dict(self) -> dict[str, object]:
        """The choice as a new JSON-ready dict with the OpenAI keys."""

        return {
            "index": self.index,
            "message": self.message.to_dict(),
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCompletion:
    """One chat reply, as an OpenAI ``chat.completion`` object (contracts C1.3)."""

    id: str
    object: str
    created: int
    model: str
    choices: tuple[ChatChoice, ...]
    usage: ChatUsage
    screamingface: InferenceInfo

    @property
    def text(self) -> str | None:
        """The content of the first choice, or None when there is no choice."""

        if not self.choices:
            return None
        return self.choices[0].message.content

    @property
    def tool_calls(self) -> tuple[ChatToolCall, ...] | None:
        """The tool calls of the first choice, or None when there is no choice."""

        if not self.choices:
            return None
        return self.choices[0].message.tool_calls

    @property
    def cost_usd(self) -> Decimal | None:
        """The cost of the run in US dollars, or None when one call has no price."""

        return self.screamingface.cost_usd

    @property
    def trace_id(self) -> str | None:
        """The trace id of the run, or None when the reply has none."""

        return self.screamingface.trace_id

    def to_dict(self) -> dict[str, object]:
        """The reply as a new JSON-ready dict with the OpenAI keys and the screamingface object."""

        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [choice.to_dict() for choice in self.choices],
            "usage": self.usage.to_dict(),
            "screamingface": self.screamingface.to_dict(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatDelta:
    """The delta of one streamed choice, as an OpenAI ``delta`` object (contracts C1.3)."""

    role: str | None
    content: str | None
    tool_calls: tuple[ChatDeltaToolCall, ...] | None
    refusal: str | None

    def to_dict(self) -> dict[str, object]:
        """The delta as a new JSON-ready dict with the OpenAI keys."""

        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": (
                [call.to_dict() for call in self.tool_calls]
                if self.tool_calls is not None
                else None
            ),
            "refusal": self.refusal,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatChunkChoice:
    """One choice of a streamed chunk, as an OpenAI ``choices`` item (contracts C1.3)."""

    index: int
    delta: ChatDelta
    finish_reason: str | None

    def to_dict(self) -> dict[str, object]:
        """The choice as a new JSON-ready dict with the OpenAI keys."""

        return {
            "index": self.index,
            "delta": self.delta.to_dict(),
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCompletionChunk:
    """One chunk of a streamed reply, as an OpenAI ``chat.completion.chunk`` (contracts C1.3)."""

    id: str
    object: str
    created: int
    model: str
    choices: tuple[ChatChunkChoice, ...]
    usage: ChatUsage | None
    screamingface: InferenceInfo | None

    @property
    def text(self) -> str:
        """The delta content of the first choice, or an empty string when there is none."""

        if not self.choices:
            return ""
        return self.choices[0].delta.content or ""

    def to_dict(self) -> dict[str, object]:
        """The chunk as a new JSON-ready dict with the OpenAI keys and the screamingface object."""

        return {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [choice.to_dict() for choice in self.choices],
            "usage": self.usage.to_dict() if self.usage is not None else None,
            "screamingface": self.screamingface.to_dict()
            if self.screamingface is not None
            else None,
        }


class ChatStream:
    """The chunks of one reply, for a sync client and ``stream=True`` (contracts C1.4)."""


class AsyncChatStream:
    """The chunks of one reply, for an AsyncClient and ``stream=True`` (contracts C1.4)."""

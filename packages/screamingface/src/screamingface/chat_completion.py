"""The reply types of the chat calls: a chat reply, its chunks and the two streams.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.3 and C1.4).
The field names are those of the OpenAI objects (ans:Q2).
WHY the ClassVar[None] attributes: they are OpenAI attributes that the Engine never sets. OpenAI
code that reads them gets None (contracts C1.7, D24). They are not dataclass fields, so the
constructor, the equality and to_dict() do not change.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from types import TracebackType
from typing import ClassVar, Self

from screamingface._chat_dump import OpenAIDump


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatUsage(OpenAIDump):
    """The token counts of one reply, as the OpenAI ``usage`` object (contracts C1.3)."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: ClassVar[None] = None
    completion_tokens_details: ClassVar[None] = None

    def to_dict(self) -> dict[str, object]:
        """The usage as a new JSON-ready dict with the OpenAI keys."""

        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatFunctionCall(OpenAIDump):
    """The function of one tool call, as the OpenAI ``function`` object (contracts C1.3)."""

    name: str
    arguments: str

    def to_dict(self) -> dict[str, object]:
        """The function as a new JSON-ready dict with the OpenAI keys."""

        return {"name": self.name, "arguments": self.arguments}


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatToolCall(OpenAIDump):
    """One tool call of a reply, as an OpenAI ``tool_calls`` item (contracts C1.3)."""

    id: str
    type: str
    function: ChatFunctionCall

    def to_dict(self) -> dict[str, object]:
        """The tool call as a new JSON-ready dict with the OpenAI keys."""

        return {"id": self.id, "type": self.type, "function": self.function.to_dict()}


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatDeltaToolCall(OpenAIDump):
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
class FinalStep(OpenAIDump):
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
class InferenceInfo(OpenAIDump):
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
class ChatMessage(OpenAIDump):
    """The message of one choice, as an OpenAI ``message`` object (contracts C1.3)."""

    role: str
    content: str | None
    tool_calls: tuple[ChatToolCall, ...] | None
    refusal: str | None
    function_call: ClassVar[None] = None
    audio: ClassVar[None] = None
    annotations: ClassVar[None] = None

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
class ChatChoice(OpenAIDump):
    """One choice of a reply, as an OpenAI ``choices`` item (contracts C1.3)."""

    index: int
    message: ChatMessage
    finish_reason: str
    logprobs: ClassVar[None] = None

    def to_dict(self) -> dict[str, object]:
        """The choice as a new JSON-ready dict with the OpenAI keys."""

        return {
            "index": self.index,
            "message": self.message.to_dict(),
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCompletion(OpenAIDump):
    """One chat reply, as an OpenAI ``chat.completion`` object (contracts C1.3)."""

    id: str
    object: str
    created: int
    model: str
    choices: tuple[ChatChoice, ...]
    usage: ChatUsage
    screamingface: InferenceInfo
    system_fingerprint: ClassVar[None] = None
    service_tier: ClassVar[None] = None
    moderation: ClassVar[None] = None

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
class ChatDelta(OpenAIDump):
    """The delta of one streamed choice, as an OpenAI ``delta`` object (contracts C1.3)."""

    role: str | None
    content: str | None
    tool_calls: tuple[ChatDeltaToolCall, ...] | None
    refusal: str | None
    function_call: ClassVar[None] = None

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
class ChatChunkChoice(OpenAIDump):
    """One choice of a streamed chunk, as an OpenAI ``choices`` item (contracts C1.3)."""

    index: int
    delta: ChatDelta
    finish_reason: str | None
    logprobs: ClassVar[None] = None

    def to_dict(self) -> dict[str, object]:
        """The choice as a new JSON-ready dict with the OpenAI keys."""

        return {
            "index": self.index,
            "delta": self.delta.to_dict(),
            "finish_reason": self.finish_reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatCompletionChunk(OpenAIDump):
    """One chunk of a streamed reply, as an OpenAI ``chat.completion.chunk`` (contracts C1.3)."""

    id: str
    object: str
    created: int
    model: str
    choices: tuple[ChatChunkChoice, ...]
    usage: ChatUsage | None
    screamingface: InferenceInfo | None
    system_fingerprint: ClassVar[None] = None
    service_tier: ClassVar[None] = None
    moderation: ClassVar[None] = None

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
    """The chunks of one reply, for a sync client and ``stream=True`` (contracts C1.4).

    Iterate it to get each ChatCompletionChunk in the order of the Engine. It is a context
    manager. The stream closes its connection at the end of the chunks, at an error, at close(),
    at the exit of a with block and when Python frees it. The SDK makes the stream; do not make
    one yourself.

    The Engine sends a buffered stream: the first chunk comes when the run has ended, and then
    all chunks come at one time. It is not a token stream.
    """

    __slots__ = ("_chunks", "_close", "_closed")

    def __init__(self, chunks: Iterator[ChatCompletionChunk], close: Callable[[], None]) -> None:
        self._chunks = chunks
        self._close = close
        self._closed = False

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> ChatCompletionChunk:
        if self._closed:
            raise StopIteration
        try:
            chunk = next(self._chunks, None)
        except Exception:
            self.close()
            raise
        if chunk is None:
            self.close()
            raise StopIteration
        return chunk

    def close(self) -> None:
        """Release the connection. A second call does nothing."""

        if self._closed:
            return
        self._closed = True
        self._close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class AsyncChatStream:
    """The chunks of one reply, for an AsyncClient and ``stream=True`` (contracts C1.4).

    Iterate it with ``async for`` to get each ChatCompletionChunk in the order of the Engine.
    It is an async context manager. The stream closes its connection at the end of the chunks,
    at an error, at aclose(), and at the exit of an ``async with`` block.
    WHY no close when Python frees it: the close needs an await. asyncio closes the open
    connection later through its hooks for async generators. Use ``async with`` or aclose() to
    close it at once.

    The Engine sends a buffered stream: the first chunk comes when the run has ended, and then
    all chunks come at one time. It is not a token stream.
    """

    __slots__ = ("_chunks", "_aclose", "_closed")

    def __init__(
        self,
        chunks: AsyncIterator[ChatCompletionChunk],
        aclose: Callable[[], Awaitable[None]],
    ) -> None:
        self._chunks = chunks
        self._aclose = aclose
        self._closed = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        if self._closed:
            raise StopAsyncIteration
        try:
            chunk = await anext(self._chunks, None)
        except Exception:
            await self.aclose()
            raise
        if chunk is None:
            await self.aclose()
            raise StopAsyncIteration
        return chunk

    async def aclose(self) -> None:
        """Release the connection. A second call does nothing."""

        if self._closed:
            return
        self._closed = True
        await self._aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

"""The frame reader of the chat stream: SSE lines to events, events to chunks, chunks to one reply.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C2.3), unit U3.
INVARIANT: pure code: no I/O, no log, no SDK error. Unit U4 maps FrameError to ExecutionError
(code invalid_response) and StreamError by the table of contracts C2.4.
AIDEV-NOTE: the Engine pins the same reply rule in
apps/screamingface-engine/tests/unit/test_chat_stream_retry_flag.py::_reply_from_chunks.
Change the two together.
AIDEV-NOTE: the transport reads with EventReader (one line at a time, sync and async),
chunk_from_payload and build_completion. events_from_lines, read_chunks and completion_from_lines
are the pull forms of the same steps; the table tests use them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

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

__all__ = [
    "EventReader",
    "FrameError",
    "FrameErrorReason",
    "StreamError",
    "completion_from_lines",
    "read_chunks",
]

type FrameErrorReason = Literal["not_json", "wrong_shape", "truncated"]


class FrameError(Exception):
    """A chat stream with a wrong form; unit U4 maps it to ExecutionError with the code
    invalid_response."""

    def __init__(self, reason: FrameErrorReason, message: str) -> None:
        self.reason: FrameErrorReason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class StreamDone:
    """The data: [DONE] line, the normal end of the stream."""


DONE: Final[StreamDone] = StreamDone()


@dataclass(frozen=True, slots=True, kw_only=True)
class StreamError:
    """The error event of a stream that started (contracts C2.3, C4.1).

    should_retry is None when the event has no such key (an Engine before C4.1); unit U4 makes
    that error permanent.
    """

    message: str
    type: str
    code: str
    should_retry: bool | None
    retry_after: int | None


def event_from_line(line: str) -> dict[str, Any] | StreamError | StreamDone | None:
    """The event of one SSE line, or None when the line carries no event."""

    # WHY: this drops the blank line between events, the keep-alive comment lines that start with
    # ':' and each other SSE field. The Engine sends only data lines and comments, and the SSE
    # standard tells a reader to ignore a field that it does not use.
    field_name, _, value = line.partition(":")
    if field_name != "data":
        return None
    if value.startswith(" "):
        value = value[1:]
    return _event_from_data(value)


class EventReader:
    """The push form of events_from_lines: one SSE line in, its event out (contracts C2.3).

    The sync and the async transport give each line to one reader, so the two read the stream by
    the same rule. After the [DONE] line or the error event, ended is True and the caller stops
    to read.
    """

    __slots__ = ("_ended",)

    def __init__(self) -> None:
        self._ended = False

    @property
    def ended(self) -> bool:
        """True after the [DONE] line or the error event."""

        return self._ended

    def push(self, line: str) -> dict[str, Any] | StreamError | None:
        """The event of one line, or None for a line with no event and for the [DONE] line.

        It raises FrameError for a data line that is not a JSON object.
        """

        event = event_from_line(line)
        if isinstance(event, StreamDone):
            self._ended = True
            return None
        if isinstance(event, StreamError):
            self._ended = True
        return event

    def end(self) -> None:
        """Check the end of the lines: FrameError (truncated) when no [DONE] and no error event
        came."""

        if not self._ended:
            raise FrameError("truncated", "the chat stream ended before its [DONE] line")


def events_from_lines(lines: Iterable[str]) -> Iterator[dict[str, Any] | StreamError]:
    """The events of the lines, up to [DONE] or the error event.

    The lines after [DONE] or after the error event are not read.
    """

    reader = EventReader()
    for line in lines:
        event = reader.push(line)
        if event is not None:
            yield event
        if reader.ended:
            return
    reader.end()


def chunk_from_payload(payload: Mapping[str, Any]) -> ChatCompletionChunk:
    """The chunk of one data object. Unknown keys are ignored, so a newer Engine still reads."""

    raw_usage = payload.get("usage")
    raw_info = payload.get("screamingface")
    return ChatCompletionChunk(
        id=_text(payload, "id", "chunk"),
        object=_text(payload, "object", "chunk"),
        created=_whole(payload, "created", "chunk"),
        model=_text(payload, "model", "chunk"),
        choices=tuple(_chunk_choice(item) for item in _items(payload, "choices", "chunk")),
        usage=None if raw_usage is None else _usage(raw_usage),
        screamingface=None if raw_info is None else _info(raw_info),
    )


def read_chunks(lines: Iterable[str]) -> Iterator[ChatCompletionChunk | StreamError]:
    """The chunks of the lines, and the error event as it is."""

    for event in events_from_lines(lines):
        if isinstance(event, StreamError):
            yield event
        else:
            yield chunk_from_payload(event)


def build_completion(chunks: Iterable[ChatCompletionChunk]) -> ChatCompletion:
    """The one reply of the chunks, by the rule of contracts C2.3."""

    items = list(chunks)
    if not items:
        raise _wrong("chunk list")
    reply = _Reply()
    for chunk in items:
        reply.add(chunk)
    return reply.completion(items[0])


def completion_from_lines(lines: Iterable[str]) -> ChatCompletion | StreamError:
    """The reply of the lines, or the error event that ended the stream."""

    chunks: list[ChatCompletionChunk] = []
    for item in read_chunks(lines):
        if isinstance(item, StreamError):
            return item
        chunks.append(item)
    return build_completion(chunks)


def _event_from_data(value: str) -> dict[str, Any] | StreamError | StreamDone:
    if value == "[DONE]":
        return DONE
    payload = _json_object(value)
    if "error" in payload:
        return _stream_error(payload["error"])
    return payload


def _json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except ValueError:
        raise FrameError("not_json", "the chat stream has a data line that is not JSON") from None
    if not isinstance(payload, dict):
        raise _wrong("data line")
    return payload


def _wrong(what: str) -> FrameError:
    return FrameError("wrong_shape", f"the chat stream has a wrong {what}")


def _stream_error(raw: object) -> StreamError:
    error = _mapping(raw, "error event")
    return StreamError(
        message=_text(error, "message", "error event"),
        type=_text(error, "type", "error event"),
        code=_text(error, "code", "error event"),
        should_retry=_retry_flag(error),
        retry_after=_opt_whole(error, "retry_after", "error event"),
    )


def _retry_flag(error: Mapping[str, Any]) -> bool | None:
    """should_retry: None when the key is missing or null; otherwise it must be a bool."""

    value = error.get("should_retry")
    if value is None or isinstance(value, bool):
        return value
    raise _wrong("error event")


def _chunk_choice(value: object) -> ChatChunkChoice:
    raw = _mapping(value, "choice")
    return ChatChunkChoice(
        index=_whole(raw, "index", "choice"),
        delta=_delta(_mapping(raw.get("delta"), "delta")),
        finish_reason=_opt_text(raw, "finish_reason", "choice"),
    )


def _delta(raw: Mapping[str, Any]) -> ChatDelta:
    calls = _opt_items(raw, "tool_calls", "delta")
    tool_calls = None if calls is None else tuple(_delta_tool_call(item) for item in calls)
    return ChatDelta(
        role=_opt_text(raw, "role", "delta"),
        content=_opt_text(raw, "content", "delta"),
        tool_calls=tool_calls,
        refusal=_opt_text(raw, "refusal", "delta"),
    )


def _delta_tool_call(value: object) -> ChatDeltaToolCall:
    # WHY: contracts C2.3: the Engine sends each tool call with its full arguments in one chunk,
    # so a delta with no id (an OpenAI-style piece of arguments) is a wrong shape. The reader
    # does not join pieces.
    raw = _mapping(value, "tool call")
    return ChatDeltaToolCall(
        index=_whole(raw, "index", "tool call"),
        id=_text(raw, "id", "tool call"),
        type=_text(raw, "type", "tool call"),
        function=_function(_mapping(raw.get("function"), "function")),
    )


def _function(raw: Mapping[str, Any]) -> ChatFunctionCall:
    return ChatFunctionCall(
        name=_text(raw, "name", "function"),
        arguments=_text(raw, "arguments", "function"),
    )


def _usage(value: object) -> ChatUsage:
    raw = _mapping(value, "usage")
    return ChatUsage(
        prompt_tokens=_whole(raw, "prompt_tokens", "usage"),
        completion_tokens=_whole(raw, "completion_tokens", "usage"),
        total_tokens=_whole(raw, "total_tokens", "usage"),
    )


def _info(value: object) -> InferenceInfo:
    raw = _mapping(value, "screamingface object")
    final_step = raw.get("final_step")
    return InferenceInfo(
        status=_text(raw, "status", "screamingface object"),
        abstain_reason=_opt_text(raw, "abstain_reason", "screamingface object"),
        cost_usd=_cost(raw),
        trace_id=_opt_text(raw, "trace_id", "screamingface object"),
        final_step=None if final_step is None else _final_step(final_step),
    )


def _final_step(value: object) -> FinalStep:
    raw = _mapping(value, "final step")
    return FinalStep(
        binding=_text(raw, "binding", "final step"),
        model=_text(raw, "model", "final step"),
        usage=None if raw.get("usage") is None else _usage(raw["usage"]),
        cached=raw.get("cached") is True,
    )


def _cost(raw: Mapping[str, Any]) -> Decimal | None:
    """The cost as a decimal string; a JSON number, NaN, Infinity or a negative value is a
    wrong shape."""

    value = raw.get("cost_usd")
    if value is None:
        return None
    if not isinstance(value, str):
        raise _wrong("cost")
    try:
        cost = Decimal(value)
    except InvalidOperation:
        raise _wrong("cost") from None
    if not cost.is_finite() or cost < 0:
        raise _wrong("cost")
    return cost


def _mapping(value: object, what: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _wrong(what)
    return value


def _text(raw: Mapping[str, Any], key: str, what: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise _wrong(what)
    return value


def _opt_text(raw: Mapping[str, Any], key: str, what: str) -> str | None:
    if raw.get(key) is None:
        return None
    return _text(raw, key, what)


def _whole(raw: Mapping[str, Any], key: str, what: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _wrong(what)
    return value


def _opt_whole(raw: Mapping[str, Any], key: str, what: str) -> int | None:
    if raw.get(key) is None:
        return None
    return _whole(raw, key, what)


def _items(raw: Mapping[str, Any], key: str, what: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise _wrong(what)
    return value


def _opt_items(raw: Mapping[str, Any], key: str, what: str) -> list[Any] | None:
    if raw.get(key) is None:
        return None
    return _items(raw, key, what)


def _last[T](old: T | None, new: T | None) -> T | None:
    """The new value when it is not None, else the old value."""

    return old if new is None else new


def _once[T](old: T | None, new: T | None, what: str) -> T | None:
    """The one value of a field that the Engine sends in one delta only (contracts C2.3).

    WHY: the stream is buffered (contracts C1.4), so the Engine sends the whole text in the first
    delta. A second value is a wrong shape: the reader does not join pieces, as for a tool call.
    """

    if new is None:
        return old
    if old is not None:
        raise _wrong(what)
    return new


@dataclass(slots=True)
class _Reply:
    """The values of one reply, as the chunks give them in order (contracts C2.3)."""

    content: str | None = None
    refusal: str | None = None
    finish_reason: str | None = None
    tool_calls: list[ChatDeltaToolCall] = field(default_factory=list)
    usage: ChatUsage | None = None
    info: InferenceInfo | None = None

    def add(self, chunk: ChatCompletionChunk) -> None:
        for choice in chunk.choices:
            self.content = _once(self.content, choice.delta.content, "content delta")
            self.refusal = _once(self.refusal, choice.delta.refusal, "refusal delta")
            self.finish_reason = _last(self.finish_reason, choice.finish_reason)
            for call in choice.delta.tool_calls or ():
                # INVARIANT: contracts C2.3: each tool call comes once, with its own index.
                if any(seen.index == call.index for seen in self.tool_calls):
                    raise _wrong("tool call index")
                self.tool_calls.append(call)
        self.usage = _last(self.usage, chunk.usage)
        self.info = _last(self.info, chunk.screamingface)

    def completion(self, first: ChatCompletionChunk) -> ChatCompletion:
        # WHY: unit U4 always sends include_usage, so the Engine always sends the usage chunk, and
        # contracts C1.3 needs usage and screamingface on the reply.
        finish_reason = self.finish_reason
        usage = self.usage
        info = self.info
        if finish_reason is None:
            raise _wrong("finish chunk")
        if usage is None:
            raise _wrong("usage chunk")
        if info is None:
            raise _wrong("screamingface object")
        ordered = sorted(self.tool_calls, key=lambda call: call.index)
        calls = tuple(ChatToolCall(id=c.id, type=c.type, function=c.function) for c in ordered)
        message = ChatMessage(
            role="assistant",
            content=self.content,
            tool_calls=calls if calls else None,
            refusal=self.refusal,
        )
        return ChatCompletion(
            id=first.id,
            object="chat.completion",
            created=first.created,
            model=first.model,
            choices=(ChatChoice(index=0, message=message, finish_reason=finish_reason),),
            usage=usage,
            screamingface=info,
        )

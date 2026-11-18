"""The chunk steps that the sync and the async chat transport share.

FEATURE: SDK model inference (docs/spec/2026-11-18-sdk-model-inference, contracts C1.4, C2.1, C2.3),
unit U5.
INVARIANT: no I/O. The functions turn one event into a chunk and all chunks into one reply. The
caller of a stream gets the chunks of the wire as they are (C2.1, P6).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterable, Mapping
from typing import Any

from screamingface._inference.error_map import invalid_response, stream_error
from screamingface._inference.frames import (
    FrameError,
    StreamError,
    build_completion,
    chunk_from_payload,
)
from screamingface.chat_completion import ChatCompletion, ChatCompletionChunk
from screamingface.errors import ExecutionError

__all__ = [
    "afailed_chunks",
    "awith_first",
    "chunk_of",
    "completion_of",
    "failed_chunks",
    "with_first",
]


def chunk_of(event: Mapping[str, Any] | StreamError, trace_id: str) -> ChatCompletionChunk:
    """The chunk of one event. The error event raises its ExecutionError (C2.4).

    A data object with a wrong shape raises FrameError; the transport maps it.
    """

    if isinstance(event, StreamError):
        raise stream_error(event, trace_id)
    return chunk_from_payload(event)


def completion_of(chunks: Iterable[ChatCompletionChunk], trace_id: str) -> ChatCompletion:
    """The one reply of all the chunks (C2.3). A wrong shape is invalid_response."""

    try:
        return build_completion(chunks)
    except FrameError as exc:
        raise invalid_response(exc.reason, trace_id) from exc


def with_first(
    first: ChatCompletionChunk, rest: Iterable[ChatCompletionChunk]
) -> Generator[ChatCompletionChunk, None, None]:
    """The first chunk, then the rest of the stream, as the wire gave them (contracts C1.4, P6)."""

    yield first
    yield from rest


async def awith_first(
    first: ChatCompletionChunk, rest: AsyncIterator[ChatCompletionChunk]
) -> AsyncGenerator[ChatCompletionChunk, None]:
    """The async twin of with_first."""

    yield first
    async for chunk in rest:
        yield chunk


def failed_chunks(error: ExecutionError) -> Generator[ChatCompletionChunk, None, None]:
    """A stream that raises error at its first chunk.

    WHY: an error after the 200 answer comes from the iteration, not from the call (C1.4).
    WHY `yield from ()`: it yields nothing, but it makes this function a generator, so the error
    comes at the first next() and not at the call.
    """

    yield from ()
    raise error


async def afailed_chunks(error: ExecutionError) -> AsyncGenerator[ChatCompletionChunk, None]:
    """The async twin of failed_chunks."""

    # WHY: the async form of `yield from ()` in failed_chunks; the loop body never runs.
    for chunk in ():
        yield chunk
    raise error

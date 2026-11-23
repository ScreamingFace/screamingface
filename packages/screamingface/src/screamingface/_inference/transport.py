"""The chat call of one `InferenceClient` on the wire, with its time limits and its retries.

FEATURE: SDK model inference, contracts C1.4, C2.1, C2.4, C2.5, P11, units U4 and U5.
Stage 1: one try (_try_chunks, _atry_chunks). A new trace, one POST through the client seam, and
the chunks of the answer, read line by line.
Stage 2: the retry until the first chunk (_first_chunk, _afirst_chunk). Only an error that the
Engine marked as safe, and at most max_retries more tries.
Stage 3: the caller forms. send_chat and send_chat_async give one reply; open_chat_stream and
open_chat_stream_async give a stream that is open at its first chunk.
INVARIANT: a retry happens only before the first chunk reaches the caller; after it, each error
goes to the caller.
INVARIANT: a try that sent the request and then lost the connection is never sent again
(inference_outcome_unknown), also with max_retries above 0.
INVARIANT: the with-block of each try closes the response on each exit (end, error, close,
garbage).
INVARIANT: this module does not import Client; it gets the seam through the EnginePostStream and
AsyncEnginePostStream Protocols.
AIDEV-NOTE: plan D3 puts the error map in this module; it is in _inference/error_map.py, because of
the 450-line limit.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager, aclosing, closing
from dataclasses import dataclass
from typing import Any, Final, Protocol

import httpx

from screamingface._inference.chunks import (
    afailed_chunks,
    awith_first,
    chunk_of,
    completion_of,
    failed_chunks,
    with_first,
)
from screamingface._inference.error_map import (
    client_timeout,
    engine_unavailable,
    invalid_response,
    outcome_unknown,
    refusal_error,
)
from screamingface._inference.frames import EventReader, FrameError
from screamingface._inference.request import ChatCall, chat_headers
from screamingface.chat_completion import (
    AsyncChatStream,
    ChatCompletion,
    ChatCompletionChunk,
    ChatStream,
)
from screamingface.errors import ExecutionError, ScreamingFaceError

CHAT_PATH: Final = "/v1/chat/completions"
#: WHY 60 s (P11, risk R7): the Engine sends a keep-alive line each 15 s by default, so 60 s with no
#: byte is a dead connection.
READ_LIMIT_S: Final = 60.0
_CONNECT_LIMIT_S: Final = 10.0
_WRITE_LIMIT_S: Final = 30.0
_POOL_LIMIT_S: Final = 30.0
_MAX_BACKOFF_S: Final = 30.0
_NEVER_SENT: Final[tuple[type[httpx.TransportError], ...]] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)
# WHY module globals for the time (review F13 of U4, decided in U5 for the sync and the async
# path): the tests put a fake clock and fake sleeps in these three names. Parameters would change
# each signature of this module for a test seam only, so module globals are the smaller change.
# Read them only at call time.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep
_async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

type _Chunks = Generator[ChatCompletionChunk, None, None]
type _AsyncChunks = AsyncGenerator[ChatCompletionChunk, None]


class EnginePostStream(Protocol):
    """A streamed POST on the Engine with the replay-safe mark (Client._engine_post_stream)."""

    def __call__(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: httpx.Timeout,
    ) -> AbstractContextManager[httpx.Response]: ...


class AsyncEnginePostStream(Protocol):
    """The async twin of EnginePostStream (AsyncClient._engine_post_stream)."""

    def __call__(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: httpx.Timeout,
    ) -> AbstractAsyncContextManager[httpx.Response]: ...


@dataclass(slots=True)
class _Try:
    """One try. started is True after the Engine answered 200, so the stream started.

    deadline is the end of the time of the caller (None: no limit). A stream sets it to None when
    the caller gets the first chunk (see open_chat_stream).
    """

    trace_id: str
    deadline: float | None
    started: bool = False


@dataclass(frozen=True, slots=True)
class _Opened[R]:
    """The first chunk, the open rest of the stream, and the state of the try."""

    first: ChatCompletionChunk
    rest: R
    state: _Try


@dataclass(frozen=True, slots=True)
class _Failed:
    """The last error of a call. started tells if it came after the 200 answer."""

    error: ExecutionError
    started: bool


# Stage 3: the caller forms.


def send_chat(post: EnginePostStream, engine_url: str, call: ChatCall) -> ChatCompletion:
    """The reply of one chat call, with at most call.max_retries more tries (contracts C2.5)."""

    # WHY the retry stops at the first chunk also here (C2.5): the stream of the Engine is
    # buffered, so an error after the first chunk does not come in practice; when one comes, the
    # run has a cost, so it is not sent again.
    opened = _first_chunk(post, engine_url, call)
    if isinstance(opened, _Failed):
        raise opened.error
    with closing(opened.rest) as rest:
        chunks = [opened.first, *rest]
    return completion_of(chunks, opened.state.trace_id)


def open_chat_stream(post: EnginePostStream, engine_url: str, call: ChatCall) -> ChatStream:
    """The stream of one chat call, open at its first chunk (contracts C1.4, C2.5).

    An error before the 200 answer is raised here. An error after it comes from the iteration.
    The caller gets each chunk of the wire as it is (C2.1, P6).
    """

    opened = _first_chunk(post, engine_url, call)
    if isinstance(opened, _Failed):
        if not opened.started:
            raise opened.error
        failed = failed_chunks(opened.error)
        return ChatStream(failed, failed.close)
    _hand_over(opened.state)
    # WHY close() of rest: closing the try generator exits its with-block, so the response closes
    # at once; the with_first generator then has nothing open.
    # WHY garbage closes: when Python frees the ChatStream, it frees the generators, and Python
    # closes a freed generator, which exits the with-block.
    return ChatStream(with_first(opened.first, opened.rest), opened.rest.close)


async def send_chat_async(
    post: AsyncEnginePostStream, engine_url: str, call: ChatCall
) -> ChatCompletion:
    """The async twin of send_chat."""

    opened = await _afirst_chunk(post, engine_url, call)
    if isinstance(opened, _Failed):
        raise opened.error
    async with aclosing(opened.rest) as rest:
        chunks = [opened.first, *[chunk async for chunk in rest]]
    return completion_of(chunks, opened.state.trace_id)


async def open_chat_stream_async(
    post: AsyncEnginePostStream, engine_url: str, call: ChatCall
) -> AsyncChatStream:
    """The async twin of open_chat_stream."""

    opened = await _afirst_chunk(post, engine_url, call)
    if isinstance(opened, _Failed):
        if not opened.started:
            raise opened.error
        failed = afailed_chunks(opened.error)
        return AsyncChatStream(failed, failed.aclose)
    _hand_over(opened.state)
    # WHY aclose() of rest: the same rule as open_chat_stream.
    return AsyncChatStream(awith_first(opened.first, opened.rest), opened.rest.aclose)


def _hand_over(state: _Try) -> None:
    """Stop the time limit of the caller when the caller gets the first chunk of a stream.

    WHY (review F1 of U5): the stream of the Engine is buffered, so after the first chunk the rest
    of the answer is already sent. The time that the caller uses between two chunks is not a
    slow Engine, and a client_timeout would lose a reply that has a cost. The read limit of the
    try still stops a dead connection.
    """

    state.deadline = None


# Stage 2: the retry until the first chunk.


def _first_chunk(
    post: EnginePostStream, engine_url: str, call: ChatCall
) -> _Opened[_Chunks] | _Failed:
    """Try until the first chunk; send again only an error that the Engine marked as safe (C2.5).

    An error that is not an ExecutionError (for example PlanningError) passes out at once.
    """

    deadline = _deadline(call.timeout)
    attempt = 0
    while True:
        headers, trace_id = chat_headers(use_cache=call.use_cache)
        state = _Try(trace_id, deadline)
        chunks = _try_chunks(post, engine_url, call, headers, state)
        try:
            first = next(chunks, None)
        except ExecutionError as exc:
            error = exc
        else:
            if first is not None:
                return _Opened(first, chunks, state)
            # WHY wrong_shape: a [DONE] with no chunk before it; build_completion gives the same.
            error = invalid_response("wrong_shape", trace_id)
        wait = _retry_wait(error, attempt, call.max_retries, deadline)
        if wait is None:
            return _Failed(error, started=state.started)
        _sleep(wait)
        attempt += 1


async def _afirst_chunk(
    post: AsyncEnginePostStream, engine_url: str, call: ChatCall
) -> _Opened[_AsyncChunks] | _Failed:
    """The async twin of _first_chunk."""

    deadline = _deadline(call.timeout)
    attempt = 0
    while True:
        headers, trace_id = chat_headers(use_cache=call.use_cache)
        state = _Try(trace_id, deadline)
        chunks = _atry_chunks(post, engine_url, call, headers, state)
        try:
            first = await anext(chunks, None)
        except ExecutionError as exc:
            error = exc
        else:
            if first is not None:
                return _Opened(first, chunks, state)
            error = invalid_response("wrong_shape", trace_id)
        wait = _retry_wait(error, attempt, call.max_retries, deadline)
        if wait is None:
            return _Failed(error, started=state.started)
        await _async_sleep(wait)
        attempt += 1


def _retry_wait(
    error: ExecutionError, attempt: int, max_retries: int, deadline: float | None
) -> float | None:
    """The wait before the next try, or None when the call must not be sent again."""

    # WHY permanent is not False: only the Engine flag (x-should-retry or should_retry) makes an
    # ExecutionError retryable; outcome_unknown, client_timeout and invalid_response are permanent.
    if attempt >= max_retries or error.permanent is not False:
        return None
    wait = _wait_seconds(error, attempt)
    if deadline is not None and _clock() + wait >= deadline:
        return None
    return wait


def _wait_seconds(error: ExecutionError, attempt: int) -> float:
    details = error.details
    retry_after = details.get("retry_after") if isinstance(details, Mapping) else None
    if isinstance(retry_after, int | float) and not isinstance(retry_after, bool):
        return float(retry_after)
    return min(2.0**attempt, _MAX_BACKOFF_S)


# Stage 1: one try.


def _try_chunks(
    post: EnginePostStream,
    engine_url: str,
    call: ChatCall,
    headers: Mapping[str, str],
    state: _Try,
) -> _Chunks:
    """The chunks of one try. The with-block closes the response on each exit."""

    timeout = _timeouts(_remaining(state.deadline, state.trace_id))
    try:
        with post(CHAT_PATH, json=call.body, headers=headers, timeout=timeout) as response:
            if response.status_code != 200:
                response.read()
                raise refusal_error(response, state.trace_id)
            state.started = True
            yield from _chunks(response, state)
    except httpx.HTTPError as exc:
        raise _transport_error(exc, engine_url, state) from exc


async def _atry_chunks(
    post: AsyncEnginePostStream,
    engine_url: str,
    call: ChatCall,
    headers: Mapping[str, str],
    state: _Try,
) -> _AsyncChunks:
    """The async twin of _try_chunks."""

    timeout = _timeouts(_remaining(state.deadline, state.trace_id))
    try:
        async with post(CHAT_PATH, json=call.body, headers=headers, timeout=timeout) as response:
            if response.status_code != 200:
                await response.aread()
                raise refusal_error(response, state.trace_id)
            state.started = True
            async with aclosing(_achunks(response, state)) as chunks:
                async for chunk in chunks:
                    yield chunk
    except httpx.HTTPError as exc:
        raise _transport_error(exc, engine_url, state) from exc


def _chunks(response: httpx.Response, state: _Try) -> _Chunks:
    # WHY no strict decoder: httpx decodes the stream with errors='replace', so a byte that is not
    # UTF-8 becomes U+FFFD and is not invalid_response. The Engine writes each data line with
    # json.dumps(ensure_ascii=True) (E/chat/sse.py:38), so its lines are ASCII. Only a damaged
    # stream can hold such a byte, and the SDK accepts that.
    reader = EventReader()
    try:
        for line in response.iter_lines():
            chunk = _line_chunk(reader, line, state)
            if chunk is not None:
                yield chunk
            if reader.ended:
                return
        reader.end()
    except FrameError as exc:
        raise invalid_response(exc.reason, state.trace_id) from exc


async def _achunks(response: httpx.Response, state: _Try) -> _AsyncChunks:
    # WHY: the same rules as _chunks; only the read differs.
    reader = EventReader()
    try:
        async for line in response.aiter_lines():
            chunk = _line_chunk(reader, line, state)
            if chunk is not None:
                yield chunk
            if reader.ended:
                return
        reader.end()
    except FrameError as exc:
        raise invalid_response(exc.reason, state.trace_id) from exc


def _line_chunk(reader: EventReader, line: str, state: _Try) -> ChatCompletionChunk | None:
    """The chunk of one line, or None (the step that _chunks and _achunks share).

    WHY the deadline at each line: httpx limits each read, not the whole call (P11). So the error
    comes when the next line arrives: up to one keep-alive interval (15 s by default) after the
    deadline. When no byte comes, the read limit of the try stops the read. That limit is
    min(60 s, the time left at the start of the try), so a silent connection stops at the
    deadline at the latest. An exact limit needs a second thread that closes the response; the
    SDK does not use one.
    """

    _check_deadline(state.deadline, state.trace_id)
    event = reader.push(line)
    return None if event is None else chunk_of(event, state.trace_id)


def _transport_error(exc: httpx.HTTPError, engine_url: str, state: _Try) -> ScreamingFaceError:
    """The SDK error of a transport error of one try."""

    trace_id, deadline = state.trace_id, state.deadline
    if isinstance(exc, _NEVER_SENT):
        return engine_unavailable(engine_url, trace_id)
    # WHY: only the clock tells if the time of the caller is over. A read or write timeout inside
    # the time of the caller means that the request was sent and the outcome is unknown.
    if isinstance(exc, httpx.TimeoutException) and deadline is not None and _clock() >= deadline:
        return client_timeout(trace_id)
    return outcome_unknown(trace_id)


def _deadline(timeout: float | None) -> float | None:
    return None if timeout is None else _clock() + timeout


def _check_deadline(deadline: float | None, trace_id: str) -> None:
    if deadline is not None and _clock() >= deadline:
        raise client_timeout(trace_id)


def _remaining(deadline: float | None, trace_id: str) -> float:
    """The seconds that are left to the caller (math.inf with no timeout)."""

    if deadline is None:
        return math.inf
    remaining = deadline - _clock()
    if remaining <= 0:
        raise client_timeout(trace_id)
    return remaining


def _timeouts(remaining: float) -> httpx.Timeout:
    # WHY: these limits replace the 30 s default of the client (C2.1); each one is bounded by the
    # time that is left to the caller. httpx has no total limit, so _line_chunk checks the deadline.
    return httpx.Timeout(
        connect=min(_CONNECT_LIMIT_S, remaining),
        read=min(READ_LIMIT_S, remaining),
        write=min(_WRITE_LIMIT_S, remaining),
        pool=min(_POOL_LIMIT_S, remaining),
    )


__all__ = [
    "CHAT_PATH",
    "READ_LIMIT_S",
    "AsyncEnginePostStream",
    "EnginePostStream",
    "open_chat_stream",
    "open_chat_stream_async",
    "send_chat",
    "send_chat_async",
]

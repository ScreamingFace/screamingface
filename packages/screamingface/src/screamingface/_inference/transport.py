"""The chat call of one `ModelInference` on the wire, with its time limits and its retries.

FEATURE: SDK model inference, contracts C2.1, C2.4, C2.5, P11, unit U4.
Stage 1: one try. A new trace, one POST through the client seam, and the answer read line by line.
Stage 2: the retry. Only an error that the Engine marked as safe, and at most max_retries more
tries.
INVARIANT: a try that sent the request and then lost the connection is never sent again
(inference_outcome_unknown), also with max_retries above 0. The with-block closes the response on
each exit.
INVARIANT: this module does not import Client; it gets the seam through the EnginePostStream
Protocol.
AIDEV-NOTE: unit U5 adds the async path and the stream=True path next to send_chat.
AIDEV-NOTE: plan D3 puts the error map in this module; it is in _inference/error_map.py, because of
the 450-line limit and the async twin of U5.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from typing import Any, Final, Protocol

import httpx

from screamingface._inference.error_map import (
    client_timeout,
    engine_unavailable,
    invalid_response,
    outcome_unknown,
    refusal_error,
    stream_error,
)
from screamingface._inference.frames import FrameError, StreamError, completion_from_lines
from screamingface._inference.request import ChatCall, chat_headers
from screamingface.chat_completion import ChatCompletion
from screamingface.errors import ExecutionError

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
# AIDEV-NOTE: the tests put a fake clock and a fake sleep in these two names (MI-14, MI-15). Read
# them only at call time.
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


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


def send_chat(post: EnginePostStream, engine_url: str, call: ChatCall) -> ChatCompletion:
    """The reply of one chat call, with at most call.max_retries more tries (contracts C2.5)."""

    deadline = None if call.timeout is None else _clock() + call.timeout
    attempt = 0
    while True:
        try:
            return _one_try(post, engine_url, call, deadline)
        except ExecutionError as exc:
            wait = _retry_wait(exc, attempt, call.max_retries, deadline)
            if wait is None:
                raise
            _sleep(wait)
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


def _one_try(
    post: EnginePostStream, engine_url: str, call: ChatCall, deadline: float | None
) -> ChatCompletion:
    headers, trace_id = chat_headers(use_cache=call.use_cache)
    timeout = _timeouts(_remaining(deadline, trace_id))
    try:
        with post(CHAT_PATH, json=call.body, headers=headers, timeout=timeout) as response:
            return _answer(response, trace_id, deadline)
    except _NEVER_SENT as exc:
        raise engine_unavailable(engine_url, trace_id) from exc
    except httpx.TimeoutException as exc:
        # WHY: only the clock tells if the time of the caller is over. A read or write timeout
        # inside the time of the caller means that the request was sent and the outcome is unknown.
        if deadline is not None and _clock() >= deadline:
            raise client_timeout(trace_id) from exc
        raise outcome_unknown(trace_id) from exc
    except httpx.HTTPError as exc:
        raise outcome_unknown(trace_id) from exc


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
    # time that is left to the caller. httpx has no total limit, so _lines checks the deadline.
    return httpx.Timeout(
        connect=min(_CONNECT_LIMIT_S, remaining),
        read=min(READ_LIMIT_S, remaining),
        write=min(_WRITE_LIMIT_S, remaining),
        pool=min(_POOL_LIMIT_S, remaining),
    )


def _answer(response: httpx.Response, trace_id: str, deadline: float | None) -> ChatCompletion:
    if response.status_code != 200:
        response.read()
        raise refusal_error(response, trace_id)
    try:
        result = completion_from_lines(_lines(response, deadline, trace_id))
    except FrameError as exc:
        raise invalid_response(exc.reason, trace_id) from exc
    if isinstance(result, StreamError):
        raise stream_error(result, trace_id)
    return result


def _lines(response: httpx.Response, deadline: float | None, trace_id: str) -> Iterator[str]:
    # WHY no strict decoder: httpx decodes the stream with errors='replace', so a byte that is not
    # UTF-8 becomes U+FFFD and is not invalid_response. The Engine writes each data line with
    # json.dumps(ensure_ascii=True) (E/chat/sse.py:38), so its lines are ASCII. Only a damaged
    # stream can hold such a byte, and the SDK accepts that.
    for line in response.iter_lines():
        # WHY at each line: httpx limits each read, not the whole call (P11). So the error comes
        # when the next line arrives: up to one keep-alive interval (15 s by default) after the
        # deadline. When no byte comes, the read limit of the try stops the read. That limit is
        # min(60 s, the time left at the start of the try), so a silent connection stops at the
        # deadline at the latest. An exact limit needs a second thread that closes the response;
        # the SDK does not use one.
        if deadline is not None and _clock() >= deadline:
            raise client_timeout(trace_id)
        yield line


__all__ = ["CHAT_PATH", "READ_LIMIT_S", "EnginePostStream", "send_chat"]

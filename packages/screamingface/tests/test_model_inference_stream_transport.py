"""MI-20, MI-21 and the stream half of MI-31: the sync stream of one chat call through sf.Client and
the seam (contracts C1.4, C2.1, C2.5).
"""

from __future__ import annotations

import gc
from typing import Any

import httpx
import pytest
from _chat_engine import (
    answers,
    envelope,
    fake_time,
    recording_client,
    reply_body,
    sent_body,
    sse,
    streamed,
    trace_id_of,
)
from _chat_frames import DONE_LINE, KEEP_ALIVE, data_line, engine_stream, error_line
from _chat_stream import chunks_of

import screamingface as sf
from screamingface._inference.request import INCLUDE_USAGE, ChatCall, chat_body
from screamingface._inference.transport import open_chat_stream, send_chat
from screamingface.chat_completion import ChatStream
from screamingface.errors import EngineUnavailableError, ExecutionError, PlanningError

BODY = chat_body(
    "openrouter/a", [{"role": "user", "content": "Hello"}], None, stream_options=INCLUDE_USAGE
)
PAYLOADS = engine_stream({"role": "assistant", "content": "Hello"}, "stop")
RESTART: dict[str, Any] = {
    "message": "restart",
    "type": "server_error",
    "code": "server_restarting",
    "should_retry": True,
}


def call(**changes: Any) -> ChatCall:
    return ChatCall(
        **{"body": BODY, "use_cache": True, "max_retries": 0, "timeout": None, **changes}
    )


def open_stream(client: sf.Client, chat: ChatCall) -> ChatStream:
    return open_chat_stream(client._engine_post_stream, client.engine_url, chat)


def test_stream_gives_each_chunk_of_the_wire_as_it_is() -> None:
    requests: list[httpx.Request] = []
    with recording_client(answers(sse(reply_body())), requests) as client:
        stream = open_stream(client, call())
        chunks = list(stream)
    assert isinstance(stream, ChatStream)
    assert chunks == chunks_of(PAYLOADS)
    assert len(requests) == 1
    assert sent_body(requests[0]) == BODY


def test_the_response_stays_open_while_the_caller_iterates_and_closes_at_the_end() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        stream = open_stream(client, call())
        assert closed == []
        next(stream)
        assert closed == []
        list(stream)
        assert closed == [True]


def test_close_before_the_end_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        stream = open_stream(client, call())
        next(stream)
        stream.close()
        assert closed == [True]
        assert list(stream) == []


def test_the_with_block_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        with open_stream(client, call()) as stream:
            assert next(stream).text == "Hello"
            assert closed == []
        assert closed == [True]


def test_break_in_a_loop_over_a_stream_that_nothing_keeps_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        for _chunk in open_stream(client, call()):
            break
        gc.collect()
        assert closed == [True]


def test_a_stream_that_python_frees_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        stream = open_stream(client, call())
        assert closed == []
        del stream
        gc.collect()
        assert closed == [True]


def test_error_event_comes_from_the_iteration_not_from_the_call() -> None:
    requests: list[httpx.Request] = []
    body = KEEP_ALIVE + error_line(
        message="stop", type="server_error", code="timeout", should_retry=False
    )
    with recording_client(answers(sse(body)), requests) as client:
        stream = open_stream(client, call())
        with pytest.raises(ExecutionError) as info:
            next(stream)
    exc = info.value
    assert exc.code == "timeout"
    assert exc.permanent is True
    assert exc.trace_id == trace_id_of(requests[0])
    assert len(requests) == 1


def test_an_answer_that_is_not_200_is_raised_by_the_call() -> None:
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(400, "recipe_invalid"),
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "1"}),
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(PlanningError):
            open_stream(client, call())
        with pytest.raises(ExecutionError) as info:
            open_stream(client, call(max_retries=0))
    assert info.value.code == "overloaded"
    assert len(requests) == 2


def test_retry_happens_before_the_first_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(sse(error_line(**RESTART, retry_after=2)), sse(reply_body()))
    with recording_client(handler, requests) as client:
        stream = open_stream(client, call(max_retries=1))
        assert len(requests) == 2
        assert fake.sleeps == [2.0]
        assert [chunk.text for chunk in stream] == [
            "Hello",
            "",
            "",
        ]  # WHY: reply_body() has the usage chunk; the stream gives it as it is


def test_no_retry_after_the_first_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    body = data_line(PAYLOADS[0]) + error_line(**RESTART, retry_after=1)
    with recording_client(answers(sse(body)), requests) as client:
        stream = open_stream(client, call(max_retries=2))
        assert next(stream).text == "Hello"
        with pytest.raises(ExecutionError) as info:
            next(stream)
    assert info.value.code == "server_restarting"
    assert info.value.permanent is False
    assert len(requests) == 1
    assert fake.sleeps == []


def test_a_silent_connection_after_the_first_chunk_is_outcome_unknown_from_the_iteration() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    parts: list[Any] = [data_line(PAYLOADS[0]), httpx.ReadTimeout("silent")]
    with recording_client(answers(streamed(parts, closed)), requests) as client:
        stream = open_stream(client, call(max_retries=2))
        assert next(stream).text == "Hello"
        with pytest.raises(ExecutionError) as info:
            next(stream)
    assert info.value.code == "inference_outcome_unknown"
    assert closed == [True]
    assert len(requests) == 1


def test_done_with_no_chunk_is_invalid_response_from_the_iteration() -> None:
    requests: list[httpx.Request] = []
    with recording_client(answers(sse(DONE_LINE)), requests) as client:
        stream = open_stream(client, call())
        with pytest.raises(ExecutionError) as info:
            next(stream)
    assert info.value.code == "invalid_response"
    assert info.value.details == {"reason": "wrong_shape"}


def test_a_refused_connection_is_engine_unavailable_from_the_call() -> None:
    requests: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with recording_client(refuse, requests) as client:
        with pytest.raises(EngineUnavailableError):
            open_stream(client, call(max_retries=2))
    assert len(requests) == 1


def test_the_time_of_the_caller_between_chunks_is_not_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review F1 of U5: after the first chunk, the rest of the buffered answer is already sent, so
    the work of the caller between two chunks does not raise client_timeout."""

    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    with recording_client(answers(sse(reply_body())), requests) as client:
        stream = open_stream(client, call(timeout=5.0))
        first = next(stream)
        fake.advance(60.0)
        rest = list(stream)

    assert [first, *rest] == chunks_of(PAYLOADS)


def test_a_reply_call_still_stops_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deadline of a call with stream=False still counts to the end of the answer (P11)."""

    fake = fake_time(monkeypatch)
    late = data_line(PAYLOADS[0]) + KEEP_ALIVE + DONE_LINE
    parts: list[Any] = [late[: len(data_line(PAYLOADS[0]))], lambda: fake.advance(10.0)]
    parts.append(late[len(data_line(PAYLOADS[0])) :])
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed(parts, [])), requests) as client:
        with pytest.raises(ExecutionError) as info:
            send_chat(client._engine_post_stream, client.engine_url, call(timeout=5.0))

    assert info.value.code == "client_timeout"

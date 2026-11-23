"""MI-20, MI-21 and the stream half of MI-31 through InferenceClient with a sync client
(contracts C1.2, C1.4, C2.5)."""

from __future__ import annotations

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
from _chat_frames import KEEP_ALIVE, engine_stream, error_line
from _chat_stream import chunks_of, engine_for, engine_payloads

from screamingface.chat_completion import ChatCompletion, ChatStream, ChatUsage
from screamingface.errors import ExecutionError
from screamingface.inference import InferenceClient

PAYLOADS = engine_stream({"role": "assistant", "content": "Hello"}, "stop")


stream_engine = engine_for(PAYLOADS)


def test_stream_true_gives_the_engine_chunks_in_order() -> None:
    requests: list[httpx.Request] = []
    with recording_client(stream_engine, requests) as client:
        stream = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True
        )
        assert isinstance(stream, ChatStream)
        chunks = list(stream)

    assert chunks == chunks_of(engine_payloads(PAYLOADS, include_usage=False))
    # INVARIANT (C2.1, P6): with stream=True the wire carries the stream_options of the caller.
    assert "stream_options" not in sent_body(requests[0])
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert chunks[-1].screamingface is not None
    assert chunks[-1].screamingface.status == "answered"


def test_include_usage_adds_the_last_chunk() -> None:
    requests: list[httpx.Request] = []
    with recording_client(stream_engine, requests) as client:
        stream = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True, stream_options={"include_usage": True}
        )
        chunks = list(stream)

    assert chunks == chunks_of(PAYLOADS)
    assert sent_body(requests[0])["stream_options"] == {"include_usage": True}
    assert chunks[-1].choices == ()
    assert chunks[-1].usage == ChatUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)


def test_stream_options_has_no_effect_without_stream() -> None:
    requests: list[httpx.Request] = []
    with recording_client(stream_engine, requests) as client:
        reply = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream_options={"include_usage": False}
        )

    assert isinstance(reply, ChatCompletion)
    assert sent_body(requests[0])["stream_options"] == {"include_usage": True}


def test_closing_a_stream_early_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        stream = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True
        )
        next(stream)
        assert closed == []
        stream.close()
        assert closed == [True]
        assert list(stream) == []


def test_leaving_the_with_block_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    with recording_client(answers(streamed([reply_body()], closed)), requests) as client:
        with InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True
        ) as stream:
            next(stream)
            assert closed == []
        assert closed == [True]


def test_error_event_raises_from_the_iteration() -> None:
    error_body = KEEP_ALIVE + error_line(
        message="stop", type="server_error", code="timeout", should_retry=False
    )
    requests: list[httpx.Request] = []
    with recording_client(answers(sse(error_body)), requests) as client:
        stream = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True
        )
        with pytest.raises(ExecutionError) as error:
            list(stream)

    assert error.value.code == "timeout"
    assert error.value.permanent is True
    assert error.value.trace_id == trace_id_of(requests[0])


def test_error_event_with_no_flag_is_permanent_with_stream_true() -> None:
    error_body = error_line(message="failed", type="server_error", code="timeout")
    requests: list[httpx.Request] = []
    with recording_client(answers(sse(error_body)), requests) as client:
        stream = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True, max_retries=2
        )
        with pytest.raises(ExecutionError) as error:
            list(stream)

    assert error.value.permanent is True
    assert len(requests) == 1


def test_max_retries_works_with_stream_true(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    restart = error_line(
        message="restart",
        type="server_error",
        code="server_restarting",
        should_retry=True,
        retry_after=5,
    )
    requests: list[httpx.Request] = []
    handler = answers(sse(restart), sse(reply_body()))
    with recording_client(handler, requests) as client:
        stream = InferenceClient("openrouter/a", client=client).chat.completions.create(
            "Hello", stream=True, max_retries=1
        )
        texts = [chunk.text for chunk in stream]

    assert texts == [
        "Hello",
        "",
        "",
    ]  # WHY: reply_body() has the usage chunk; the stream gives it as it is
    assert len(requests) == 2
    assert fake.sleeps == [5.0]


def test_engine_refusal_with_stream_true_is_raised_by_the_call() -> None:
    refusal = envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "3"})
    requests: list[httpx.Request] = []
    with recording_client(answers(refusal), requests) as client:
        llm = InferenceClient("openrouter/a", client=client)
        with pytest.raises(ExecutionError) as error:
            llm.chat.completions.create("Hello", stream=True)

    assert error.value.permanent is False
    assert len(requests) == 1

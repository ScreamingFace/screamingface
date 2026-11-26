"""MI-14 and MI-15 (contracts C2.4, C2.5, P11), with a fake clock.

Each test that needs time uses fake = fake_time(monkeypatch), so no test sleeps.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from _chat_engine import (
    answers,
    envelope,
    fake_time,
    ok,
    recording_client,
    reply_body,
    sse,
    streamed,
)
from _chat_frames import KEEP_ALIVE, error_line

import screamingface as sf
from screamingface._inference.request import INCLUDE_USAGE, ChatCall, chat_body
from screamingface._inference.transport import send_chat
from screamingface.chat_completion import ChatCompletion
from screamingface.errors import ExecutionError, ScreamingFaceError

BODY = chat_body(
    "openrouter/a", [{"role": "user", "content": "Hello"}], None, stream_options=INCLUDE_USAGE
)


def call(**changes: Any) -> ChatCall:
    return ChatCall(
        **{"body": BODY, "use_cache": True, "max_retries": 0, "timeout": None, **changes}
    )


def run(client: sf.Client, chat: ChatCall) -> ChatCompletion:
    return send_chat(client._engine_post_stream, client.engine_url, chat)


def test_caller_timeout_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    handler = answers(streamed([KEEP_ALIVE, lambda: fake.advance(10.0), reply_body()], closed))
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(timeout=5.0))
    assert info.value.code == "client_timeout"
    assert info.value.permanent is True
    assert closed == [True]
    assert len(requests) == 1
    assert requests[0].extensions["timeout"]["read"] == 5.0
    assert requests[0].extensions["timeout"]["connect"] == 5.0
    assert requests[0].extensions["timeout"]["write"] == 5.0
    assert requests[0].extensions["timeout"]["pool"] == 5.0


def test_a_read_timeout_after_the_caller_deadline_is_a_client_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []

    def slow(request: httpx.Request) -> httpx.Response:
        fake.advance(5.0)
        raise httpx.ReadTimeout("slow", request=request)

    with recording_client(slow, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(timeout=5.0, max_retries=2))
    assert info.value.code == "client_timeout"
    assert len(requests) == 1


def test_a_long_timeout_keeps_the_60_s_read_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        run(client, call(timeout=600.0))
    assert requests[0].extensions["timeout"]["read"] == 60.0
    assert requests[0].extensions["timeout"]["connect"] == 10.0
    assert requests[0].extensions["timeout"]["write"] == 30.0
    assert requests[0].extensions["timeout"]["pool"] == 30.0


def test_no_timeout_keeps_the_fixed_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        run(client, call(timeout=None))
    assert requests[0].extensions["timeout"] == {
        "connect": 10.0,
        "read": 60.0,
        "write": 30.0,
        "pool": 30.0,
    }


def test_a_silent_stream_past_the_caller_timeout_is_a_client_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_time(monkeypatch)
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    parts: list[Any] = [
        KEEP_ALIVE,
        lambda: fake.advance(50.0),
        KEEP_ALIVE,
        lambda: fake.advance(60.0),
        httpx.ReadTimeout("silent"),
    ]
    with recording_client(answers(streamed(parts, closed)), requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(timeout=100.0, max_retries=2))
    assert info.value.code == "client_timeout"
    assert info.value.permanent is True
    assert len(requests) == 1
    assert closed == [True]


def test_a_write_timeout_inside_the_caller_timeout_is_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []

    def slow_write(request: httpx.Request) -> httpx.Response:
        fake.advance(30.0)
        raise httpx.WriteTimeout("slow", request=request)

    with recording_client(slow_write, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(timeout=45.0, max_retries=2))
    assert info.value.code == "inference_outcome_unknown"
    assert info.value.permanent is True
    assert len(requests) == 1


def test_client_timeout_comes_at_most_one_keep_alive_after_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_time(monkeypatch)
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    parts: list[Any] = []
    for _ in range(8):
        parts += [KEEP_ALIVE, lambda: fake.advance(15.0)]
    parts.append(reply_body())
    with recording_client(answers(streamed(parts, closed)), requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(timeout=100.0))
    assert info.value.code == "client_timeout"
    # INVARIANT: FakeTime starts at 1000.0, and the Engine sends a keep-alive each 15 s.
    assert fake.now - 1000.0 <= 100.0 + 15.0


def test_no_retry_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "1"})
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call())
    assert info.value.permanent is False
    assert len(requests) == 1
    assert fake.sleeps == []


def test_max_retries_obeys_the_engine_flag_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "2"}),
        sse(
            KEEP_ALIVE
            + error_line(
                message="restart",
                type="server_error",
                code="server_restarting",
                should_retry=True,
                retry_after=5,
            )
        ),
        sse(reply_body()),
    )
    with recording_client(handler, requests) as client:
        reply = run(client, call(max_retries=2))
    assert reply.text == "Hello"
    assert len(requests) == 3
    assert fake.sleeps == [2.0, 5.0]
    traces = {request.headers["traceparent"] for request in requests}
    assert len(traces) == 3


def test_retry_stops_at_the_last_try_and_raises_the_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        *(
            envelope(503, "engine_busy", message=message, headers={"x-should-retry": "true"})
            for message in ("one", "two", "three")
        )
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(max_retries=2))
    assert "three" in info.value.message
    assert len(requests) == 3
    assert fake.sleeps == [1.0, 2.0]


def test_backoff_has_a_maximum_of_30_s(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        *(envelope(503, "engine_busy", headers={"x-should-retry": "true"}) for _ in range(8))
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError):
            run(client, call(max_retries=7))
    assert len(requests) == 8
    assert fake.sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(
            lambda: envelope(503, "engine_busy", headers={"x-should-retry": "false"}),
            id="503-flag-false",
        ),
        pytest.param(lambda: envelope(500, "server_error"), id="500-no-flag"),
        pytest.param(lambda: envelope(400, "recipe_invalid"), id="400"),
        pytest.param(lambda: envelope(403, "forbidden"), id="403"),
        pytest.param(
            lambda: sse(
                error_line(
                    message="failed", type="server_error", code="timeout", should_retry=False
                )
            ),
            id="stream-flag-false",
        ),
    ],
)
def test_an_error_that_the_engine_did_not_mark_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, make: Any
) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    with recording_client(answers(make()), requests) as client:
        with pytest.raises(ScreamingFaceError):
            run(client, call(max_retries=3))
    assert len(requests) == 1
    assert fake.sleeps == []


def test_a_wait_past_the_caller_timeout_is_not_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "30"})
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(timeout=10.0, max_retries=2))
    assert info.value.code == "overloaded"
    assert len(requests) == 1
    assert fake.sleeps == []

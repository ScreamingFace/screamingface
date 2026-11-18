"""MI-11 (wiring), MI-12, MI-13, MI-31 (sync part) and the C2.1 request, through sf.Client and the
seam (contracts C2.1, C2.3, C2.4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _chat_engine import (
    CHAT_PATH,
    ENGINE_URL,
    answers,
    envelope,
    ok,
    recording_client,
    reply_body,
    sent_body,
    sse,
    streamed,
    trace_id_of,
)
from _chat_frames import KEEP_ALIVE, engine_stream, error_line, wire

import screamingface as sf
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._inference.request import INCLUDE_USAGE, ChatCall, chat_body
from screamingface._inference.transport import send_chat
from screamingface.chat_completion import ChatCompletion
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    PlanningError,
    ScreamingFaceError,
)

BODY = chat_body(
    "openrouter/a", [{"role": "user", "content": "Hello"}], None, stream_options=INCLUDE_USAGE
)


def call(**changes: Any) -> ChatCall:
    return ChatCall(
        **{"body": BODY, "use_cache": True, "max_retries": 0, "timeout": None, **changes}
    )


def run(client: sf.Client, chat: ChatCall) -> ChatCompletion:
    return send_chat(client._engine_post_stream, client.engine_url, chat)


def test_one_try_sends_one_streamed_post_and_gives_the_reply() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        reply = run(client, call())
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == CHAT_PATH
    assert sent_body(request) == BODY
    assert request.headers["accept"] == "text/event-stream"
    assert request.headers["content-type"].startswith("application/json")
    assert "traceparent" in request.headers
    assert "cache-control" not in request.headers
    assert request.extensions[_REPLAY_SAFE] is True
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 60.0,
        "write": 30.0,
        "pool": 30.0,
    }
    assert reply.text == "Hello"


def test_no_store_with_use_cache_false() -> None:
    requests: list[httpx.Request] = []
    with recording_client(ok, requests) as client:
        run(client, call(use_cache=False))
    assert requests[0].headers["cache-control"] == "no-store"


def test_keep_alive_lines_are_dropped_on_the_wire() -> None:
    requests: list[httpx.Request] = []
    handler = answers(sse(KEEP_ALIVE + KEEP_ALIVE + reply_body()))
    with recording_client(handler, requests) as client:
        reply = run(client, call())
    assert reply.text == "Hello"


@pytest.mark.parametrize(
    ("make", "cls", "permanent"),
    [
        pytest.param(
            lambda: httpx.Response(404, text="Not Found"),
            EngineCapabilityError,
            True,
            id="404-no-route",
        ),
        pytest.param(lambda: envelope(401, "invalid_api_key"), AuthenticationError, True, id="401"),
        pytest.param(
            lambda: envelope(400, "recipe_invalid", param="model"),
            PlanningError,
            True,
            id="400",
        ),
        pytest.param(
            lambda: envelope(
                429,
                "overloaded",
                headers={"x-should-retry": "true", "Retry-After": "3"},
            ),
            ExecutionError,
            False,
            id="429",
        ),
        pytest.param(lambda: envelope(503, "engine_busy"), ExecutionError, True, id="503"),
    ],
)
def test_error_map_before_the_stream_through_the_client(
    make: Callable[[], httpx.Response], cls: type[ScreamingFaceError], permanent: bool
) -> None:
    requests: list[httpx.Request] = []
    with recording_client(answers(make()), requests) as client:
        with pytest.raises(ScreamingFaceError) as info:
            run(client, call())
    exc = info.value
    assert type(exc) is cls
    assert exc.permanent is permanent
    assert exc.trace_id == trace_id_of(requests[0])
    assert len(requests) == 1


def test_retry_after_of_a_429_is_in_details() -> None:
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "3"})
    )
    with recording_client(handler, requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call())
    assert info.value.details == {"retry_after": 3}


@pytest.mark.parametrize("cls", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_never_sent_is_engine_unavailable(cls: type[httpx.TransportError]) -> None:
    requests: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        raise cls("refused", request=request)

    with recording_client(refuse, requests) as client:
        with pytest.raises(EngineUnavailableError) as info:
            run(client, call(max_retries=2))
    exc = info.value
    assert exc.permanent is False
    assert exc.engine_url == ENGINE_URL
    assert exc.trace_id == trace_id_of(requests[0])
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("error", "code", "permanent", "details"),
    [
        pytest.param(
            {
                "message": "restart",
                "type": "server_error",
                "code": "server_restarting",
                "should_retry": True,
                "retry_after": 5,
            },
            "server_restarting",
            False,
            {"retry_after": 5},
            id="retryable",
        ),
        pytest.param(
            {"message": "stop", "type": "server_error", "code": "timeout", "should_retry": False},
            "timeout",
            True,
            None,
            id="not-retryable",
        ),
    ],
)
def test_error_event_through_the_client_maps_should_retry_and_retry_after(
    error: dict[str, Any], code: str, permanent: bool, details: object
) -> None:
    requests: list[httpx.Request] = []
    body = KEEP_ALIVE + error_line(**error)
    with recording_client(lambda _request: sse(body), requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call())
    exc = info.value
    assert exc.code == code
    assert exc.permanent is permanent
    assert exc.details == details
    assert exc.trace_id == trace_id_of(requests[0])


def test_error_event_with_no_flag_is_not_retried() -> None:
    requests: list[httpx.Request] = []
    body = error_line(message="failed", type="server_error", code="timeout")
    with recording_client(lambda _request: sse(body), requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(max_retries=2))
    assert info.value.permanent is True
    assert len(requests) == 1


def test_a_byte_that_is_not_utf8_becomes_the_replacement_character() -> None:
    clean = wire(engine_stream({"role": "assistant", "content": "A"}, "stop"))
    body = clean.replace(b'"A"', b'"\xff"', 1)
    assert body != clean
    requests: list[httpx.Request] = []
    with recording_client(lambda _request: sse(body), requests) as client:
        reply = run(client, call())
    assert reply.text == "\ufffd"


def _silent_before(request: httpx.Request, _closed: list[bool]) -> httpx.Response:
    raise httpx.ReadTimeout("silent", request=request)


def _broken_before(request: httpx.Request, _closed: list[bool]) -> httpx.Response:
    raise httpx.ReadError("reset", request=request)


def _silent_in_stream(_request: httpx.Request, closed: list[bool]) -> httpx.Response:
    return streamed([KEEP_ALIVE, httpx.ReadTimeout("silent")], closed)


def _broken_in_stream(_request: httpx.Request, closed: list[bool]) -> httpx.Response:
    return streamed([KEEP_ALIVE, httpx.RemoteProtocolError("peer closed")], closed)


@pytest.mark.parametrize(
    ("respond", "closed_expected"),
    [
        pytest.param(_silent_before, [], id="silent-before-answer"),
        pytest.param(_broken_before, [], id="broken-before-answer"),
        pytest.param(_silent_in_stream, [True], id="silent-in-stream"),
        pytest.param(_broken_in_stream, [True], id="broken-in-stream"),
    ],
)
def test_broken_or_silent_connection_is_outcome_unknown_and_is_not_retried(
    respond: Callable[[httpx.Request, list[bool]], httpx.Response],
    closed_expected: list[bool],
) -> None:
    requests: list[httpx.Request] = []
    closed: list[bool] = []
    with recording_client(lambda request: respond(request, closed), requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(max_retries=2))
    exc = info.value
    assert exc.code == "inference_outcome_unknown"
    assert exc.permanent is True
    assert len(requests) == 1
    assert closed == closed_expected


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        pytest.param(b"data: {not json\n\n", "not_json", id="not-json"),
        pytest.param(
            wire(engine_stream({"role": "assistant", "content": "Hi"}, "stop"), done=False),
            "truncated",
            id="truncated",
        ),
        pytest.param(b"<html></html>", "truncated", id="html"),
    ],
)
def test_malformed_stream_is_invalid_response(body: bytes, reason: str) -> None:
    requests: list[httpx.Request] = []
    with recording_client(lambda _request: sse(body), requests) as client:
        with pytest.raises(ExecutionError) as info:
            run(client, call(max_retries=2))
    exc = info.value
    assert exc.code == "invalid_response"
    assert exc.details == {"reason": reason}
    assert exc.permanent is True
    assert len(requests) == 1

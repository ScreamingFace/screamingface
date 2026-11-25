"""The async half of MI-11 to MI-15 and MI-31: one chat call through sf.AsyncClient and the async
seam, with and without stream=True (contracts C1.4, C2.1, C2.3 to C2.5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from _chat_engine import (
    CHAT_PATH,
    answers,
    envelope,
    reply_body,
    sent_body,
    sse,
    trace_id_of,
)
from _chat_frames import KEEP_ALIVE, engine_stream, error_line
from _chat_stream import astreamed, async_recording_client, chunks_of, fake_async_time

import screamingface as sf
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._inference.request import INCLUDE_USAGE, ChatCall, chat_body
from screamingface._inference.transport import open_chat_stream_async, send_chat_async
from screamingface.chat_completion import AsyncChatStream, ChatCompletion
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


async def run(client: sf.AsyncClient, chat: ChatCall) -> ChatCompletion:
    return await send_chat_async(client._engine_post_stream, client.engine_url, chat)


async def open_stream(client: sf.AsyncClient, chat: ChatCall) -> AsyncChatStream:
    return await open_chat_stream_async(client._engine_post_stream, client.engine_url, chat)


@pytest.mark.asyncio
async def test_async_send_gives_the_reply_of_one_marked_post() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(sse(reply_body())), requests) as client:
        reply = await run(client, call())
    assert reply.text == "Hello"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == CHAT_PATH
    assert sent_body(request) == BODY
    assert request.headers["accept"] == "text/event-stream"
    assert request.extensions[_REPLAY_SAFE] is True
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 60.0,
        "write": 30.0,
        "pool": 30.0,
    }


@pytest.mark.asyncio
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
        pytest.param(lambda: envelope(400, "recipe_invalid"), PlanningError, True, id="400"),
        pytest.param(
            lambda: envelope(
                429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "3"}
            ),
            ExecutionError,
            False,
            id="429",
        ),
        pytest.param(lambda: envelope(503, "engine_busy"), ExecutionError, True, id="503"),
    ],
)
async def test_async_error_map_before_the_stream(
    make: Callable[[], httpx.Response], cls: type[ScreamingFaceError], permanent: bool
) -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(make()), requests) as client:
        with pytest.raises(ScreamingFaceError) as info:
            await run(client, call())
    exc = info.value
    assert type(exc) is cls
    assert exc.permanent is permanent
    assert exc.trace_id == trace_id_of(requests[0])
    assert len(requests) == 1
    if cls is ExecutionError and permanent is False:
        assert exc.details == {"retry_after": 3}


@pytest.mark.asyncio
async def test_async_never_sent_is_engine_unavailable() -> None:
    requests: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with async_recording_client(refuse, requests) as client:
        with pytest.raises(EngineUnavailableError) as info:
            await run(client, call(max_retries=2))
    assert info.value.permanent is False
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_error_event_maps_should_retry_and_retry_after() -> None:
    requests: list[httpx.Request] = []
    body = KEEP_ALIVE + error_line(**RESTART, retry_after=5)
    async with async_recording_client(answers(sse(body)), requests) as client:
        with pytest.raises(ExecutionError) as info:
            await run(client, call())
    assert info.value.code == "server_restarting"
    assert info.value.permanent is False
    assert info.value.details == {"retry_after": 5}


@pytest.mark.asyncio
async def test_async_max_retries_obeys_the_engine_flag_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_async_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(
        envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "2"}),
        sse(KEEP_ALIVE + error_line(**RESTART, retry_after=5)),
        sse(reply_body()),
    )
    async with async_recording_client(handler, requests) as client:
        reply = await run(client, call(max_retries=2))
    assert reply.text == "Hello"
    assert len(requests) == 3
    assert fake.sleeps == [2.0, 5.0]
    assert len({request.headers["traceparent"] for request in requests}) == 3


@pytest.mark.asyncio
async def test_async_caller_timeout_closes_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_async_time(monkeypatch)
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    parts: list[Any] = [KEEP_ALIVE, lambda: fake.advance(10.0), reply_body()]
    async with async_recording_client(answers(astreamed(parts, closed)), requests) as client:
        with pytest.raises(ExecutionError) as info:
            await run(client, call(timeout=5.0))
    assert info.value.code == "client_timeout"
    assert info.value.permanent is True
    assert closed == [True]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_broken_stream_is_outcome_unknown_and_is_not_retried() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    parts: list[Any] = [KEEP_ALIVE, httpx.RemoteProtocolError("peer closed")]
    async with async_recording_client(answers(astreamed(parts, closed)), requests) as client:
        with pytest.raises(ExecutionError) as info:
            await run(client, call(max_retries=2))
    assert info.value.code == "inference_outcome_unknown"
    assert info.value.permanent is True
    assert len(requests) == 1
    assert closed == [True]


@pytest.mark.asyncio
async def test_async_malformed_stream_is_invalid_response() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(sse(b"data: {not json\n\n")), requests) as client:
        with pytest.raises(ExecutionError) as info:
            await run(client, call(max_retries=2))
    assert info.value.code == "invalid_response"
    assert info.value.details == {"reason": "not_json"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_calls_run_at_the_same_time() -> None:
    requests: list[httpx.Request] = []
    started = asyncio.Event()
    waiting = 0

    async def engine(_request: httpx.Request) -> httpx.Response:
        nonlocal waiting
        waiting += 1
        if waiting == 3:
            started.set()
        await asyncio.wait_for(started.wait(), timeout=5)
        return sse(reply_body())

    async with async_recording_client(engine, requests) as client:
        replies = await asyncio.gather(*(run(client, call()) for _ in range(3)))
    assert [reply.text for reply in replies] == ["Hello"] * 3
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_async_stream_gives_each_chunk_of_the_wire_and_closes_at_the_end() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    async with async_recording_client(
        answers(astreamed([reply_body()], closed)), requests
    ) as client:
        stream = await open_stream(client, call())
        assert isinstance(stream, AsyncChatStream)
        assert closed == []
        chunks = [chunk async for chunk in stream]
        assert chunks == chunks_of(PAYLOADS)
        assert closed == [True]
    assert sent_body(requests[0]) == BODY


@pytest.mark.asyncio
async def test_async_stream_aclose_and_async_with_close_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    handler = answers(astreamed([reply_body()], closed), astreamed([reply_body()], closed))
    async with async_recording_client(handler, requests) as client:
        stream = await open_stream(client, call())
        assert (await anext(stream)).text == "Hello"
        await stream.aclose()
        assert closed == [True]
        async with await open_stream(client, call()) as second:
            assert (await anext(second)).text == "Hello"
            assert closed == [True]
        assert closed == [True, True]


@pytest.mark.asyncio
async def test_async_stream_error_event_comes_from_the_iteration() -> None:
    requests: list[httpx.Request] = []
    body = KEEP_ALIVE + error_line(
        message="stop", type="server_error", code="timeout", should_retry=False
    )
    async with async_recording_client(answers(sse(body)), requests) as client:
        stream = await open_stream(client, call())
        with pytest.raises(ExecutionError) as info:
            await anext(stream)
    assert info.value.code == "timeout"
    assert info.value.trace_id == trace_id_of(requests[0])
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_stream_retry_happens_before_the_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_async_time(monkeypatch)
    requests: list[httpx.Request] = []
    handler = answers(sse(error_line(**RESTART, retry_after=2)), sse(reply_body()))
    async with async_recording_client(handler, requests) as client:
        stream = await open_stream(client, call(max_retries=1))
        assert len(requests) == 2
        assert fake.sleeps == [2.0]
        assert [chunk.text async for chunk in stream] == [
            "Hello",
            "",
            "",
        ]  # WHY: reply_body() has the usage chunk; the stream gives it as it is


@pytest.mark.asyncio
async def test_async_time_of_the_caller_between_chunks_is_not_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review F1 of U5, async twin."""

    fake = fake_async_time(monkeypatch)
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(sse(reply_body())), requests) as client:
        stream = await open_stream(client, call(timeout=5.0))
        first = await anext(stream)
        fake.advance(60.0)
        rest = [chunk async for chunk in stream]

    assert [first, *rest] == chunks_of(PAYLOADS)

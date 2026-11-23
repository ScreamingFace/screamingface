"""MI-22 and the async half of MI-31 through aclient.chat (an AsyncClient)
(contracts C1.2, ans:Q7)."""

from __future__ import annotations

import asyncio
import gc
import inspect
import warnings
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest
from _chat_engine import (
    CATALOG,
    CHAT_PATH,
    answers,
    catalogue_engine,
    envelope,
    ok,
    recording_client,
    reply_body,
    sent_body,
    sse,
    vote,
)
from _chat_frames import KEEP_ALIVE, engine_stream, error_line
from _chat_stream import (
    astreamed,
    async_recording_client,
    chunks_of,
    engine_for,
    engine_payloads,
    fake_async_time,
)

from screamingface._inference.request import model_source, model_text
from screamingface.chat_completion import AsyncChatStream, ChatCompletion
from screamingface.client import AsyncClient
from screamingface.errors import ExecutionError, PlanningError

PAYLOADS = engine_stream({"role": "assistant", "content": "Hello"}, "stop")


stream_engine = engine_for(PAYLOADS)


@pytest.mark.asyncio
async def test_async_client_gives_the_same_reply() -> None:
    sync_requests: list[httpx.Request] = []
    with recording_client(ok, sync_requests) as client:
        expected = client.chat.completions.create("Hello", model="openrouter/a")

    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        reply = await aclient.chat.completions.create("Hello", model="openrouter/a")

    assert reply == expected
    assert sent_body(requests[0]) == sent_body(sync_requests[0])


@pytest.mark.asyncio
async def test_complete_returns_a_coroutine_that_sends_at_the_await() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        coro = aclient.chat.completions.create("Hello", model="openrouter/a")
        assert inspect.iscoroutine(coro)
        assert requests == []
        reply = await asyncio.create_task(coro)

    assert reply.text == "Hello"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("include_usage", [True, False])
async def test_async_stream(include_usage: bool) -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(stream_engine, requests) as aclient:
        stream = await aclient.chat.completions.create(
            "Hello",
            stream=True,
            stream_options={"include_usage": include_usage},
            model="openrouter/a",
        )
        assert isinstance(stream, AsyncChatStream)
        chunks = [chunk async for chunk in stream]

    assert chunks == chunks_of(engine_payloads(PAYLOADS, include_usage=include_usage))
    assert sent_body(requests[0])["stream_options"] == {"include_usage": include_usage}


@pytest.mark.asyncio
async def test_async_stream_aclose_closes_the_connection() -> None:
    closed: list[bool] = []
    requests: list[httpx.Request] = []
    async with async_recording_client(
        answers(astreamed([reply_body()], closed)), requests
    ) as aclient:
        stream = await aclient.chat.completions.create("Hello", stream=True, model="openrouter/a")
        await anext(stream)
        assert closed == []
        await stream.aclose()

    assert closed == [True]


@pytest.mark.asyncio
async def test_async_errors_raise_at_the_await() -> None:
    refusal = envelope(429, "overloaded", headers={"x-should-retry": "true", "Retry-After": "3"})
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(refusal), requests) as aclient:
        coro = aclient.chat.completions.create("Hello", model="openrouter/a")
        with pytest.raises(ExecutionError) as error:
            await coro

    assert error.value.details == {"retry_after": 3}


@pytest.mark.asyncio
async def test_async_error_event_raises_from_the_iteration() -> None:
    error_body = KEEP_ALIVE + error_line(
        message="stop", type="server_error", code="timeout", should_retry=False
    )
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(sse(error_body)), requests) as aclient:
        stream = await aclient.chat.completions.create("Hello", stream=True, model="openrouter/a")
        with pytest.raises(ExecutionError) as error:
            [chunk async for chunk in stream]

    assert error.value.code == "timeout"


@pytest.mark.asyncio
async def test_async_max_retries_works_with_stream_true(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_async_time(monkeypatch)
    restart = error_line(
        message="restart",
        type="server_error",
        code="server_restarting",
        should_retry=True,
        retry_after=5,
    )
    requests: list[httpx.Request] = []
    handler = answers(sse(restart), sse(reply_body()))
    async with async_recording_client(handler, requests) as aclient:
        stream = await aclient.chat.completions.create(
            "Hello", stream=True, max_retries=1, model="openrouter/a"
        )
        texts = [chunk.text async for chunk in stream]

    assert texts == [
        "Hello",
        "",
        "",
    ]  # WHY: reply_body() has the usage chunk; the stream gives it as it is
    assert len(requests) == 2
    assert fake.sleeps == [5.0]


@pytest.mark.asyncio
async def test_async_error_event_with_no_flag_is_permanent() -> None:
    error_body = error_line(message="failed", type="server_error", code="timeout")
    requests: list[httpx.Request] = []
    async with async_recording_client(answers(sse(error_body)), requests) as aclient:
        with pytest.raises(ExecutionError) as error:
            await aclient.chat.completions.create("Hello", max_retries=2, model="openrouter/a")

    assert error.value.permanent is True
    assert len(requests) == 1


ARGUMENT_CASES: list[tuple[Callable[[AsyncClient], object], type[Exception]]] = [
    (lambda c: c.chat.completions.create(model="openrouter/a"), TypeError),
    (
        lambda c: c.chat.completions.create(
            "hi", messages=[{"role": "user", "content": "x"}], model="openrouter/a"
        ),
        TypeError,
    ),
    (lambda c: c.chat.completions.create(messages=[], model="openrouter/a"), ValueError),
    (lambda c: c.chat.completions.create("hi", timeout=0, model="openrouter/a"), ValueError),
    (lambda c: c.chat.completions.create("hi", max_retries=-1, model="openrouter/a"), ValueError),
    (
        lambda c: c.chat.completions.create("hi", stream=cast(Any, "yes"), model="openrouter/a"),
        TypeError,
    ),
    (lambda c: c.chat.completions.create("hi", tool=[], model="openrouter/a"), TypeError),
    (lambda c: c.chat.completions.create("hi", n=2, model="openrouter/a"), PlanningError),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("call", "error"), ARGUMENT_CASES)
async def test_async_argument_errors_are_raised_before_a_coroutine_exists(
    call: Callable[[AsyncClient], object], error: type[Exception]
) -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(ok, requests) as aclient:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(error):
                _ = call(aclient)
            gc.collect()
        assert not [w for w in caught if "never awaited" in str(w.message)]

    assert requests == []


@pytest.mark.asyncio
async def test_async_closed_client_raises_at_the_call() -> None:
    requests: list[httpx.Request] = []
    aclient = async_recording_client(ok, requests)
    await aclient.aclose()
    with pytest.raises(RuntimeError, match="AsyncClient is closed"):
        _ = aclient.chat.completions.create("Hello", model="openrouter/a")

    assert requests == []


@pytest.mark.asyncio
async def test_async_reducer_recipe_loads_the_catalogue_with_await() -> None:
    requests: list[httpx.Request] = []
    async with async_recording_client(catalogue_engine, requests) as aclient:
        reply = await aclient.chat.completions.create("Hello", model=vote())

    assert isinstance(reply, ChatCompletion)
    assert [r.url.path for r in requests] == ["/v1/operators", CHAT_PATH]
    assert sent_body(requests[1])["model"] == model_text(model_source(vote()), lambda: CATALOG)

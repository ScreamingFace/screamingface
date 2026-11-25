"""The review-2 rules of the chat calls: a cancel releases the connection, and the timeout is the
limit of the full call (RR-S17, RR-S18; tests MI-51 to MI-55)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from _chat_engine import FakeTime, fake_time, ok, recording_client
from _chat_stream import async_recording_client

from screamingface.chat_completion import (
    AsyncChatStream,
    ChatChunkChoice,
    ChatCompletionChunk,
    ChatDelta,
    ChatStream,
)
from screamingface.errors import ExecutionError


def _chunk() -> ChatCompletionChunk:
    delta = ChatDelta(role=None, content="Hi", tool_calls=None, refusal=None)
    return ChatCompletionChunk(
        id="c",
        object="chat.completion.chunk",
        created=1,
        model="m",
        choices=(ChatChunkChoice(index=0, delta=delta, finish_reason=None),),
        usage=None,
        screamingface=None,
    )


async def _no_chunks() -> AsyncIterator[ChatCompletionChunk]:
    return
    yield


def _interrupted() -> Iterator[ChatCompletionChunk]:
    raise KeyboardInterrupt
    yield


def _resolve_in(monkeypatch: pytest.MonkeyPatch, fake: FakeTime, seconds: float) -> None:
    """Patch the sync model resolution so that it takes `seconds` of the fake clock."""

    def resolve(source: object, load: object) -> str:
        fake.advance(seconds)
        return "openrouter/a"

    monkeypatch.setattr("screamingface._inference.calls.model_text", resolve)


@pytest.mark.asyncio
async def test_cancel_while_waiting_for_a_chunk_releases_the_connection() -> None:
    blocker = asyncio.Event()
    closes: list[int] = []

    async def chunks() -> AsyncIterator[ChatCompletionChunk]:
        await blocker.wait()
        yield _chunk()

    async def aclose() -> None:
        closes.append(1)

    stream = AsyncChatStream(chunks(), aclose)
    task = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert closes == [1]


@pytest.mark.asyncio
async def test_a_cancelled_aclose_runs_again() -> None:
    calls: list[int] = []
    gate = asyncio.Event()

    async def release() -> None:
        calls.append(1)
        if len(calls) == 1:
            await gate.wait()

    stream = AsyncChatStream(_no_chunks(), release)
    task = asyncio.ensure_future(stream.aclose())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await stream.aclose()
    assert calls == [1, 1]
    await stream.aclose()
    assert calls == [1, 1]


def test_sync_stream_releases_on_a_base_exception() -> None:
    closes: list[int] = []
    stream = ChatStream(_interrupted(), lambda: closes.append(1))

    with pytest.raises(KeyboardInterrupt):
        next(stream)

    assert closes == [1]


def test_a_failed_sync_release_runs_again_at_the_next_close() -> None:
    attempts: list[int] = []

    def release() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise KeyboardInterrupt

    stream = ChatStream(_interrupted(), release)
    with pytest.raises(KeyboardInterrupt):
        stream.close()
    stream.close()
    stream.close()

    assert attempts == [1, 1]


def test_timeout_counts_the_model_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    _resolve_in(monkeypatch, fake, 60.0)
    requests: list[httpx.Request] = []

    with recording_client(ok, requests) as client:
        with pytest.raises(ExecutionError) as err:
            client.chat.completions.create("Hello", model="openrouter/a", timeout=50.0)

    assert err.value.code == "client_timeout"
    assert requests == []


def test_the_request_gets_the_time_that_is_left(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    _resolve_in(monkeypatch, fake, 20.0)
    requests: list[httpx.Request] = []

    with recording_client(ok, requests) as client:
        reply = client.chat.completions.create("Hello", model="openrouter/a", timeout=50.0)

    assert reply.text == "Hello"
    assert len(requests) == 1
    assert requests[0].extensions["timeout"]["read"] == 30.0


def test_no_timeout_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_time(monkeypatch)
    _resolve_in(monkeypatch, fake, 1000.0)
    requests: list[httpx.Request] = []

    with recording_client(ok, requests) as client:
        reply = client.chat.completions.create("Hello", model="openrouter/a", timeout=None)

    assert reply.text == "Hello"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_async_resolution_stops_at_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(source: object, load: object) -> str:
        await asyncio.sleep(10)
        return "openrouter/a"

    monkeypatch.setattr("screamingface._inference.calls.model_text_async", resolve)
    requests: list[httpx.Request] = []

    async with async_recording_client(ok, requests) as aclient:
        started = time.monotonic()
        with pytest.raises(ExecutionError) as err:
            await aclient.chat.completions.create("hi", model="openrouter/a", timeout=0.05)
        elapsed = time.monotonic() - started

    assert err.value.code == "client_timeout"
    assert requests == []
    assert elapsed < 2.0

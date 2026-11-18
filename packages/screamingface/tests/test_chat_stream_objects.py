"""ChatStream and AsyncChatStream (contracts C1.4), unit U5, with no transport."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest

from screamingface._inference.error_map import outcome_unknown
from screamingface.chat_completion import (
    AsyncChatStream,
    ChatChunkChoice,
    ChatCompletionChunk,
    ChatDelta,
    ChatStream,
)
from screamingface.errors import ExecutionError


def _chunk(text: str) -> ChatCompletionChunk:
    delta = ChatDelta(role=None, content=text, tool_calls=None, refusal=None)
    return ChatCompletionChunk(
        id="c",
        object="chat.completion.chunk",
        created=1,
        model="m",
        choices=(ChatChunkChoice(index=0, delta=delta, finish_reason=None),),
        usage=None,
        screamingface=None,
    )


A, B = _chunk("a"), _chunk("b")


def _broken() -> Iterator[ChatCompletionChunk]:
    yield A
    raise outcome_unknown("t1")


async def _agen(items: list[ChatCompletionChunk]) -> AsyncIterator[ChatCompletionChunk]:
    for item in items:
        yield item


async def _abroken() -> AsyncIterator[ChatCompletionChunk]:
    yield A
    raise outcome_unknown("t1")


def test_chat_stream_gives_each_chunk_in_order_and_closes_at_the_end() -> None:
    closes: list[int] = []
    s = ChatStream(iter([A, B]), lambda: closes.append(1))

    assert list(s) == [A, B]
    assert closes == [1]
    assert list(s) == []
    assert closes == [1]


def test_chat_stream_iter_gives_the_stream_itself() -> None:
    s = ChatStream(iter([A]), lambda: None)

    assert iter(s) is s


def test_close_stops_the_iteration_and_a_second_close_does_nothing() -> None:
    closes: list[int] = []
    s = ChatStream(iter([A, B]), lambda: closes.append(1))

    assert next(s) == A
    s.close()
    s.close()

    assert closes == [1]
    with pytest.raises(StopIteration):
        next(s)


def test_an_error_of_the_iteration_closes_the_stream() -> None:
    closes: list[int] = []
    s = ChatStream(_broken(), lambda: closes.append(1))

    assert next(s) == A
    with pytest.raises(ExecutionError) as info:
        next(s)

    assert info.value.code == "inference_outcome_unknown"
    assert closes == [1]
    with pytest.raises(StopIteration):
        next(s)


def test_the_with_block_closes_the_stream() -> None:
    closes: list[int] = []
    entered = ChatStream(iter([A, B]), lambda: closes.append(1))

    with entered as s:
        assert s is entered
        assert next(s) == A
        assert closes == []

    assert closes == [1]


@pytest.mark.asyncio
async def test_async_stream_gives_each_chunk_in_order_and_closes_at_the_end() -> None:
    closes: list[int] = []

    async def aclose() -> None:
        closes.append(1)

    s = AsyncChatStream(_agen([A, B]), aclose)

    assert [c async for c in s] == [A, B]
    assert closes == [1]
    assert [c async for c in s] == []
    assert closes == [1]


@pytest.mark.asyncio
async def test_async_aiter_gives_the_stream_itself() -> None:
    async def aclose() -> None:
        return None

    s = AsyncChatStream(_agen([A]), aclose)

    assert s.__aiter__() is s


@pytest.mark.asyncio
async def test_async_aclose_stops_the_iteration_and_a_second_aclose_does_nothing() -> None:
    closes: list[int] = []

    async def aclose() -> None:
        closes.append(1)

    s = AsyncChatStream(_agen([A, B]), aclose)

    assert await anext(s) == A
    await s.aclose()
    await s.aclose()

    assert closes == [1]
    with pytest.raises(StopAsyncIteration):
        await anext(s)


@pytest.mark.asyncio
async def test_an_error_of_the_async_iteration_closes_the_stream() -> None:
    closes: list[int] = []

    async def aclose() -> None:
        closes.append(1)

    s = AsyncChatStream(_abroken(), aclose)

    assert await anext(s) == A
    with pytest.raises(ExecutionError) as info:
        await anext(s)

    assert info.value.code == "inference_outcome_unknown"
    assert closes == [1]
    with pytest.raises(StopAsyncIteration):
        await anext(s)


@pytest.mark.asyncio
async def test_the_async_with_block_closes_the_stream() -> None:
    closes: list[int] = []

    async def aclose() -> None:
        closes.append(1)

    async with AsyncChatStream(_agen([A, B]), aclose) as s:
        assert await anext(s) == A
        assert closes == []

    assert closes == [1]

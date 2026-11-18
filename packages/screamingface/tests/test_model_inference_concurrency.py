"""MI-24: calls at one time on one ModelInference object (MI-S20), with threads and with tasks."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from _chat_engine import (
    CHAT_PATH,
    catalogue_engine,
    recording_client,
    reply_body,
    sent_body,
    sse,
    vote,
)
from _chat_stream import async_recording_client

from screamingface.inference import ModelInference


def echo(request: httpx.Request) -> httpx.Response:
    return sse(reply_body(sent_body(request)["messages"][0]["content"]))


def test_two_calls_at_one_time_on_one_object_with_threads() -> None:
    barrier = threading.Barrier(2, timeout=5)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/operators":
            return catalogue_engine(request)
        # WHY: the barrier opens only when both calls are inside the Engine at one time.
        barrier.wait()
        return echo(request)

    requests: list[httpx.Request] = []
    with recording_client(handler, requests) as client:
        llm = ModelInference(vote(), client=client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(llm.chat.complete, prompt) for prompt in ("one", "two")]
            texts = [future.result(timeout=10).text for future in futures]

    assert texts == ["one", "two"]
    assert len([r for r in requests if r.url.path == CHAT_PATH]) == 2


@pytest.mark.asyncio
async def test_n_tasks_at_one_time_on_one_object() -> None:
    count = 5
    arrived = [0]
    ready = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/operators":
            return catalogue_engine(request)
        arrived[0] += 1
        if arrived[0] == count:
            ready.set()
        # WHY: each call waits until all the calls are inside the Engine at one time.
        await asyncio.wait_for(ready.wait(), timeout=5)
        return echo(request)

    requests: list[httpx.Request] = []
    async with async_recording_client(handler, requests) as aclient:
        llm = ModelInference(vote(), client=aclient)
        tasks = [asyncio.create_task(llm.chat.complete(f"q{i}")) for i in range(count)]
        replies = await asyncio.gather(*tasks)

    assert [reply.text for reply in replies] == [f"q{i}" for i in range(count)]


def test_the_object_keeps_no_state_of_a_call() -> None:
    requests: list[httpx.Request] = []
    with recording_client(echo, requests) as client:
        llm = ModelInference("openrouter/a", client=client)
        before = (llm._source, llm._client)
        llm.chat.complete("one")
        llm.chat.complete("two")
        assert (llm._source, llm._client) == before

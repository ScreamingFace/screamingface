"""Helpers of the stream and async chat tests: async twins of tests/_chat_engine.py and an Engine
that answers with or without the usage chunk (unit U5).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
from _chat_engine import ENGINE_URL, FakeTime, Part, fake_time, sse
from _chat_frames import wire

import screamingface as sf
from screamingface._inference import transport
from screamingface._inference.frames import chunk_from_payload
from screamingface.chat_completion import ChatCompletionChunk

type AsyncHandler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def async_recording_client(handler: AsyncHandler, requests: list[httpx.Request]) -> sf.AsyncClient:
    """An AsyncClient whose Engine is `handler`; every request it receives lands in `requests`."""

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        answer = handler(request)
        if inspect.isawaitable(answer):
            return await answer
        return answer

    return sf.AsyncClient(
        engine_url=ENGINE_URL,
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(respond),
        save_results=False,
    )


class AsyncRecordingStream(httpx.AsyncByteStream):
    """The async twin of RecordingStream: it gives its parts in order and appends True to
    `closed` when it is closed."""

    def __init__(self, parts: list[Part], closed: list[bool]) -> None:
        self._parts = parts
        self._closed = closed

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self._parts:
            if isinstance(part, bytes):
                yield part
            elif isinstance(part, BaseException):
                raise part
            else:
                part()

    async def aclose(self) -> None:
        self._closed.append(True)


def astreamed(parts: list[Part], closed: list[bool]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=AsyncRecordingStream(parts, closed),
    )


def fake_async_time(monkeypatch: pytest.MonkeyPatch) -> FakeTime:
    """fake_time, and an async sleep that moves the same fake clock."""

    fake = fake_time(monkeypatch)

    async def sleep(seconds: float) -> None:
        fake.sleep(seconds)

    monkeypatch.setattr(transport, "_async_sleep", sleep)
    return fake


def engine_payloads(payloads: list[dict[str, Any]], *, include_usage: bool) -> list[dict[str, Any]]:
    """The payloads that the Engine sends for a request with or without include_usage.

    `payloads` is the include_usage form of engine_stream. With no include_usage, the Engine
    sends no usage chunk and puts its screamingface object on the finish chunk.
    AIDEV-NOTE: a hand copy of E/chat/sse.py frames(), as tests/_chat_frames.py is.
    """

    if include_usage:
        return payloads
    *head, finish, usage = payloads
    return [*head, {**finish, "screamingface": usage["screamingface"]}]


def chunks_of(payloads: list[dict[str, Any]]) -> list[ChatCompletionChunk]:
    """The chunks that a stream caller gets for these payloads: each one, as it is (C2.1, P6)."""

    return [chunk_from_payload(payload) for payload in payloads]


def asks_for_usage(request: httpx.Request) -> bool:
    """True when the body of the request asks for the usage chunk."""

    options = json.loads(request.content).get("stream_options") or {}
    return options.get("include_usage") is True


def engine_for(payloads: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    """An Engine that answers each request with engine_payloads for its include_usage value."""

    def respond(request: httpx.Request) -> httpx.Response:
        sent = engine_payloads(payloads, include_usage=asks_for_usage(request))
        return sse(wire(sent))

    return respond

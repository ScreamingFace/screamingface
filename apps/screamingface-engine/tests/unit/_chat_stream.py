"""Test support for the streamed chat route (U5): the stream body, the reader of the SSE payloads,
a raw ASGI stream that the test can watch while it runs, and a bounded poll.

Test-only, the `_chat_app` pattern. `start_stream` runs one raw ASGI request whose receive gives
the body once and then waits for `gone`; the list it returns fills while the stream runs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from _chat_app import ChatApp, asgi_scope, body, body_then

__all__ = [
    "body_items",
    "data_payloads",
    "encoded",
    "keep_alives",
    "media_type",
    "response_start",
    "scheduled_topic",
    "sent_payloads",
    "start_stream",
    "stream_body",
    "wait_until",
]

_KEEP_ALIVE = b": keep-alive"
_DATA = b"data: "


def stream_body(**extra: Any) -> dict[str, Any]:
    """A chat completion request body with `stream` true."""
    return body(stream=True, **extra)


def encoded(payload: dict[str, Any]) -> bytes:
    """The JSON bytes of a request body."""
    return json.dumps(payload).encode()


def data_payloads(raw: bytes) -> list[dict[str, Any] | str]:
    """The events of an SSE body: "keep-alive", "[DONE]", or the JSON object of a data line."""
    payloads: list[dict[str, Any] | str] = []
    for block in raw.split(b"\n\n"):
        if not block:
            continue
        if block == _KEEP_ALIVE:
            payloads.append("keep-alive")
            continue
        if not block.startswith(_DATA):
            raise AssertionError(f"not an SSE data line: {block[:40]!r}")
        data = block[len(_DATA) :]
        payloads.append("[DONE]" if data == b"[DONE]" else json.loads(data))
    return payloads


def start_stream(
    ca: ChatApp, raw_body: bytes, gone: asyncio.Event
) -> tuple[asyncio.Future[Any], list[dict[str, Any]]]:
    """Starts one raw ASGI request; the call and the list of the messages that the App sent."""
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = asgi_scope(len(raw_body))
    call = asyncio.ensure_future(ca.app(scope, body_then(raw_body, gone), send))
    return call, sent


def body_items(sent: list[dict[str, Any]]) -> list[bytes]:
    """The non-empty bodies of the http.response.body messages, one item for each message."""
    return [m["body"] for m in sent if m["type"] == "http.response.body" and m.get("body")]


def sent_payloads(sent: list[dict[str, Any]]) -> list[dict[str, Any] | str]:
    """The SSE events that the App sent so far."""
    return data_payloads(b"".join(body_items(sent)))


def keep_alives(sent: list[dict[str, Any]]) -> int:
    """The number of keep-alive comments sent so far."""
    return sum(1 for p in sent_payloads(sent) if p == "keep-alive")


def response_start(sent: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The http.response.start message, when the App sent it."""
    return next((m for m in sent if m["type"] == "http.response.start"), None)


def media_type(content_type: str) -> str:
    """The media type of a Content-Type value, without its parameters."""
    return content_type.split(";")[0].strip()


async def wait_until(
    predicate: Callable[[], bool], bound_s: float = 5.0, *, what: str = "the condition"
) -> None:
    """Polls `predicate` each 0.005 s; fails the test when it is not true within `bound_s`."""
    for _ in range(int(bound_s / 0.005)):
        if predicate():
            return
        await asyncio.sleep(0.005)
    if not predicate():
        raise AssertionError(f"{what} was not reached within {bound_s} s")


async def scheduled_topic(ca: ChatApp, index: int = 0) -> str:
    """The topic of the run with this index, once it is scheduled."""
    await wait_until(lambda: len(ca.runner.scheduled) > index, what="the schedule")
    return ca.runner.scheduled[index]["topic"]

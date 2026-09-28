"""The ASGI primitives shared by the node and the ``url4 serve`` wrapper.

STORY: the wire error body and the lifespan handshake have one owner; the CLI
adds its shutdown hook and Retry-After header as parameters, never as copies
(F8).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from url4.peer._asgi import lifespan, send, send_error
from url4.peer.server import Url4Node

pytestmark = pytest.mark.asyncio


class _Channel:
    """A minimal ASGI send/receive pair that records what was written."""

    def __init__(self, incoming: list[dict]) -> None:
        self._incoming = iter(incoming)
        self.sent: list[Mapping] = []

    async def receive(self) -> dict:
        return next(self._incoming)

    async def send(self, message: Mapping) -> None:
        self.sent.append(message)


async def test_send_writes_start_then_body() -> None:
    channel = _Channel([])
    headers = [(b"content-type", b"text/plain; charset=utf-8")]
    await send(channel.send, 200, headers, b"hello")
    assert channel.sent == [
        {"type": "http.response.start", "status": 200, "headers": headers},
        {"type": "http.response.body", "body": b"hello"},
    ]


async def test_send_error_body_is_byte_identical() -> None:
    # The error shape is protocol, not implementation: pin the exact bytes so a
    # key-order or spacing change cannot slip through as a "refactor".
    channel = _Channel([])
    await send_error(channel.send, 504, "timeout", "evaluation exceeded 5s")
    assert channel.sent[0] == {
        "type": "http.response.start",
        "status": 504,
        "headers": [(b"content-type", b"application/json")],
    }
    body = channel.sent[1]["body"]
    assert body == b'{"error": {"code": "timeout", "message": "evaluation exceeded 5s"}}'
    assert json.loads(body) == {"error": {"code": "timeout", "message": "evaluation exceeded 5s"}}


async def test_send_error_adds_retry_after_when_asked() -> None:
    channel = _Channel([])
    await send_error(channel.send, 503, "overloaded", "server at capacity", retry_after=1)
    assert channel.sent[0]["headers"] == [
        (b"content-type", b"application/json"),
        (b"retry-after", b"1"),
    ]
    assert (
        channel.sent[1]["body"]
        == b'{"error": {"code": "overloaded", "message": "server at capacity"}}'
    )


async def test_lifespan_without_on_shutdown_completes_both_acks() -> None:
    channel = _Channel([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    await lifespan(channel.receive, channel.send)
    assert [m["type"] for m in channel.sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]


async def test_lifespan_runs_on_shutdown_before_the_ack() -> None:
    events: list[str] = []

    async def on_shutdown() -> None:
        events.append("closed")

    async def send(message: Mapping) -> None:
        events.append(message["type"])

    channel = _Channel([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    await lifespan(channel.receive, send, on_shutdown=on_shutdown)
    assert events == ["lifespan.startup.complete", "closed", "lifespan.shutdown.complete"]


async def test_node_asgi_lifespan_routes_through_the_shared_helper() -> None:
    # The bare node passes NO on_shutdown, so this pins the None branch end to end.
    channel = _Channel([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    await Url4Node("t").asgi()({"type": "lifespan"}, channel.receive, channel.send)
    assert [m["type"] for m in channel.sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]

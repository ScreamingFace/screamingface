"""An early 413 closes the connection; the per-path limit follows the route path (OME-1542).

# FEATURE: image and file input across the gateway (OME-1529) — the body cap.
# STORY: as the gateway operator, an unauthenticated caller who declares (or streams) more than the
# cap gets the 413 AND loses the socket — it cannot keep an FD pinned by trickling the remainder.
# INVARIANT: every middleware-authored 413 carries `Connection: close`, and the ASGI server closes
# the transport after it without draining the caller's remaining input.
# INVARIANT: the path-specific limit is chosen on the route path — `root_path` stripped as Starlette
# routes — so a prefixed deployment keeps the snapshot upload's larger allowance.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from starlette.types import Message, Receive, Scope, Send

from aigateway.middleware.body_cap import BodyCapMiddleware

_CAP = 10
# WHY far above the probe window: a close inside the window can then only come from the 413's
# `Connection: close`, never from uvicorn's idle keep-alive timer.
_KEEP_ALIVE_S = 30
_CLOSE_WITHIN_S = 2.0


async def _read_all_then_ok(scope: Scope, receive: Receive, send: Send) -> None:
    more = True
    while more:
        message = await receive()
        more = message.get("more_body", False)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.fixture(params=["httptools", "h11"])
def server_port(request: pytest.FixtureRequest) -> Iterator[int]:
    """A real uvicorn on an ephemeral loopback port serving the capped app."""
    config = uvicorn.Config(
        BodyCapMiddleware(_read_all_then_ok, max_bytes=_CAP),
        host="127.0.0.1",
        port=0,
        http=request.param,
        lifespan="off",
        log_level="warning",
        timeout_keep_alive=_KEEP_ALIVE_S,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.01)
    port: int = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _read_response_head(sock: socket.socket) -> bytes:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        assert chunk, f"connection closed before a response: {data!r}"
        data += chunk
    return data


def _closed_within(sock: socket.socket, seconds: float) -> bool:
    """True once the peer closes (EOF or reset); False if still open at the deadline."""
    sock.settimeout(seconds)
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            if not sock.recv(4096):
                return True
    except (ConnectionResetError, BrokenPipeError):
        return True
    except TimeoutError:
        return False
    return False


def _probe(port: int, head: bytes, first_body: bytes) -> tuple[bytes, bool]:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(head + first_body)
        response = _read_response_head(sock)
        # WHY one more byte: reviewer's probe — a trickled byte cancels uvicorn's keep-alive
        # timer, so without the close the socket would stay pinned while the parser waits.
        try:
            sock.sendall(b"x")
        except (ConnectionResetError, BrokenPipeError):
            return response, True
        return response, _closed_within(sock, _CLOSE_WITHIN_S)


def test_a_declared_overflow_closes_the_connection_after_the_413(server_port: int) -> None:
    head = b"POST / HTTP/1.1\r\nHost: t\r\nContent-Length: 100\r\n\r\n"

    response, closed = _probe(server_port, head, b"")

    assert response.startswith(b"HTTP/1.1 413"), response
    assert b"connection: close" in response.lower()
    assert closed, "the socket stayed open after the early 413"


def test_a_chunked_overflow_closes_the_connection_after_the_413(server_port: int) -> None:
    head = b"POST / HTTP/1.1\r\nHost: t\r\nTransfer-Encoding: chunked\r\n\r\n"
    # one 20-byte chunk crosses the 10-byte cap; the terminating chunk is never sent
    chunk = b"14\r\n" + b"y" * 20 + b"\r\n"

    response, closed = _probe(server_port, head, chunk)

    assert response.startswith(b"HTTP/1.1 413"), response
    assert b"connection: close" in response.lower()
    assert closed, "the socket stayed open after the early 413"


def test_a_body_under_the_cap_keeps_the_connection_alive(server_port: int) -> None:
    # The close is for refusals only — an ordinary request keeps HTTP/1.1 keep-alive.
    with socket.create_connection(("127.0.0.1", server_port), timeout=5) as sock:
        sock.sendall(b"POST / HTTP/1.1\r\nHost: t\r\nContent-Length: 3\r\n\r\nabc")
        response = _read_response_head(sock)
        assert response.startswith(b"HTTP/1.1 200"), response
        assert b"connection: close" not in response.lower()
        assert not _closed_within(sock, 0.5)


# --- root_path ----------------------------------------------------------------------------------


def _run(app: Any, scope: Scope, body: bytes) -> tuple[int, list[Message]]:
    sent: list[Message] = []
    pending = [body]

    async def receive() -> Message:
        if not pending:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": pending.pop(), "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start"), sent


def _prefixed_scope(path: str, root_path: str) -> Scope:
    return {"type": "http", "method": "POST", "path": path, "root_path": root_path, "headers": []}


_SNAPSHOTS = "/v1/admin/cache/snapshots"


def _snapshot_app() -> BodyCapMiddleware:
    return BodyCapMiddleware(_read_all_then_ok, max_bytes=10, path_limits={_SNAPSHOTS: 100})


def test_a_prefixed_deployment_keeps_the_path_specific_limit() -> None:
    status, _ = _run(_snapshot_app(), _prefixed_scope(f"/prefix{_SNAPSHOTS}", "/prefix"), b"z" * 50)

    assert status == 200


def test_a_prefixed_deployment_still_caps_at_the_path_specific_limit() -> None:
    status, _ = _run(
        _snapshot_app(), _prefixed_scope(f"/prefix{_SNAPSHOTS}", "/prefix"), b"z" * 101
    )

    assert status == 413


@pytest.mark.parametrize(
    ("path", "root_path"),
    [
        # a root_path that is only a string prefix of the next segment is not a mount boundary
        (f"/prefixed{_SNAPSHOTS}", "/prefix"),
        # the bare mount point is not the snapshot route
        ("/prefix", "/prefix"),
        # a root_path the path does not start with is ignored, as Starlette ignores it
        (f"/other{_SNAPSHOTS}", "/prefix"),
    ],
)
def test_only_a_real_mount_prefix_is_stripped(path: str, root_path: str) -> None:
    status, _ = _run(_snapshot_app(), _prefixed_scope(path, root_path), b"z" * 50)

    assert status == 413


def test_an_unprefixed_scope_with_a_root_path_already_stripped_still_matches() -> None:
    # Some servers pass a path that already excludes root_path; Starlette routes it as-is.
    status, _ = _run(_snapshot_app(), _prefixed_scope(_SNAPSHOTS, "/prefix"), b"z" * 50)

    assert status == 200

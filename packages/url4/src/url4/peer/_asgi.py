"""The ASGI primitives shared by the node and the ``url4 serve`` wrapper.

Both :meth:`~url4.peer.server.Url4Node.asgi` and the ``url4 serve`` wrapper
(:func:`~url4.cli._serve.build_asgi_app`) answer lifespan messages and write the
same ``{"error": {"code", "message"}}`` body. Those write paths live here once,
so the wire error shape has a single owner and the CLI can add its shutdown hook
(``on_shutdown``) and its ``Retry-After`` header as parameters rather than copies.

# INVARIANT: only ASGI primitives and the standard library. No web framework and
# no HTTP client is imported at module scope, so the core import graph stays
# framework-free (see tests/unit/test_import_isolation.py).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence

_Send = Callable[[Mapping], Awaitable[None]]
_Receive = Callable[[], Awaitable[Mapping]]
_OnShutdown = Callable[[], Awaitable[None]]
_Headers = Sequence[tuple[bytes, bytes]]


async def lifespan(receive: _Receive, send: _Send, on_shutdown: _OnShutdown | None = None) -> None:
    """Serve the ASGI lifespan protocol, running ``on_shutdown`` before the ack.

    ``on_shutdown`` is how the ``url4 serve`` wrapper closes its node gracefully;
    the bare node passes none, because it owns nothing to release at exit.
    """
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            if on_shutdown is not None:
                await on_shutdown()
            await send({"type": "lifespan.shutdown.complete"})
            return


async def send(send: _Send, status: int, headers: _Headers, body: bytes) -> None:
    """Write one complete HTTP response with the given raw header pairs."""
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def send_error(
    send: _Send, status: int, code: str, message: str, retry_after: int | None = None
) -> None:
    """Write the canonical error body, optionally with a ``Retry-After`` header.

    The body — ``{"error": {"code", "message"}}`` — is the protocol's error
    shape and is byte-identical for every caller.
    """
    payload = json.dumps({"error": {"code": code, "message": message}})
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload.encode()})

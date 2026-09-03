"""The total body cap, enforced before anything parses the body.

Spec §2.4's 64 KiB limit is the only cap that has to hold *pre-parse*: every other row is a
property of a value that only exists once the JSON has been decoded, and decoding an unbounded
body to find out how big it is defeats the cap. So this is pure ASGI middleware rather than a
route dependency or a `BaseHTTPMiddleware` — both of those run after starlette has already been
handed the stream.

Two paths, because a client either declares its length or it does not:

- **Declared `Content-Length`.** Over the cap → refuse without reading a byte. Under it → pass
  the request through untouched; HTTP framing means the server will not read more than the
  declared length, so a low header cannot smuggle a larger body past this check.
- **No usable `Content-Length`** (chunked, or a malformed header). Buffer while counting and
  refuse the moment the running total exceeds the cap, then replay the buffer to the app. The
  buffer is bounded by the cap plus one chunk, which is the whole reason this is safe to do.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .problem import render_problem
from .problem_catalogue import body_too_large

_METHODS_WITH_A_BODY = frozenset({"POST", "PUT", "PATCH"})


def _declared_length(scope: Scope) -> int | None:
    """The request's `Content-Length` as an int, or None when it is absent or unusable.

    A header that is not an integer is treated as absent rather than as an error: rejecting it
    here would answer a framing problem with this service's report-shaped 413, and the counting
    path below reaches the same verdict on the bytes that actually arrive.
    """
    for name, value in scope.get("headers", ()):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodyLimitMiddleware:
    """Refuse a request body over ``max_bytes`` with the service's own RFC 9457 413."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _METHODS_WITH_A_BODY:
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is None:
            await self._while_counting(scope, receive, send)
        elif declared > self.max_bytes:
            await self._refuse(scope, send, size=declared)
        else:
            await self.app(scope, receive, send)

    async def _while_counting(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                # A disconnect mid-body: there is nobody left to answer, and handing a partial
                # body to the app would look to it like a complete one.
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._refuse(scope, send, size=None)
                return
            more_body = message.get("more_body", False)
        await self.app(scope, _replay(bytes(body)), send)

    async def _refuse(self, scope: Scope, send: Send, size: int | None) -> None:
        response = render_problem(body_too_large(self.max_bytes, size))
        # The unread remainder of the body is deliberately not drained: draining is how a cap
        # becomes an invitation to send an unbounded stream slowly.
        await response(scope, _nothing_more, send)


async def _nothing_more() -> Message:
    """A `receive` for a response that never reads one."""
    return {"type": "http.request", "body": b"", "more_body": False}


def _replay(body: bytes) -> Receive:
    """A `receive` that hands the buffered body over once, then reports the stream closed."""
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive

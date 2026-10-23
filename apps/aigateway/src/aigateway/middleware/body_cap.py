"""The request body cap (OME-1542).

FEATURE: image and file input across the gateway (OME-1529). Inline `data:` images and PDFs make
chat bodies megabytes long, and before this nothing — app, uvicorn or ingress — bounded what a
caller could make the gateway hold in memory.

STORY: as a benchmark author whose Case trips the cap, the 413 names the limit in bytes and MiB,
so the run explains itself instead of failing with an anonymous error.

INVARIANT: enforced on the bytes actually DELIVERED. A declared `Content-Length` over the limit is
refused before reading; anything else (no length, a chunked body, a length that lies) is counted
as it arrives, and the chunk that would cross the limit is never handed to the app. The middleware
buffers nothing — its only state is a counter.

WHY pure ASGI and not `BaseHTTPMiddleware`: the same reason as `call_id` — this gateway streams
SSE, and `BaseHTTPMiddleware` runs the app in a separate task that cannot see the body stream.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_MIB = 1024 * 1024


def _limit_detail(limit: int) -> dict[str, Any]:
    return {
        "code": "request_too_large",
        "limit_bytes": limit,
        "message": (
            f"Request body exceeds the gateway limit of {limit} bytes ({limit / _MIB:g} MiB)."
        ),
    }


class RequestBodyTooLarge(HTTPException):
    """Raised out of `receive()` when the delivered body crosses the limit.

    # WHY an HTTPException: FastAPI's own handlers render it as the 413 wherever the read happens
    # (the chat route, a pydantic body parameter, a multipart form) — and the middleware answers it
    # itself if it escapes, or replaces whatever a careless layer sent instead.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(status_code=413, detail=_limit_detail(limit))


def _route_path(scope: Scope) -> str:
    """The path Starlette routes on: ``scope["path"]`` with a mounted ``root_path`` removed.

    # WHY (OME-1542 review 2): uvicorn keeps the mount prefix in ``scope["path"]`` and Starlette
    # strips ``root_path`` only when it routes, so an exact ``path`` lookup missed the snapshot
    # upload's own limit behind a prefix. Mirrors ``starlette._utils.get_route_path`` — copied, not
    # imported, because that module is private.
    # INVARIANT: only a whole-segment prefix is stripped (``/prefix`` never strips ``/prefixed``).
    """
    path: str = scope.get("path", "")
    root_path: str = scope.get("root_path", "")
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path) :]
    return path


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                # WHY ignore, not refuse: the counted bytes are the authority either way.
                return None
    return None


class BodyCapMiddleware:
    """Refuse a request whose body is larger than its path's limit with a 413."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        path_limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        # WHY per path: the admin snapshot upload has its own, larger, separately configured cap
        # (`AIGW_CACHE_UPLOAD_MAX_BYTES`). It gets that bound here — it is not exempted.
        self.path_limits = dict(path_limits or {})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.path_limits.get(_route_path(scope), self.max_bytes)
        declared = _declared_length(scope)
        if declared is not None and declared > limit:
            await self._refuse(scope, receive, send, limit)
            return

        received = 0
        overflowed = False
        started = False
        replied = False

        async def capped_receive() -> Message:
            nonlocal received, overflowed
            if overflowed:
                raise RequestBodyTooLarge(limit)
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # INVARIANT: the crossing chunk is dropped here, never returned to the app.
                    overflowed = True
                    raise RequestBodyTooLarge(limit)
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started, replied
            if overflowed and not started:
                # INVARIANT: fail closed. Whatever the app answers after the overflow — its own
                # rendering of the 413, or a 200 built on a truncated body by a layer that
                # swallowed the refusal — the caller gets exactly one canonical 413.
                if not replied:
                    replied = True
                    await self._refuse(scope, receive, send, limit)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, guarded_send)
        except RequestBodyTooLarge:
            if started:
                raise
        if overflowed and not started and not replied:
            await self._refuse(scope, receive, send, limit)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        # INVARIANT (OME-1542 review 2): every 413 this middleware authors closes the connection.
        # It can answer before the body is complete (a declared over-limit length, a crossing
        # chunk); on keep-alive the server would otherwise keep reading the caller's remainder, so
        # a trickled byte pins the socket indefinitely. `Connection: close` makes uvicorn (httptools
        # and h11) close the transport after the response — the remainder is never drained.
        response = JSONResponse(
            status_code=413,
            content={"detail": _limit_detail(limit)},
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)

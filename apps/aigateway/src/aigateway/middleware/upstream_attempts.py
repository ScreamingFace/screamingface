"""The `X-AIGW-Upstream-Attempts` response header (contract C7).

FEATURE: Router Recipe extension Unit 5.1 — the Engine records how many HTTP requests the Gateway
sent upstream for one chat or classification call. Every non-streaming answer on those two routes,
success or handled error, carries that count; the status and body are untouched. The frozen-copy
replay of each route carries it too: a replay sends nothing upstream (`routes/frozen_copies.py`), so
its answer says `0`, never the count of the call it replays.

INVARIANT: registered immediately inside `CallIdMiddleware` and outside every other user
middleware, so an auth, body-cap, validation or `HTTPException` answer passes through here and
carries the header. An unhandled error is answered by Starlette's outermost server-error layer,
outside user middleware, and carries none; the Engine records that as unknown.

INVARIANT: one counter per request, bound before the inner app runs. Send hooks mutate it, so
sends made in a task a `BaseHTTPMiddleware` starts (the auth-disabled guard) still count.

WHY pure ASGI: the same reason as `call_id` and `body_cap`. `BaseHTTPMiddleware` would run the app
in another task and could not set a value every inner task inherits.
"""

from __future__ import annotations

import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aigateway.core.upstream_attempts import HEADER, UpstreamAttempts, bound_attempts

from .body_cap import route_path

# WHY a pattern: a replay path carries the copy id, matched as Starlette's `str` path convertor
# matches it (one non-empty segment), so `/v1/frozen-copies/{id}/classifications` is counted from
# the release that first serves it.
_COUNTED_PATH = re.compile(r"/v1/(?:frozen-copies/[^/]+/)?(?:chat/completions|classifications)")
_HEADER = HEADER.encode("latin-1")
_EVENT_STREAM = b"text/event-stream"


def _is_event_stream(headers: list[tuple[bytes, bytes]]) -> bool:
    return any(
        name.lower() == b"content-type" and value.lower().startswith(_EVENT_STREAM)
        for name, value in headers
    )


class UpstreamAttemptsMiddleware:
    """Count the physical upstream sends of one call and answer with the count."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or _COUNTED_PATH.fullmatch(route_path(scope)) is None
        ):
            await self.app(scope, receive, send)
            return

        counter = UpstreamAttempts()

        async def send_with_count(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                # WHY streaming is skipped: C7 leaves streaming answers unchanged; their status
                # is committed before any upstream send, so no count could be final there.
                if not _is_event_stream(headers):
                    kept = [(name, value) for name, value in headers if name.lower() != _HEADER]
                    count = str(counter.count).encode("ascii")
                    message = {**message, "headers": [*kept, (_HEADER, count)]}
            await send(message)

        with bound_attempts(counter):
            await self.app(scope, receive, send_with_count)

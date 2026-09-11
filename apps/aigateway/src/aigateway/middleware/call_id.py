"""Bind one request's correlation ids for its whole lifetime (OME-938, OME-1120).

Two ids, one scope:

- `gateway_call_id` — ours, minted here, always present.
- `trace_id` — the CALLER's, joined from the inbound `traceparent` when it is well-formed,
  minted here when it is not. This is what makes one id greppable across the engine's
  namespace and `sf-aigw`, which is Phase 1's whole payoff.

WHY the ids are minted HERE and not in the taxonomy plugin: they used to be minted in
`plugins/taxonomy/session.py`, and that plugin is gated by `TaxonomyPluginSettings().enabled`
(`AIGW_TAXONOMY_ENABLED`). So turning off a *usage-accounting* feature silently deleted the
*only correlation mechanism* in the gateway. Correlation is not a feature of accounting;
accounting is one consumer of correlation.

WHY pure ASGI and not `BaseHTTPMiddleware`: `BaseHTTPMiddleware` runs the downstream app in a
SEPARATE task and returns as soon as the response *starts*. This gateway streams SSE, so the
response body is produced after that point — under `BaseHTTPMiddleware` the scope would unbind
while the stream was still being generated, and every line emitted during the stream (which is
where dispatch, retry and provider errors happen) would lose its ids.

SECURITY: `traceparent` is caller-controlled. Adopting a malformed or attacker-chosen value
would let a caller pick the key other requests are grouped under, so anything that does not
parse is REPLACED, never cleaned up. See `aigateway.w3c_trace`.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aigateway.call_context import call_scope, new_gateway_call_id
from aigateway.tracing import server_span
from aigateway.w3c_trace import adopt_or_mint_trace_id, parse_traceparent

TRACE_RESPONSE_HEADER = b"x-aigw-trace-id"
"""Echoed on every response so a STREAMING caller can read the id.

An SSE consumer never sees a response body object, so `_aigw.trace_id` in the JSON is not
reachable for the very calls this gateway mostly serves. A header is the only channel both a
JSON and a streaming caller can read.
"""


def _inbound_traceparent(scope: Scope) -> str | None:
    """The raw `traceparent` header, read off the ASGI scope.

    WHY the scope and not a Starlette `Request`: this runs before any framework object exists,
    which is the point — the ids must be bound before the first line any layer can log.
    """
    for name, value in scope.get("headers", ()):
        if name == b"traceparent":
            return value.decode("latin-1")
    return None


def _route_name(scope: Scope) -> str:
    """The span's name: `<METHOD> <path>`.

    The RAW path, deliberately not a templated route — this runs before routing has happened,
    which is the same reason the ids are bound here. Path parameters in aigateway's surface are
    ids, not secrets, so the cardinality cost is bounded and the alternative (naming every span
    after the method alone) makes the trace view useless.
    """
    method = scope.get("method", "HTTP")
    return f"{method} {scope.get('path', '')}".strip()


class CallIdMiddleware:
    """Give every HTTP request its correlation ids, bound for the whole request."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # WHY the type guard: lifespan and websocket scopes pass through here too. Binding a
        # per-REQUEST id around the lifespan scope would hold one id for the process's entire
        # life and stamp it onto every boot and shutdown line.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        inbound = _inbound_traceparent(scope)
        trace_id = adopt_or_mint_trace_id(inbound)
        call_id = new_gateway_call_id()
        # The caller's SPAN id, when it sent a usable one — the edge that attaches this
        # gateway's span to the engine node that called it. `adopt_or_mint_trace_id` above
        # keeps only the trace id, which is all a log line needs and not enough for a span.
        # Re-parsing rather than threading it through: one validated read, same rejections.
        parsed = parse_traceparent(inbound)
        parent_span_id = parsed[1] if parsed is not None else None

        async def send_with_trace(message: Message) -> None:
            # INVARIANT: appended, never replacing the header list. A response that already
            # sets headers (content-type, the SSE stream's own) must keep them.
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((TRACE_RESPONSE_HEADER, trace_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        # INVARIANT: the span opens INSIDE `call_scope`. `tracing`'s id generator reads the
        # bound trace id from that scope, so opening the span outside it would mint a
        # different one and produce the two-ids-for-one-call state this middleware exists to
        # prevent (OME-1132). A no-op when tracing is not configured, which is the default.
        with (
            call_scope(call_id, trace_id=trace_id),
            server_span(_route_name(scope), parent_span_id=parent_span_id),
        ):
            # Published on the scope so downstream consumers (the taxonomy session, the
            # exception handlers) read the SAME ids rather than minting a second set for the
            # same request — two ids for one call is worse than none, because both look right.
            state = scope.setdefault("state", {})
            state["gateway_call_id"] = call_id
            state["trace_id"] = trace_id
            await self._app(scope, receive, send_with_trace)


__all__ = ["TRACE_RESPONSE_HEADER", "CallIdMiddleware"]

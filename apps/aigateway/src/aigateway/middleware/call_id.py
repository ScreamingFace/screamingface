"""Bind one `gateway_call_id` per inbound request, for the whole request (OME-938).

WHY the id is minted HERE and not in the taxonomy plugin: it used to be minted in
`plugins/taxonomy/session.py`, and that plugin is gated by `TaxonomyPluginSettings().enabled`
(`AIGW_TAXONOMY_ENABLED`). So turning off a *usage-accounting* feature silently deleted the
*only correlation mechanism* in the gateway — an operator debugging a production incident would
find every log line anonymous and no way to tell why. Correlation is not a feature of
accounting; accounting is one consumer of correlation.

WHY pure ASGI and not `BaseHTTPMiddleware`: `BaseHTTPMiddleware` runs the downstream app in a
SEPARATE task and returns as soon as the response *starts*. This gateway streams SSE, so the
response body is produced after that point — under `BaseHTTPMiddleware` the scope would unbind
while the stream was still being generated, and every line emitted during the stream (which is
where dispatch, retry and provider errors happen) would lose its id. A pure ASGI middleware
holds the scope across the entire send cycle, last chunk included.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from aigateway.call_context import call_scope, new_gateway_call_id


class CallIdMiddleware:
    """Give every HTTP request a correlation id, bound for its whole lifetime."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # WHY the type guard: lifespan and websocket scopes pass through here too. Binding a
        # per-REQUEST id around the lifespan scope would hold one id for the process's entire
        # life and stamp it onto every boot and shutdown line.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        call_id = new_gateway_call_id()
        with call_scope(call_id):
            # Published on the scope so downstream consumers (the taxonomy session, the
            # exception handlers) read the SAME id rather than minting a second one for the
            # same request — two ids for one call is worse than none, because both look right.
            scope.setdefault("state", {})["gateway_call_id"] = call_id
            await self._app(scope, receive, send)


__all__ = ["CallIdMiddleware"]

"""The node's HTTP adapter — ASGI serving and :class:`Url4Error` → status mapping.

The wire half of :class:`~url4.peer.server.Url4Node`, split from the node core:
the node owns WHAT a request resolves to (registries, dispatch policy), this
module owns HOW a resolved request and its failures cross HTTP (framing, status
codes). The two change for different reasons, so they live in different files.

Everything here builds on the ASGI primitives of :mod:`url4.peer._asgi` and the
standard library only — uvicorn is imported lazily inside :func:`serve`, so the
core import graph stays framework-free (see tests/unit/test_import_isolation.py).
The node is consumed through the :class:`~url4.io.layer.IOLayer` port alone
(``fetch``), the same port every adapter implements.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable, Mapping

from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.io.layer import IOLayer
from url4.peer._asgi import lifespan as _lifespan
from url4.peer._asgi import send as _send
from url4.peer._asgi import send_error as _send_error

# HTTP status by spec error code; unlisted codes fall back by exception shape.
# Keyed by ErrorCode members but typed ``dict[str, int]``: ``Url4Error.code`` is a
# ``str`` and ``StrEnum`` members compare equal to their wire strings, so the
# lookup is exact without narrowing the exception attribute to the enum.
_STATUS_BY_CODE: dict[str, int] = {
    ErrorCode.MALFORMED_SOURCE: 400,
    ErrorCode.UNBOUND_REFERENCE: 400,
    ErrorCode.ENDPOINT_NOT_FOUND: 404,
    ErrorCode.UNKNOWN_IDENTITY: 404,
    ErrorCode.IDENTITY_UNAVAILABLE: 404,
    ErrorCode.IDENTITY_ACCESS_DENIED: 403,
    ErrorCode.CONSENT_REQUIRED: 403,
    ErrorCode.CONSENT_WITHHELD: 403,
}


def asgi_app(node: IOLayer) -> Callable[..., Awaitable[None]]:
    """The node as a plain ASGI application (framework-free by construction).

    HTTP requests dispatch through the node's own ``fetch`` port, so HTTP
    behavior and in-process behavior can never diverge.
    """

    async def app(scope: Mapping, receive, send) -> None:
        if scope["type"] == "lifespan":
            await _lifespan(receive, send)
        elif scope["type"] == "http":
            await handle_http(node, scope, send)

    return app


def serve(node: IOLayer, host: str = "127.0.0.1", port: int = 4404, **uvicorn_kwargs) -> None:
    """Serve :func:`asgi_app` with uvicorn (requires the ``url4[server]`` extra)."""
    try:
        uvicorn = importlib.import_module("uvicorn")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "serving a Url4Node over HTTP requires uvicorn — install url4[server]"
        ) from exc
    uvicorn.run(asgi_app(node), host=host, port=port, **uvicorn_kwargs)


async def handle_http(node: IOLayer, scope: Mapping, send) -> None:
    """Answer one ASGI ``http`` scope as a GET-only url4 dispatch."""
    if scope["method"] != "GET":
        # Doctrine N1: the url4 expression is the address; the
        # transactional call is an idempotent, cacheable GET.
        await _send_error(send, 405, "method_not_allowed", "url4 nodes speak GET")
        return
    query = scope.get("query_string", b"").decode("latin-1")
    target = scope["path"] + (f"?{query}" if query else "")
    try:
        body = await node.fetch(target, relative=True)
    except Url4Error as exc:
        await _send_error(send, status_for(exc), exc.code, str(exc))
        return
    await _send(send, 200, [(b"content-type", b"text/plain; charset=utf-8")], body.encode())


def status_for(exc: Url4Error) -> int:
    """The HTTP status for a :class:`Url4Error` (spec codes, then exception shape)."""
    status = _STATUS_BY_CODE.get(exc.code)
    if status is not None:
        return status
    if isinstance(exc, ResolutionError) and not exc.permanent:
        return 502  # transient upstream/source failure
    return 500

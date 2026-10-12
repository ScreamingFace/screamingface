"""The node's HTTP adapter — ASGI serving and :class:`Url4Error` → status mapping.

The wire half of :class:`~url4.peer.server.Url4Node`, split from the node core:
the node owns WHAT a request resolves to (registries, dispatch policy), this
module owns HOW a resolved request and its failures cross HTTP (framing, status
codes). The two change for different reasons, so they live in different files.

Everything here builds on the ASGI primitives of :mod:`url4.peer._asgi` and the
standard library only — uvicorn is imported lazily inside :func:`serve`, so the
core import graph stays framework-free (see tests/unit/test_import_isolation.py).
The node is consumed through the :class:`~url4.io.layer.IOLayer` port alone
(``fetch``), the same port every adapter implements. Stdlib logging is used for
adapter failures outside a run; in-run events go through :mod:`url4.observe`.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable, Mapping

from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.io.layer import IOLayer
from url4.peer._asgi import lifespan as _lifespan
from url4.peer._asgi import send as _send
from url4.peer._asgi import send_error as _send_error

_logger = logging.getLogger(__name__)

# HTTP status by spec error code; unlisted codes fall back by exception shape.
# Keyed by ErrorCode members but typed ``dict[str, int]``: ``Url4Error.code`` is a
# ``str`` and ``StrEnum`` members compare equal to their wire strings, so the
# lookup is exact without narrowing the exception attribute to the enum.
_STATUS_BY_CODE: dict[str, int] = {
    ErrorCode.MALFORMED_SOURCE: 400,
    ErrorCode.UNBOUND_REFERENCE: 400,
    ErrorCode.MISSING_INTENT: 400,
    ErrorCode.ENDPOINT_NOT_FOUND: 404,
    ErrorCode.UNKNOWN_IDENTITY: 404,
    ErrorCode.IDENTITY_UNAVAILABLE: 404,
    ErrorCode.IDENTITY_ACCESS_DENIED: 403,
    ErrorCode.CONSENT_REQUIRED: 403,
    ErrorCode.CONSENT_WITHHELD: 403,
    # No request was sent: the node's own concurrency cap ran the deadline out, so the
    # node is the one that is (temporarily) unavailable — not an upstream failure.
    ErrorCode.ADMISSION_TIMEOUT: 503,
    # url4 2.0 code pointers (contracts C8). A caller applying Spec C §13.2.1 to the
    # status recovers the class: 501 is exactly `unsupported_mode`; `intent_error` has
    # no §13.2.1 row, so 422 keeps it permanent (500 would read as transient) and the
    # JSON body carries the exact code.
    ErrorCode.UNSUPPORTED_MODE: 501,
    ErrorCode.INTENT_ERROR: 422,
    # The node's own bug stays 500 (the generic body hides it), whatever its class.
    ErrorCode.INTERNAL_ERROR: 500,
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
    except Exception:
        # WHY: Spec C §13.5.2 registry row internal_error; the client gets the generic
        # message only (error privacy, cf. §13.5.1), the traceback goes to the log.
        # node.fetch returns before any byte is sent, so the response has not started
        # and a JSON error body can still be written. A handler's own TimeoutError is
        # not a Url4Error, so it lands here too: a handler that means "timeout" must
        # raise a Url4Error with code timeout.
        _logger.exception("unhandled error serving %s", scope["path"])
        await _send_error(send, 500, ErrorCode.INTERNAL_ERROR, "internal error")
        return
    await _send(send, 200, [(b"content-type", b"text/plain; charset=utf-8")], body.encode())


def status_for_code(code: str | None, *, permanent: bool) -> int:
    """The HTTP status for a failed call by spec error code, then exception shape.

    Shared by :func:`status_for` (the node's own dispatch) and
    ``url4.peer.direct.http_status`` (which overlays its own direct-call codes
    first) — one fallback rule: 502 when transient, 422 when permanent, 500 with no code.
    """
    if code is not None:
        status = _STATUS_BY_CODE.get(code)
        if status is not None:
            return status
    if code is None:
        return 500  # no code at all: the node's own failure
    # WHY 422 (contracts C8, owner decision Q10): a caller that maps our status back with
    # Spec C §13.2.1 must recover the CLASS. 500 reads as transient, so an unlisted
    # permanent code (quorum_not_met as a plain error, expansion_not_iterable) was retried.
    return 422 if permanent else 502


def status_for(exc: Url4Error) -> int:
    """The HTTP status for a :class:`Url4Error` (spec codes, then exception shape).

    An unlisted :class:`ResolutionError` is 502 whatever its class: a source this node
    could not resolve is an upstream failure even when retrying cannot help (a 404
    behind the node is still the upstream's 404, not this node's bug). Any other
    unlisted error keeps its own class: 422 when permanent, 502 when transient (C8).
    """
    return status_for_code(
        exc.code, permanent=exc.permanent and not isinstance(exc, ResolutionError)
    )

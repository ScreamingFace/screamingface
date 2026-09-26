"""The public direct-call API: run ONE registered handler of a node, never an expression.

A direct call is what a mount call is (spec D1): ``GET /<endpoint>?q=(context)!intent`` calls
one intent processor with already-resolved context; ``GET /<data route>`` reads one data
route. No grammar, no DAG, no URL-valued context. A target that names no registered handler
and falls in the eval path (``/v1`` and its qualified ``/v1/<collection>`` form — which would
EVALUATE an expression against the node) is REFUSED with
:data:`~url4.core.errors.ErrorCode.DIRECT_EVAL_REFUSED`.

WHY a public module and not the package-private ``_dispatch``: a host that queues mount calls
and runs them elsewhere (the engine's direct runs) needs this guarantee as API, checked where
the call happens — not re-derived from private registries on the other side of a queue.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from url4.core.errors import ErrorCode, ResolutionError
from url4.observe import (
    ModelResponse,
    NodeFinished,
    NodeStarted,
    Observer,
    RunFinished,
    RunStarted,
    Usage,
    _bind_node_sinks,
)
from url4.peer._dispatch import _text, call_endpoint
from url4.peer._http import _STATUS_BY_CODE
from url4.wire.subrequest import extract_expression_params

if TYPE_CHECKING:
    from url4.peer.server import Url4Node


@dataclass(frozen=True)
class DirectResult:
    """The handler's body, and the media type its route declares (``None`` for endpoints and
    for data routes that declare none)."""

    body: str
    media_type: str | None


@dataclass(frozen=True)
class RouteInfo:
    """One route a direct call can reach: its path, kind, and declared media type."""

    path: str
    kind: Literal["endpoint", "data"]
    media_type: str | None


def describe_routes(node: Url4Node) -> list[RouteInfo]:
    """Every endpoint and data route of ``node``, sorted by path — never the eval path."""
    routes = [RouteInfo(path, "endpoint", None) for path in node._endpoints]
    routes += [RouteInfo(path, "data", route.media_type) for path, route in node._data.items()]
    return sorted(routes, key=lambda route: route.path)


def is_eval_path(node: Url4Node, path: str) -> bool:
    """Whether ``path`` is ``node``'s eval path, bare or collection-qualified."""
    return path == node._eval_path or path.startswith(f"{node._eval_path}/")


async def dispatch_direct(
    node: Url4Node,
    target: str,
    *,
    observer: Observer | None = None,
    trace_id: str | None = None,
    root_span_id: str | None = None,
) -> DirectResult:
    """Run the ONE handler ``target`` (``<path>[?query]``) names on ``node``.

    With an ``observer``, the call is reported as a one-node run: ``RunStarted``, then ONE
    ``NodeStarted`` / ``NodeFinished`` pair (a child of ``root_span_id``) with the handler's
    ``Usage`` and ``ModelResponse`` on that span, then ``RunFinished`` — the events a DAG run of
    a single call would emit, so a host maps them to the same span and cost frames. The handler
    reports usage exactly as it does inside a run, through the ctx-less sinks
    (:func:`~url4.observe.current_usage_sink`).

    Raises:
        ResolutionError: ``direct_eval_refused`` for the eval path; ``missing_intent`` for an
            endpoint called without ``q``; ``endpoint_not_found`` for any other path; and the
            subrequest decode errors for a malformed ``q``. All permanent.
    """
    if observer is None:
        return await _dispatch_direct(node, target)
    return await _observed(node, target, observer, trace_id, root_span_id)


async def _observed(
    node: Url4Node,
    target: str,
    observer: Observer,
    trace_id: str | None,
    root_span_id: str | None,
) -> DirectResult:
    root = root_span_id if root_span_id is not None else secrets.token_hex(8)
    span = secrets.token_hex(8)
    seq = itertools.count(1)
    digest = hashlib.sha256(target.encode()).hexdigest()[:16]
    observer.on_event(RunStarted(trace_id or secrets.token_hex(16), root, digest))
    observer.on_event(NodeStarted(span, root, "DirectCall", target.partition("?")[0]))

    def usage(**kwargs: Any) -> None:
        observer.on_event(Usage(span_id=span, **kwargs))

    def response(**kwargs: Any) -> None:
        observer.on_event(ModelResponse(span_id=span, **kwargs))

    try:
        with _bind_node_sinks(usage, response):
            result = await _dispatch_direct(node, target)
    except asyncio.CancelledError:
        observer.on_event(NodeFinished(span, "cancelled", next(seq)))
        observer.on_event(RunFinished("cancelled", next(seq)))
        raise
    except Exception as exc:
        code = getattr(exc, "code", None)
        permanent = getattr(exc, "permanent", None)
        observer.on_event(
            NodeFinished(
                span,
                "error",
                next(seq),
                code=code if isinstance(code, str) else None,
                permanent=permanent if isinstance(permanent, bool) else None,
            )
        )
        observer.on_event(RunFinished("error", next(seq)))
        raise
    observer.on_event(NodeFinished(span, "ok", next(seq)))
    observer.on_event(RunFinished("ok", next(seq)))
    return result


async def _dispatch_direct(node: Url4Node, target: str) -> DirectResult:
    path, sep, query = target.partition("?")
    params, q = extract_expression_params(query) if sep else ({}, None)
    # INVARIANT (D1): only a REGISTERED handler is ever called. The eval branch of `dispatch`
    # (`node._run_text`) is not reachable from here at all — not by an ordering rule, but
    # because this function has no path to it. Endpoints and data routes win by exact
    # registration, which is why a mount UNDER the eval path (`/v1/chat/completions`) is
    # served, while `/v1` itself or an unregistered `/v1/<x>` is refused by name.
    if path in node._endpoints:
        if q is None:
            raise ResolutionError(
                f"endpoint {path!r} needs q=(context)!intent",
                code=ErrorCode.MISSING_INTENT,
                permanent=True,
            )
        return DirectResult(await call_endpoint(node, path, q, params), None)
    route = node._data.get(target) or node._data.get(path)
    if route is not None:
        provider = route.provider
        body = await _text(provider() if callable(provider) else provider)
        return DirectResult(body, route.media_type)
    if is_eval_path(node, path):
        raise ResolutionError(
            f"a direct call may not target the eval path {node._eval_path!r}",
            code=ErrorCode.DIRECT_EVAL_REFUSED,
            permanent=True,
        )
    raise ResolutionError(
        f"node {node.name!r} has no endpoint or data route at {path!r}",
        code=ErrorCode.ENDPOINT_NOT_FOUND,
        permanent=True,
    )


_DIRECT_STATUS: dict[str, int] = {
    ErrorCode.MISSING_INTENT: 400,
    ErrorCode.DIRECT_EVAL_REFUSED: 404,
}
"""What a direct call adds to the node's spec table: an endpoint called without ``q`` is the
caller's error, and the eval path has no direct handler (as if the route did not exist)."""


def http_status(code: str | None, *, permanent: bool) -> int:
    """The HTTP status for a failed direct call with error ``code``.

    The node's own spec table (``url4.peer._http``) plus the direct-call codes; an unlisted
    code falls back by its shape, as the node does: 502 when transient, 500 when permanent.
    WHY public: a host that runs direct calls elsewhere (queued) still answers the caller over
    HTTP, and must answer as the node would have.
    """
    if code is not None:
        status = _DIRECT_STATUS.get(code) or _STATUS_BY_CODE.get(code)
        if status is not None:
            return status
    return 500 if permanent else 502


__all__ = [
    "DirectResult",
    "RouteInfo",
    "describe_routes",
    "dispatch_direct",
    "http_status",
    "is_eval_path",
]

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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from url4.core.errors import ErrorCode, ResolutionError
from url4.peer._dispatch import _text, call_endpoint
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


async def dispatch_direct(node: Url4Node, target: str) -> DirectResult:
    """Run the ONE handler ``target`` (``<path>[?query]``) names on ``node``.

    Raises:
        ResolutionError: ``direct_eval_refused`` for the eval path; ``missing_intent`` for an
            endpoint called without ``q``; ``endpoint_not_found`` for any other path; and the
            subrequest decode errors for a malformed ``q``. All permanent.
    """
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


__all__ = ["DirectResult", "RouteInfo", "describe_routes", "dispatch_direct", "is_eval_path"]

"""The dispatch half of :class:`~url4.peer.server.Url4Node` — how a relative
target resolves against the node's registries.

Split from peer/server.py (second review, F2 — the prepared cut, executed when
the module-size cap fired): ``Url4Node`` keeps registration (endpoint / data /
holdings / identity) and the evaluation facade; this module owns the dispatch
order — how one resolved target crosses that registry surface. The functions
take the node and read its registries directly (package-private by design), so
the dispatch order lives in exactly one place — and the HTTP adapter in
:mod:`url4.peer._http` reuses the same ``fetch`` dispatch, so HTTP behavior
and in-process behavior can never diverge.

Dispatch contract (mirrors the engine's wire conventions):

- **Endpoint paths are intent processors.** ``GET /claude?[params&]q=(ctx)!i``
  calls the registered handler with :class:`Request` — ``context`` is *opaque,
  already-resolved data*. AIDEV-NOTE: engine-internal dispatches wire-escape
  resolved text, so re-evaluating it would mis-parse — handlers never receive
  unresolved expressions.
- **The eval path is the protocol surface** (default ``/v1``). Its ``q=`` is a
  full url4 expression: the node reconstructs it, re-attaches non-transport
  protocol params as the ``;``-chain (so ``broadcast``/``quorum`` keep their
  spec meaning, §6.1.1/§9), and evaluates it against itself — sources resolve
  HERE (§5.6.3 pass-through), the intent dispatches to the node's default
  route (explicit ``default_processor``, else its first registered endpoint).
- **Data routes** serve plain reads (`/api/rows`) for sources and collections.
- **GET is the only verb.** WHY: url4-engine doctrine N1 — the expression is the
  address, so the transactional call is an idempotent, cacheable GET.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from inspect import isawaitable
from typing import TYPE_CHECKING

from url4.core.errors import ErrorCode, ResolutionError
from url4.core.subrequest import (
    TRANSPORT_ONLY_PARAMS,
    decode_expression_http,
    decode_subrequest_http,
    extract_expression_params,
)
from url4.io.layer import FetchRequest, FetchResult, fetch_result, resolve_shelf

if TYPE_CHECKING:  # the node type only — this module never constructs one
    from url4.peer.server import Url4Node


@dataclass(frozen=True)
class Request:
    """One decoded intent-processor call: ``GET <path>?[params&]q=(context)!intent``.

    ``context`` is opaque resolved data (see the module contract); ``params``
    are the decoded protocol params that preceded ``q=``.
    """

    path: str
    context: str
    intent: str
    params: Mapping[str, str]


# Transport-level query params a node consumes itself rather than re-attaching
# to the expression (spec §11.6.3); `processor` is expression-bearing and its
# delegation semantics (§27.3) are not implemented yet.
# The ingress set is broader than the spec's transport-only rule: it also drops
# params this node consumes itself (delivery/cb/meta/v) and `processor`, whose
# §27.3 delegation semantics are not implemented yet (see `OME-506`).
# INVARIANT: _TRANSPORT_PARAMS is DERIVED from TRANSPORT_ONLY_PARAMS, so the two
# can never disagree about resume/rid.
_TRANSPORT_PARAMS = TRANSPORT_ONLY_PARAMS | frozenset({"delivery", "cb", "meta", "v", "processor"})


# --- the IOLayer ports (a node IS an io layer) -------------------------------------


async def fetch(node: Url4Node, target: str, *, relative: bool) -> str:
    return (
        await dispatch(node, target)
        if relative or target.startswith("/")
        else (await node._outbound_io().fetch(target, relative=False))
    )


async def fetch_ex(node: Url4Node, request: FetchRequest) -> FetchResult:
    if request.relative or request.target.startswith("/"):
        body = await dispatch(node, request.target)
        return FetchResult(body, data_media_type(node, request.target))
    return await fetch_result(node._outbound_io(), request)


def data_media_type(node: Url4Node, target: str) -> str | None:
    """The declared Content-Type of the data route serving ``target``, if any.

    Mirrors ``dispatch``'s exact-target-then-path data lookup; endpoint and
    eval-path dispatches have no declared media type and report None.
    """
    route = node._data.get(target) or node._data.get(target.partition("?")[0])
    return route.media_type if route is not None else None


async def fetch_holdings(node: Url4Node, identity: str | None, collection: str | None) -> str:
    if identity is None:
        handler = resolve_shelf(node._self_holdings, collection)
        if handler is None:
            raise ResolutionError(f"node {node.name!r} serves no self holdings for {collection!r}")
        return await _text(handler(collection))
    named = node._identities.get(identity)
    if named is None:
        raise ResolutionError(
            f"unknown identity {identity!r} on node {node.name!r}",
            code=ErrorCode.UNKNOWN_IDENTITY,
            permanent=True,
        )
    return await _text(named(collection))


# --- the dispatch core ----------------------------------------------------------------


async def dispatch(node: Url4Node, target: str) -> str:
    path, sep, query = target.partition("?")
    params, q = extract_expression_params(query) if sep else ({}, None)
    if q is not None:
        expression_result = await dispatch_expression(node, path, q, params)
        if expression_result is not None:
            return expression_result
    # INVARIANT: exact-target first, then the bare path — membership, not
    # `.get(..., .get(...))`, so a hit avoids the second lookup and a
    # legitimately falsy provider (e.g. "") is still served rather than skipped.
    if target in node._data:
        route = node._data[target]
    elif path in node._data:
        route = node._data[path]
    else:
        route = None
    if route is not None:
        provider = route.provider
        return await _text(provider() if callable(provider) else provider)
    raise ResolutionError(
        f"node {node.name!r} has no endpoint, eval path, or data route at {path!r}",
        code=ErrorCode.ENDPOINT_NOT_FOUND,
        permanent=True,
    )


async def dispatch_expression(
    node: Url4Node, path: str, q: str, params: Mapping[str, str]
) -> str | None:
    """Route an expression-bearing request, or ``None`` if ``path`` bears none.

    Returning ``None`` (rather than raising) lets :func:`dispatch` fall
    through to the data routes, so a data path carrying its own ``?q=…``
    query is still served as data.
    """
    if path in node._endpoints:
        return await call_endpoint(node, path, q, params)
    # Spec §5.6.1/§5.6.3.1 — `{eval_path}/<qualifier>` evaluates the
    # expression with `@` scoped to that self-holdings collection:
    # `GET /v1/science?q=(@)!'…'`. Multi-segment qualifiers join with "/"
    # (`/v1/a/b` -> "a/b"), matching how an identity-collection is carried
    # (§5.6.2); the bare eval path yields "" -> None, the default shelf.
    # Endpoints are matched first, so a command route still wins its exact
    # path; `_check_routable` keeps the two from overlapping.
    if path == node._eval_path or path.startswith(f"{node._eval_path}/"):
        collection = path[len(node._eval_path) + 1 :]
        # AIDEV-NOTE: `processor` is consumed here, not re-attached by
        # `reassemble` — it selects this run's processor, not an expression param.
        return await node._run_text(
            reassemble(q, params),
            self_collection=collection or None,
            processor=params.get("processor"),
        )
    return None


async def call_endpoint(node: Url4Node, path: str, q: str, params: Mapping[str, str]) -> str:
    context, intent = decode_subrequest_http(q)
    request = Request(path=path, context=context, intent=intent, params=params)
    return await _text(node._endpoints[path](request))


# --- helpers ------------------------------------------------------------------------------


def reassemble(q: str, params: Mapping[str, str]) -> str:
    """Rebuild the eval-path expression, re-attaching non-transport params.

    The dual-convention decode lives with the wire codec
    (:func:`url4.core.subrequest.decode_expression_http` — one owner, spec §3.4).
    ``broadcast`` and friends keep their §9 semantics by riding the trailing
    ``;`` chain the envelope decode reads (a flag param decodes to value "").
    """
    text = decode_expression_http(q)
    for key, value in params.items():
        if key not in _TRANSPORT_PARAMS:
            text += f";{key}" if value == "" else f";{key}={value}"
    return text


async def _text(result: str | Awaitable[str]) -> str:
    return await result if isawaitable(result) else result

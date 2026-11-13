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
  unresolved expressions. No ``q`` on an endpoint is 400 ``missing_intent``.
- **The eval path is the protocol surface** (default ``/v1``). Its ``q=`` is a
  full url4 expression: the node reconstructs it, re-attaches non-transport
  protocol params as the ``;``-chain (so ``broadcast``/``quorum`` keep their
  spec meaning, §6.1.1/§9), and evaluates it against itself — sources resolve
  HERE (§5.6.3 pass-through), the intent dispatches to the node's default
  route (explicit ``default_processor``, else its first registered endpoint).
  No ``q`` on the eval path is 400 ``missing_intent``. The direct path never
  evaluates, so it refuses the eval path by name (:mod:`url4.peer.direct`).
- **Data routes** serve plain reads (`/api/rows`) for sources and collections.
  A data route cannot live under the eval path: the node evaluates there.
- **GET is the only verb.** WHY: url4-engine doctrine N1 — the expression is the
  address, so the transactional call is an idempotent, cacheable GET.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import TYPE_CHECKING

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.layer import FetchRequest, FetchResult, fetch_result, resolve_shelf
from url4.wire.subrequest import (
    decode_subrequest_http,
    extract_expression_params,
)

# WHY: redundant aliases re-export the ingress rebuild from its own module, so every
# ``url4.peer._dispatch.<name>`` import path keeps working.
from url4.peer._reassemble import _TRANSPORT_PARAMS as _TRANSPORT_PARAMS  # isort: skip
from url4.peer._reassemble import reassemble as reassemble  # isort: skip

if TYPE_CHECKING:  # the node type only — this module never constructs one
    from url4.peer.server import Url4Node, _DataRoute


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
    attachments: tuple[Attachment, ...] = field(default=(), repr=False)
    """The calling run's files, in order (F2): set for an in-process call only. An HTTP
    ingress has no calling run, so a remote caller's files never arrive here (D6)."""


# --- the IOLayer ports (a node IS an io layer) -------------------------------------


async def fetch(node: Url4Node, target: str, *, relative: bool) -> str:
    return (
        await dispatch(node, target)
        if relative or target.startswith("/")
        else (await node._outbound_io().fetch(target, relative=False))
    )


async def fetch_ex(node: Url4Node, request: FetchRequest) -> FetchResult:
    if request.relative or request.target.startswith("/"):
        return await dispatch_result(node, request.target)
    return await fetch_result(node._outbound_io(), request)


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


def data_route(node: Url4Node, target: str, path: str) -> _DataRoute | None:
    """The data route serving ``target`` (exact) or ``path`` (bare), or ``None``.

    INVARIANT: exact-target first, then the bare path — membership, not
    `.get(..., .get(...))`, so a hit avoids the second lookup and a
    legitimately falsy provider (e.g. "") is still served rather than skipped.
    """
    if target in node._data:
        return node._data[target]
    if path in node._data:
        return node._data[path]
    return None


async def serve_data(route: _DataRoute) -> FetchResult:
    """Read one data route: its provider's body, with the media type the route declares."""
    provider = route.provider
    body = await _text(provider() if callable(provider) else provider)
    return FetchResult(body, route.media_type)


async def dispatch_result(node: Url4Node, target: str) -> FetchResult:
    """Run the one branch ``target`` names, and report the media type that branch declares.

    Branches run in order: an endpoint (exact path), the eval path (bare or
    ``/<collection>``), then a data route. A data path that carries its own
    ``?q=`` is neither an endpoint nor under the eval path, so it is still
    served as data, with that data route's declared media type.
    """
    path, sep, query = target.partition("?")
    params, q = extract_expression_params(query) if sep else ({}, None)
    if path in node._endpoints:
        if q is None:
            raise missing_intent(path, "q=(context)!intent")
        return FetchResult(await call_endpoint(node, path, q, params), None)
    # Spec §5.6.1/§5.6.3.1 — `{eval_path}/<qualifier>` evaluates the
    # expression with `@` scoped to that self-holdings collection:
    # `GET /v1/science?q=(@)!'…'`. Multi-segment qualifiers join with "/"
    # (`/v1/a/b` -> "a/b"), matching how an identity-collection is carried
    # (§5.6.2); the bare eval path yields "" -> None, the default shelf.
    # Endpoints are matched first, so a command route still wins its exact
    # path; `_check_routable` keeps the two from overlapping.
    if node._is_eval_path(path):
        if q is None:
            raise missing_intent(path, "q=<expression>")
        collection = path[len(node._eval_path) + 1 :]
        # AIDEV-NOTE: `processor` is consumed here, not re-attached by
        # `reassemble` — it selects this run's processor, not an expression param.
        text = await node._run_text(
            reassemble(q, params),
            self_collection=collection or None,
            processor=params.get("processor"),
        )
        return FetchResult(text, None)
    route = data_route(node, target, path)
    if route is not None:
        return await serve_data(route)
    raise ResolutionError(
        f"node {node.name!r} has no endpoint, eval path, or data route at {path!r}",
        code=ErrorCode.ENDPOINT_NOT_FOUND,
        permanent=True,
    )


async def dispatch(node: Url4Node, target: str) -> str:
    return (await dispatch_result(node, target)).body


async def call_endpoint(node: Url4Node, path: str, q: str, params: Mapping[str, str]) -> str:
    context, intent = decode_subrequest_http(q)
    request = Request(
        path=path,
        context=context,
        intent=intent,
        params=params,
        attachments=current_attachments(),
    )
    return await _text(node._endpoints[path](request))


# --- helpers ------------------------------------------------------------------------------


def missing_intent(path: str, needs: str) -> ResolutionError:
    """The permanent 400 for a call to ``path`` that carries no ``q=``; ``needs`` names the form."""
    return ResolutionError(f"{path!r} needs {needs}", code=ErrorCode.MISSING_INTENT, permanent=True)


async def _text(result: str | Awaitable[str]) -> str:
    return await result if isawaitable(result) else result

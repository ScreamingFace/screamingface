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
from typing import TYPE_CHECKING, Literal

from url4.core._annotations import read_query_tail
from url4.core._scan import iter_top_level
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.io.layer import FetchRequest, FetchResult, fetch_result, resolve_shelf
from url4.wire.rds import RdsValue, decode_q_payload, decode_rds_document
from url4.wire.subrequest import (
    TRANSPORT_ONLY_PARAMS,
    decode_expression_http,
    decode_subrequest_http,
    extract_expression_params,
    split_expression_query,
)

if TYPE_CHECKING:  # the node type only — this module never constructs one
    from url4.peer.server import Url4Node, _DataRoute


@dataclass(frozen=True)
class Request:
    """One decoded intent-processor call: ``GET <path>?[params&]q=(context)!intent``.

    ``context`` is opaque resolved data (see the module contract); ``params``
    are the decoded protocol params that preceded ``q=``.

    In RDS mode (``mode == "rds"``, a code-pointer call with no ``!`` tail): ``context`` is the
    input document's JSON text exactly as received, ``intent`` is ``""`` (the path is the code
    pointer), ``params`` are the query-tail params, and ``inputs`` is the document's ``inputs``.
    """

    path: str
    context: str
    intent: str
    params: Mapping[str, str]
    # WHY: the default keeps every 1.x handler working; only an RDS call sets the new fields.
    mode: Literal["llm", "rds"] = "llm"
    # INVARIANT: `inputs` is set if and only if `mode == "rds"` (contracts C1 `inputs`).
    inputs: Mapping[str, RdsValue] | None = None


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


async def dispatch(node: Url4Node, target: str) -> str:
    path, sep, query = target.partition("?")
    rds = rds_call(query) if sep else None
    if rds is not None:
        return await call_rds(node, path, *rds)
    params, q = extract_expression_params(query) if sep else ({}, None)
    if q is not None:
        expression_result = await dispatch_expression(node, path, q, params)
        if expression_result is not None:
            return expression_result
    route = data_route(node, target, path)
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


def rds_call(query_string: str) -> tuple[dict[str, str], str, dict[str, RdsValue]] | None:
    """The RDS call a query string carries, as ``(params, document text, inputs)``, else ``None``.

    A request is RDS when its ``q=`` payload has no ``!`` tail and decodes to a valid v1 document
    (contracts C2 step 3). Any other request is an LLM call, and the caller keeps today's path.
    The query-tail params are read from the raw text before ``q=``, so the author's bytes reach
    :func:`~url4.core._annotations.read_query_tail` unchanged.
    """
    _raw_params, raw_q = split_expression_query(query_string)
    document = None if raw_q is None else decode_q_payload(raw_q)
    inputs = None if document is None else decode_rds_document(document)
    if document is None or inputs is None:
        return None
    return read_query_tail(_raw_query_tail(query_string)), document, inputs


def _raw_query_tail(query_string: str) -> str:
    """The raw text before the depth-0 ``q=`` segment, without the ``&`` that separates them.

    INVARIANT: ``q=`` is the last non-empty segment (`split_expression_query` refuses anything
    after it), so the separator before it is the last depth-0 ``&`` once trailing empty segments
    are dropped. The slice is by position, never by re-joining the parsed pairs.
    """
    body = query_string.rstrip("&")
    separators = [index for index, ch in iter_top_level(body) if ch == "&"]
    return query_string[: separators[-1]] if separators else ""


async def call_rds(
    node: Url4Node,
    path: str,
    params: Mapping[str, str],
    document: str,
    inputs: Mapping[str, RdsValue],
) -> str:
    """Call the code pointer at ``path`` once with an RDS document — the one RDS owner.

    Both :func:`dispatch` and :func:`~url4.peer.direct.dispatch_direct` call this, so the RDS rules
    exist in one place. INVARIANT: an RDS request runs only a registered endpoint. A path with no
    endpoint is ``intent_error``, never the eval path and never a data route.
    """
    if path not in node._endpoints:
        raise ResolutionError(
            f"node {node.name!r} has no code pointer at {path!r}",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        )
    request = Request(
        path=path, context=document, intent="", params=params, mode="rds", inputs=inputs
    )
    try:
        result = await _text(node._endpoints[path](request))
    except Url4Error:
        raise
    except Exception as exc:
        # WHY: a failure inside the code pointer is the author's input failing, so it is permanent
        # and keeps the chained cause. Only a url4 error keeps its own code (contracts C7).
        raise ResolutionError(
            f"code pointer {path!r} failed: {exc}",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        ) from exc
    if not isinstance(result, str):
        raise ResolutionError(
            f"code pointer {path!r} returned {type(result).__name__}, not text",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        )
    return result


# --- helpers ------------------------------------------------------------------------------


def reassemble(q: str, params: Mapping[str, str]) -> str:
    """Rebuild the eval-path expression, re-attaching non-transport params.

    The dual-convention decode lives with the wire codec
    (:func:`url4.wire.subrequest.decode_expression_http` — one owner, spec §3.4).
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

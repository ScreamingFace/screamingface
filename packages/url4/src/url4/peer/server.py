"""The node-side SDK — :class:`Url4Node`: registries, evaluation, and ASGI serving.

A node IS an :class:`~url4.io.layer.IOLayer`: it implements ``fetch`` (routing
relative targets to its own endpoints / eval path / data routes and delegating
absolute URIs outbound), ``fetch_ex``, and ``fetch_holdings`` (``@`` and
``@identity``, spec §5.6). In-process evaluation is therefore just
``run(expression, io=self)`` — and the ASGI shim reuses the same dispatch, so
HTTP behavior and in-process behavior can never diverge.

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

Deferred by design: response envelopes, streaming delivery, requestor
authentication and consent hooks (they need the URL4-Auth-Token / Part C
transport spec); identity handlers may raise the spec error codes themselves.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from inspect import isawaitable, signature
from typing import overload

from url4.core.context import Context
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.core.grammar import _IDENTITY_NAME_RE
from url4.core.nodes import Node
from url4.core.render import render
from url4.core.subrequest import (
    TRANSPORT_ONLY_PARAMS,
    decode_expression_http,
    decode_subrequest_http,
    extract_expression_params,
)
from url4.dag import DEFAULT_RUN_CONCURRENCY, ExecutionContext, run
from url4.dag.node import ProcessFn, default_process
from url4.io.layer import FetchRequest, FetchResult, IOLayer, fetch_result, resolve_shelf
from url4.peer._owned import _OwnedIO
from url4.peer.client import Url4Result

# Transport-level query params a node consumes itself rather than re-attaching
# to the expression (spec §11.6.3); `processor` is expression-bearing and its
# delegation semantics (§27.3) are not implemented yet.
# The ingress set is broader than the spec's transport-only rule: it also drops
# params this node consumes itself (delivery/cb/meta/v) and `processor`, whose
# §27.3 delegation semantics are not implemented yet (see `OME-506`).
# INVARIANT: _TRANSPORT_PARAMS is DERIVED from TRANSPORT_ONLY_PARAMS, so the two
# can never disagree about resume/rid.
_TRANSPORT_PARAMS = TRANSPORT_ONLY_PARAMS | frozenset({"delivery", "cb", "meta", "v", "processor"})

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


EndpointHandler = Callable[[Request], str | Awaitable[str]]
# handlers may take the requested collection or nothing at all
HoldingsHandler = Callable[[str | None], str | Awaitable[str]] | Callable[[], str | Awaitable[str]]
_HoldingsPort = Callable[[str | None], str | Awaitable[str]]
DataCallable = Callable[[], str | Awaitable[str]]
DataProvider = str | DataCallable


@dataclass(frozen=True)
class _DataRoute:
    """A registered data route: its provider plus the optional declared media type."""

    provider: DataProvider
    media_type: str | None = None


class Url4Node:
    """A url4 protocol node: endpoint/holdings/identity registries + dispatch.

    ``outbound`` is the IOLayer for absolute (``https://``, ``url4://``, …)
    sources; omitted, an httpx adapter is created lazily and owned. The node
    itself is the io layer for everything relative.
    """

    def __init__(
        self,
        name: str = "node",
        *,
        eval_path: str = "/v1",
        default_processor: str | None = None,
        process_fn: ProcessFn = default_process,
        outbound: IOLayer | None = None,
        data: Mapping[str, DataProvider] | None = None,
        concurrency: int | None = DEFAULT_RUN_CONCURRENCY,
        strict_fields: bool = False,
    ) -> None:
        self.name = name
        self._eval_path = eval_path
        self._processor = default_processor
        self._process = process_fn
        self._owned = _OwnedIO(outbound)
        self._concurrency = concurrency
        self._strict_fields = strict_fields
        self._endpoints: dict[str, EndpointHandler] = {}
        self._data: dict[str, _DataRoute] = {}
        self._self_holdings: dict[str | None, _HoldingsPort] = {}
        self._identities: dict[str, _HoldingsPort] = {}
        for path, provider in (data or {}).items():
            self.data(path, provider)

    def __repr__(self) -> str:
        counts = (
            (len(self._endpoints), "endpoint", "endpoints"),
            (len(self._self_holdings), "holdings shelf", "holdings shelves"),
            (len(self._identities), "identity", "identities"),
            (len(self._data), "data route", "data routes"),
        )
        listed = ", ".join(f"{n} {one if n == 1 else many}" for n, one, many in counts if n)
        return f"<Url4Node {self.name!r}: {listed or 'empty'}>"

    # --- registration ----------------------------------------------------------

    def endpoint(self, path: str) -> Callable[[EndpointHandler], EndpointHandler]:
        """Register an intent processor at ``path`` (decorator)."""
        self._check_routable(path)

        def register(handler: EndpointHandler) -> EndpointHandler:
            self._endpoints[path] = handler
            return handler

        return register

    @overload
    def data(
        self, path: str, *, media_type: str | None = None
    ) -> Callable[[DataCallable], DataCallable]: ...

    @overload
    def data(self, path: str, provider: DataProvider, *, media_type: str | None = None) -> None: ...

    def data(
        self, path: str, provider: DataProvider | None = None, *, media_type: str | None = None
    ) -> Callable[[DataCallable], DataCallable] | None:
        """Serve a plain data read at ``path`` — static text, a callable, or a decorator.

        ``node.data("/api/rows", '[…]')`` registers a value directly;
        ``@node.data("/api/rows")`` decorates a provider function. ``media_type``
        declares the route's Content-Type so a collection served here parses by
        its declared type (spec §5.3.7) rather than being sniffed — the node's
        :meth:`fetch_ex` reports it when it serves this route.
        """
        self._check_routable(path)
        if provider is not None:
            self._data[path] = _DataRoute(provider, media_type)
            return None

        def register(fn: DataCallable) -> DataCallable:
            self._data[path] = _DataRoute(fn, media_type)
            return fn

        return register

    @overload
    def holdings(self, collection: HoldingsHandler) -> HoldingsHandler: ...

    @overload
    def holdings(
        self, collection: str | None = None
    ) -> Callable[[HoldingsHandler], HoldingsHandler]: ...

    def holdings(
        self, collection: str | HoldingsHandler | None = None
    ) -> Callable[[HoldingsHandler], HoldingsHandler] | HoldingsHandler:
        """Register the node's own ``@`` holdings (optionally per collection).

        Use bare (``@node.holdings``), default (``@node.holdings()``), or per
        shelf (``@node.holdings("science")``). Handlers may take the requested
        collection or nothing at all.
        """
        if callable(collection):  # bare @node.holdings
            return self._register_holdings(None, collection)

        def register(handler: HoldingsHandler) -> HoldingsHandler:
            return self._register_holdings(collection, handler)

        return register

    def _register_holdings(
        self, collection: str | None, handler: HoldingsHandler
    ) -> HoldingsHandler:
        if collection in self._self_holdings:
            raise ValueError(f"holdings for collection {collection!r} already registered")
        self._self_holdings[collection] = _adapt_holdings(handler)
        return handler

    def identity(self, name: str) -> Callable[[HoldingsHandler], HoldingsHandler]:
        """Register a principal's ``@name`` holdings (§5.6.2).

        The handler takes the requested collection (or nothing) and may raise
        :class:`~url4.core.errors.ResolutionError` with the spec's codes
        (``identity_access_denied``, ``consent_required``, …) to gate access.
        """
        if not _IDENTITY_NAME_RE.fullmatch(name) or name in self._identities:
            raise ValueError(f"invalid or duplicate identity name {name!r}")

        def register(handler: HoldingsHandler) -> HoldingsHandler:
            self._identities[name] = _adapt_holdings(handler)
            return handler

        return register

    def processor_routes(self) -> list[str]:
        """The registered endpoint paths a `processor=` id may name (§27.3)."""
        return list(self._endpoints)

    def default_route(self) -> str | None:
        """The node's reduce route (:class:`~url4.io.layer.SupportsDefaultRoute`).

        The explicit ``default_processor`` when one was given, else the FIRST
        registered endpoint — the node hardcodes no route names; with neither,
        a fan-out reduce fails with a clear error.
        """
        if self._processor is not None:
            return self._processor
        return next(iter(self._endpoints), None)

    def _check_routable(self, path: str) -> None:
        if not path.startswith("/"):
            raise ValueError(f"route path {path!r} must start with '/'")
        if path == self._eval_path:
            raise ValueError(f"{path!r} is the eval path — it is dispatched by the node itself")
        if path in self._endpoints or path in self._data:
            raise ValueError(f"path {path!r} is already registered")

    # --- the IOLayer ports (a node IS an io layer) ----------------------------------

    async def fetch(self, target: str, *, relative: bool) -> str:
        if relative or target.startswith("/"):
            return await self._dispatch(target)
        return await self._outbound_io().fetch(target, relative=False)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        if request.relative or request.target.startswith("/"):
            body = await self._dispatch(request.target)
            return FetchResult(body, self._data_media_type(request.target))
        return await fetch_result(self._outbound_io(), request)

    def _data_media_type(self, target: str) -> str | None:
        """The declared Content-Type of the data route serving ``target``, if any.

        Mirrors ``_dispatch``'s exact-target-then-path data lookup; endpoint and
        eval-path dispatches have no declared media type and report None.
        """
        route = self._data.get(target) or self._data.get(target.partition("?")[0])
        return route.media_type if route is not None else None

    async def fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        if identity is None:
            handler = resolve_shelf(self._self_holdings, collection)
            if handler is None:
                raise ResolutionError(
                    f"node {self.name!r} serves no self holdings for {collection!r}"
                )
            return await _text(handler(collection))
        named = self._identities.get(identity)
        if named is None:
            raise ResolutionError(
                f"unknown identity {identity!r} on node {self.name!r}",
                code=ErrorCode.UNKNOWN_IDENTITY,
                permanent=True,
            )
        return await _text(named(collection))

    # --- dispatch -----------------------------------------------------------------

    async def _dispatch(self, target: str) -> str:
        path, sep, query = target.partition("?")
        params, q = extract_expression_params(query) if sep else ({}, None)
        if q is not None:
            expression_result = await self._dispatch_expression(path, q, params)
            if expression_result is not None:
                return expression_result
        # INVARIANT: exact-target first, then the bare path — membership, not
        # `.get(..., .get(...))`, so a hit avoids the second lookup and a
        # legitimately falsy provider (e.g. "") is still served rather than skipped.
        if target in self._data:
            route: _DataRoute | None = self._data[target]
        elif path in self._data:
            route = self._data[path]
        else:
            route = None
        if route is not None:
            provider = route.provider
            return await _text(provider() if callable(provider) else provider)
        raise ResolutionError(
            f"node {self.name!r} has no endpoint, eval path, or data route at {path!r}",
            code=ErrorCode.ENDPOINT_NOT_FOUND,
            permanent=True,
        )

    async def _dispatch_expression(
        self, path: str, q: str, params: Mapping[str, str]
    ) -> str | None:
        """Route an expression-bearing request, or ``None`` if ``path`` bears none.

        Returning ``None`` (rather than raising) lets :meth:`_dispatch` fall
        through to the data routes, so a data path carrying its own ``?q=…``
        query is still served as data.
        """
        if path in self._endpoints:
            return await self._call_endpoint(path, q, params)
        # Spec §5.6.1/§5.6.3.1 — `{eval_path}/<qualifier>` evaluates the
        # expression with `@` scoped to that self-holdings collection:
        # `GET /v1/science?q=(@)!'…'`. Multi-segment qualifiers join with "/"
        # (`/v1/a/b` -> "a/b"), matching how an identity-collection is carried
        # (§5.6.2); the bare eval path yields "" -> None, the default shelf.
        # Endpoints are matched first, so a command route still wins its exact
        # path; `_check_routable` keeps the two from overlapping.
        if path == self._eval_path or path.startswith(f"{self._eval_path}/"):
            collection = path[len(self._eval_path) + 1 :]
            # AIDEV-NOTE: `processor` is consumed here, not re-attached by
            # `_reassemble` — it selects this run's processor, not an expression param.
            return await self._run_text(
                _reassemble(q, params),
                self_collection=collection or None,
                processor=params.get("processor"),
            )
        return None

    async def _call_endpoint(self, path: str, q: str, params: Mapping[str, str]) -> str:
        context, intent = decode_subrequest_http(q)
        request = Request(path=path, context=context, intent=intent, params=params)
        return await _text(self._endpoints[path](request))

    async def _run_text(
        self,
        text: str,
        env: Mapping[str, object] | None = None,
        *,
        self_collection: str | None = None,
        processor: str | None = None,
    ) -> str:
        # WHY the request's `processor=` wins: §27.3 lets a CALLER select the
        # processor for this evaluation. The node's own `default_processor` is
        # the fallback when the request names none.
        ctx = ExecutionContext(
            self,
            processor=processor or self._processor,
            process=self._process,
            scope=Context(bindings=dict(env)) if env else None,
            strict_fields=self._strict_fields,
            self_collection=self_collection,
        )
        return await run(text, ctx=ctx, concurrency=self._concurrency)

    # --- evaluation and serving --------------------------------------------------------

    async def evaluate(
        self, expression: str | Node, *, env: Mapping[str, object] | None = None
    ) -> Url4Result:
        """Evaluate a url4 expression in-process, with this node as its world."""
        request = expression if isinstance(expression, str) else render(expression)
        text = await self._run_text(request, env)
        return Url4Result(text=text, request=request)

    def asgi(self):
        """The node as a plain ASGI application (framework-free by construction)."""

        async def app(scope: Mapping, receive, send) -> None:
            if scope["type"] == "lifespan":
                await _lifespan(receive, send)
            elif scope["type"] == "http":
                await self._handle_http(scope, send)

        return app

    def serve(self, host: str = "127.0.0.1", port: int = 4404, **uvicorn_kwargs) -> None:
        """Serve :meth:`asgi` with uvicorn (requires the ``url4[server]`` extra)."""
        try:
            uvicorn = importlib.import_module("uvicorn")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "serving a Url4Node over HTTP requires uvicorn — install url4[server]"
            ) from exc
        uvicorn.run(self.asgi(), host=host, port=port, **uvicorn_kwargs)

    async def aclose(self) -> None:
        """Close the lazily-owned outbound adapter (injected outbound is left alone)."""
        await self._owned.aclose()

    async def __aenter__(self) -> Url4Node:
        await self._owned.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._owned.__aexit__(*exc_info)

    def _outbound_io(self) -> IOLayer:
        return self._owned.outbound()

    async def _handle_http(self, scope: Mapping, send) -> None:
        if scope["method"] != "GET":
            # Doctrine N1: the url4 expression is the address; the
            # transactional call is an idempotent, cacheable GET.
            await _send_error(send, 405, "method_not_allowed", "url4 nodes speak GET")
            return
        query = scope.get("query_string", b"").decode("latin-1")
        target = scope["path"] + (f"?{query}" if query else "")
        try:
            body = await self.fetch(target, relative=True)
        except Url4Error as exc:
            await _send_error(send, _status_for(exc), exc.code, str(exc))
            return
        await _send(send, 200, "text/plain; charset=utf-8", body.encode())


# --- module helpers ------------------------------------------------------------------


def _reassemble(q: str, params: Mapping[str, str]) -> str:
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


def _adapt_holdings(handler: Callable[..., str | Awaitable[str]]) -> _HoldingsPort:
    """Normalize a holdings/identity handler to the one-arg port shape.

    Zero-arg handlers are common (most holdings don't branch on the requested
    collection); detect them by signature and drop the argument for them.
    """
    try:
        signature(handler).bind(None)
    except TypeError:
        return lambda _collection: handler()
    except ValueError:  # no introspectable signature — assume the port shape
        return handler
    return handler


def _status_for(exc: Url4Error) -> int:
    status = _STATUS_BY_CODE.get(exc.code)
    if status is not None:
        return status
    if isinstance(exc, ResolutionError) and not exc.permanent:
        return 502  # transient upstream/source failure
    return 500


async def _lifespan(receive, send) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def _send(send, status: int, content_type: str, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", content_type.encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_error(send, status: int, code: str, message: str) -> None:
    payload = json.dumps({"error": {"code": code, "message": message}})
    await _send(send, status, "application/json", payload.encode())


__all__ = ["DataProvider", "EndpointHandler", "HoldingsHandler", "Request", "Url4Node"]

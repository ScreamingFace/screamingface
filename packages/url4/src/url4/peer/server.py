"""The node-side SDK — :class:`Url4Node`: registries and evaluation.

A node IS an :class:`~url4.io.layer.IOLayer`: it implements ``fetch`` (routing
relative targets to its own endpoints / eval path / data routes and delegating
absolute URIs outbound), ``fetch_ex``, and ``fetch_holdings`` (``@`` and
``@identity``, spec §5.6). In-process evaluation is therefore just
``run(expression, io=self)`` — and the HTTP adapter in :mod:`url4.peer._http`
reuses the same ``fetch`` dispatch, so HTTP behavior and in-process behavior
can never diverge.

The dispatch half — how a relative target resolves against these registries —
lives in :mod:`url4.peer._dispatch` (the second review's F2 split, made when
the module-size cap fired): this module owns what a request CAN resolve to
(registration) and the evaluation facade; that module owns the dispatch order.

The ``@`` holdings and ``@identity`` registration (spec §5.6) lives in
:mod:`url4.peer._holdings`, a mixin that :class:`Url4Node` inherits.

Deferred by design: response envelopes, streaming delivery, requestor
authentication and consent hooks (they need the URL4-Auth-Token / Part C
transport spec); identity handlers may raise the spec error codes themselves.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import overload

from url4.core.context import Context
from url4.core.nodes import Node
from url4.core.render import render
from url4.dag import DEFAULT_RUN_CONCURRENCY, ExecutionContext, ProcessFn, default_process, run
from url4.io.layer import FetchRequest, FetchResult, IOLayer
from url4.peer import _dispatch
from url4.peer._holdings import HoldingsHandler, _HoldingsRegistration
from url4.peer._http import asgi_app as _asgi_app
from url4.peer._http import serve as _serve_node
from url4.peer._owned import _OwnedIO
from url4.peer._request import Request
from url4.peer.client import Url4Result, _blaming_render

EndpointHandler = Callable[[Request], str | Awaitable[str]]
DataCallable = Callable[[], str | Awaitable[str]]
DataProvider = str | DataCallable


@dataclass(frozen=True)
class _DataRoute:
    """A registered data route: its provider plus the optional declared media type."""

    provider: DataProvider
    media_type: str | None = None


class Url4Node(_HoldingsRegistration):
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
        self._rds_endpoints: set[str] = set()
        self._data: dict[str, _DataRoute] = {}
        self._init_holdings()
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

    @property
    def eval_path(self) -> str:
        """The path this node serves its eval expressions on (set by ``eval_path=``)."""
        return self._eval_path

    # --- registration ----------------------------------------------------------

    def endpoint(
        self, path: str, *, rds: bool = False
    ) -> Callable[[EndpointHandler], EndpointHandler]:
        """Register an intent processor at ``path`` (decorator).

        ``rds=True`` opts in to code-pointer calls; LLM calls are delivered either way (ans:Q7).
        """
        self._check_routable(path)

        def register(handler: EndpointHandler) -> EndpointHandler:
            self._endpoints[path] = handler
            if rds:
                self._rds_endpoints.add(path)
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

    def processor_routes(self) -> list[str]:
        """The registered endpoint paths a `processor=` id may name (§27.3)."""
        return list(self._endpoints)

    def default_route(self) -> str | None:
        """The node's reduce route (:class:`~url4.io.layer.SupportsDefaultRoute`).

        The explicit ``default_processor`` when one was given, else the FIRST
        registered endpoint that is not a code pointer (``rds=True`` never takes
        a prompt reduce); with neither, a fan-out reduce fails with a clear error.
        """
        if self._processor is not None:
            return self._processor
        return next((p for p in self._endpoints if p not in self._rds_endpoints), None)

    def _check_routable(self, path: str) -> None:
        if not path.startswith("/"):
            raise ValueError(f"route path {path!r} must start with '/'")
        if path == self._eval_path:
            raise ValueError(f"{path!r} is the eval path — it is dispatched by the node itself")
        if path in self._endpoints or path in self._data:
            raise ValueError(f"path {path!r} is already registered")

    # --- the IOLayer ports (a node IS an io layer) ----------------------------------
    # Thin delegates: the dispatch order lives in url4.peer._dispatch (the F2
    # split) — one owner, so HTTP (url4.peer._http) and in-process behavior
    # cannot diverge.

    async def fetch(self, target: str, *, relative: bool) -> str:
        return await _dispatch.fetch(self, target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        return await _dispatch.fetch_ex(self, request)

    async def fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        return await _dispatch.fetch_holdings(self, identity, collection)

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

    # --- evaluation -----------------------------------------------------------------

    async def evaluate(
        self, expression: str | Node, *, env: Mapping[str, object] | None = None
    ) -> Url4Result:
        """Evaluate a url4 expression in-process, with this node as its world.

        A tree passed as ``Node`` is rendered with the round-trip re-parse
        skipped (``check=False``, ~15x the render). A tree the grammar cannot
        faithfully carry (spec §8.1.2) is still reported as
        :class:`~url4.core.errors.RenderError` naming the tree — the check runs
        only once the run has already failed, so it costs nothing when the tree
        is sound.
        """
        # WHY check=False: same front-door reasoning as Client.evaluate — the verify
        # re-parse costs ~15x the render, and _blaming_render pays it only on failure.
        if isinstance(expression, str):
            request, rendered = expression, None
        else:
            request, rendered = render(expression, check=False), expression
        text = await _blaming_render(rendered, request, self._run_text(request, env))
        return Url4Result(text=text, request=request)

    def asgi(self):
        """The node as a plain ASGI application (framework-free by construction)."""
        return _asgi_app(self)

    def serve(self, host: str = "127.0.0.1", port: int = 4404, **uvicorn_kwargs) -> None:
        """Serve :meth:`asgi` with uvicorn (requires the ``url4[server]`` extra)."""
        _serve_node(self, host=host, port=port, **uvicorn_kwargs)

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


__all__ = ["DataProvider", "EndpointHandler", "HoldingsHandler", "Request", "Url4Node"]

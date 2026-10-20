"""The in-memory, deterministic :class:`~url4.io.layer.IOLayer` adapter.

No network, fully reproducible — the default for tests. Serves static reads
from ``fetch_map``, localhost ``?q=`` expression endpoints from ``routes``,
``@`` / ``@identity`` references from ``holdings``
(:class:`~url4.io.layer.SupportsHoldings`), and declared media types from
``media_types`` (:class:`~url4.io.layer.SupportsFetchEx`). Depends only on the
sub-request codec and the error hierarchy, never on httpx.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from inspect import isawaitable

from url4.core.code import CodeCall, CodeHandler, invoke_mounted
from url4.core.errors import ErrorCode, ResolutionError
from url4.io._text_guard import require_text
from url4.io.layer import FetchedBytes, FetchRequest, FetchResult
from url4.wire.subrequest import decode_subrequest, extract_expression_params

RouteHandler = Callable[[str, str], str | Awaitable[str]]


class StaticIOLayer:
    """An in-memory :class:`~url4.io.layer.IOLayer` — no network, fully deterministic.

    ``fetch_map`` maps an exact URL/path to its content (a static data read):
    ``str`` for text, or ``bytes`` for a binary-safe source served by
    ``fetch_bytes`` as-is. A ``bytes`` value whose mapped media type is binary is
    refused on the text paths (``unsupported_content_type``), like ``HttpIOLayer``.
    ``routes`` maps a localhost path (e.g. ``/claude``) to a handler
    ``(context, intent) -> str`` (sync or async) — invoked when a relative
    expression is fetched as ``/claude?q=(context)!intent``, simulating a
    localhost url4 node. ``holdings`` maps holdings keys to content — ``""``
    for the node's own default holdings (``@``), ``"coll"`` for ``@`` with a
    collection qualifier, ``"name"`` for ``@name``, ``"name/coll"`` for
    ``@name/coll``; omitting it makes this adapter behave like a non-URL4
    source (spec §5.6.6). ``media_types`` maps a target to the media type
    ``fetch_ex`` reports for it. ``code`` maps a code path or name to a handler: the test
    double for a node's ``@node.code`` mounts. Missing keys raise
    :class:`~url4.core.errors.ResolutionError`.
    """

    def __init__(
        self,
        fetch_map: Mapping[str, str | bytes] | None = None,
        routes: dict[str, RouteHandler] | None = None,
        *,
        holdings: Mapping[str, str] | None = None,
        media_types: Mapping[str, str] | None = None,
        code: Mapping[str, CodeHandler] | None = None,
    ) -> None:
        self._fetch = dict(fetch_map or {})
        self._routes = dict(routes or {})
        self._holdings = dict(holdings) if holdings is not None else None
        self._media_types = dict(media_types or {})
        self._code = dict(code or {})

    async def fetch(self, target: str, *, relative: bool) -> str:
        body = await self._lookup(target)
        if isinstance(body, str):
            return body
        require_text(target, self._media_types.get(target))
        return body.decode("utf-8")

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        body = await self._lookup(request.target)
        raw = body.encode("utf-8") if isinstance(body, str) else body
        return FetchedBytes(raw, media_type=self._media_types.get(request.target))

    async def _lookup(self, target: str) -> str | bytes:
        # Routes accept the full canonical form "/path?[params&]q=…" (spec
        # §3.1.1) — protocol params before q= are tolerated and ignored by
        # this test double; the expression alone reaches the handler.
        path, sep, query = target.partition("?")
        if sep and path in self._routes:
            _params, q = extract_expression_params(query)
            if q is not None:
                context, intent = decode_subrequest(q)
                result = self._routes[path](context, intent)
                return await result if isawaitable(result) else result
        try:
            return self._fetch[target]
        except KeyError:
            raise ResolutionError(f"no fetch mapping for {target!r}") from None

    def processor_routes(self) -> list[str]:
        """The declared route paths a `processor=` id may name (§27.3)."""
        return list(self._routes)

    def default_route(self) -> str | None:
        """The first declared route — the engine's ``processor`` default
        (:class:`~url4.io.layer.SupportsDefaultRoute`); ``None`` without routes."""
        return next(iter(self._routes), None)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        body = await self.fetch(request.target, relative=request.relative)
        return FetchResult(body, media_type=self._media_types.get(request.target))

    async def fetch_holdings(self, identity: str | None, collection: str | None) -> str:
        holdings = self._holdings
        if holdings is None:
            # No holdings configured: this adapter is a non-URL4 source in the
            # spec's sense, and @/@identity on one is a permanent error (§5.6.6).
            raise ResolutionError(
                "this adapter serves no holdings — @/@identity requires a URL4-aware node",
                code=(
                    ErrorCode.SELF_REF_ON_NON_URL4
                    if identity is None
                    else ErrorCode.IDENTITY_REF_ON_NON_URL4
                ),
                permanent=True,
            )
        key = _holdings_key(identity, collection)
        if key in holdings:
            return holdings[key]
        if identity is not None:
            raise ResolutionError(
                f"unknown identity {identity!r}", code=ErrorCode.UNKNOWN_IDENTITY, permanent=True
            )
        raise ResolutionError(f"no self holdings for collection {collection!r}")

    def has_code(self, pointer: str) -> bool:
        """Whether a code handler is mounted at ``pointer`` (exact path or name key)."""
        return pointer in self._code

    async def invoke_code(self, call: CodeCall) -> object:
        """Run the handler mounted at ``call.pointer``; its raw result."""
        return await invoke_mounted(self._code, call)


def _holdings_key(identity: str | None, collection: str | None) -> str:
    # StaticIOLayer keys its composite identity+collection string directly, so a
    # missing shelf is a precise error, not a fallback. `resolve_shelf`
    # (url4.io.layer) is the canonical exact-then-None rule that the node
    # adapters apply; this deterministic test double deliberately does not.
    base = identity or ""
    if collection is None:
        return base
    return f"{base}/{collection}" if base else collection


__all__ = ["RouteHandler", "StaticIOLayer"]

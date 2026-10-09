"""The ``@`` holdings and ``@identity`` registration — the node's own shelves (spec §5.6).

Split out of :mod:`url4.peer.server` when the server module reached its size cap: this module owns
what a node serves as its own holdings — the per-collection ``holdings`` shelves, the ``identity``
principals, and the one-argument port shape both are normalized to. The dispatch that reads these
registries lives in :mod:`url4.peer._dispatch`; this module only registers them.

:class:`_HoldingsRegistration` is a mixin: :class:`~url4.peer.server.Url4Node` inherits it, and
``Url4Node.__init__`` initializes the two registries it writes.

The dependency is one-directional: :mod:`url4.peer.server` imports this module; this module never
imports :mod:`url4.peer.server`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import signature
from typing import overload

from url4.core.grammar import _IDENTITY_NAME_RE

# handlers may take the requested collection or nothing at all
HoldingsHandler = Callable[[str | None], str | Awaitable[str]] | Callable[[], str | Awaitable[str]]
_HoldingsPort = Callable[[str | None], str | Awaitable[str]]


class _HoldingsRegistration:
    """The node's own ``@`` holdings and ``@identity`` registries (spec §5.6).

    A mixin that owns its state: the host's ``__init__`` calls :meth:`_init_holdings` once,
    so every class that mixes it in starts with empty registries.
    """

    _self_holdings: dict[str | None, _HoldingsPort]
    _identities: dict[str, _HoldingsPort]

    def _init_holdings(self) -> None:
        self._self_holdings = {}
        self._identities = {}

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

    def holdings_collections(self) -> frozenset[str | None]:
        """Every registered self-holdings collection; ``None`` is the default shelf."""
        return frozenset(self._self_holdings)

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


# --- module helpers ------------------------------------------------------------------


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

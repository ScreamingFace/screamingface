"""The I/O layer port (framework-free by construction).

Executable nodes never perform I/O themselves. They depend on the
:class:`IOLayer` *port* — a Protocol with a single :meth:`~IOLayer.fetch`
operation — and concrete adapters implement it, the dependency inversion that
keeps the core free of httpx, plugin registries, and frameworks. This module
imports nothing heavier than the standard library, so the DAG core can name the
port without dragging a transport into its import graph.

Everything is a fetch against the current node: a bare relative URI ``/api/x``
is a data read, and a relative *expression* ``/claude(ctx)!intent`` is fetched
as the encoded sub-request ``/claude?q=(ctx)!intent`` (the local node evaluates
it — there is no separate "call" primitive).

Two optional capability protocols widen the port without breaking old adapters:

- :class:`SupportsFetchEx` — :class:`FetchRequest` in, :class:`FetchResult`
  (body + media type) out, so collection parsing can be Content-Type-driven
  (spec §5.3.7) instead of sniffed. :func:`fetch_result` bridges: adapters
  without ``fetch_ex`` are wrapped body-only.
- :class:`SupportsHoldings` — resolves ``@`` / ``@identity`` self- and
  identity-references (spec §5.6) against the node's own data.

The batteries-included adapters live in their own modules so importing the port
never pulls one in:

- :class:`~url4.io.static.StaticIOLayer` — in-memory, no network, deterministic;
  the default for tests.
- :class:`~url4.io.http.HttpIOLayer` — httpx ``GET`` adapter; what
  :func:`~url4.run` uses when no layer is supplied.

Collection parsing — :func:`parse_collection`, the iterable-items decoder the
``*`` iteration and ``;expand`` expansion operators consume — lives in
:mod:`url4.core.collection`; this module re-exports it for its historical
consumers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from url4.core.collection import parse_collection  # re-export; see docstring


@runtime_checkable
class IOLayer(Protocol):
    """The I/O port — a single operation. Adapters implement ``fetch``.

    Everything is a fetch: a bare relative URI ``/api/x`` is a data read on the
    current node, and a relative *expression* ``/claude(ctx)!intent`` is fetched
    as the encoded sub-request ``/claude?q=(ctx)!intent`` (the local node
    evaluates it). There is no separate "call" primitive — dispatching a model
    backend is a localhost fetch, same as any other.
    """

    async def fetch(self, target: str, *, relative: bool) -> str:
        """Resolve a URL (``relative=False``) or ``/path`` (``relative=True``) to content."""
        ...


@dataclass(frozen=True)
class FetchRequest:
    """One resolution request through the port — richer than a bare target.

    ``kind`` records the scheme classification the engine derived (spec §3.5):
    ``url4`` targets expect URL4 protocol semantics from the adapter, ``http``
    is a raw HTTP data read, ``relative`` resolves against the current node,
    and ``other`` is any further scheme (``s3://``, …) the adapter may or may
    not support. ``accept`` carries the per-source ``;accept=`` execution
    annotation (spec §4.2) for adapters that honor it. (``;t=`` is enforced
    engine-side by GuardNode, so it never reaches the port.)
    """

    target: str
    relative: bool = False
    kind: Literal["http", "url4", "relative", "other"] = "http"
    accept: str | None = None


@dataclass(frozen=True)
class FetchResult:
    """A resolved body plus the media type the adapter observed (or ``None``)."""

    body: str
    media_type: str | None = None


@runtime_checkable
class SupportsFetchEx(Protocol):
    """Optional adapter capability: media-type-aware fetching."""

    async def fetch_ex(self, request: FetchRequest) -> FetchResult: ...


@runtime_checkable
class SupportsDefaultRoute(Protocol):
    """Optional adapter capability: the io world's default reduce route.

    An adapter that DECLARES routes (a node's registered endpoints, a static
    layer's ``routes``) reports the first-declared one; the engine uses it as
    the ``processor`` default when none is set explicitly — the core hardcodes
    no route names. Adapters without a registry simply don't implement it, and
    a fan-out reduce then requires an explicit ``processor``.
    """

    def default_route(self) -> str | None: ...


@runtime_checkable
class SupportsProcessorRoutes(Protocol):
    """Optional adapter capability: the processor routes this world declares.

    A `processor=` id (§27.3 Form 1) names one of these. The adapter only
    DECLARES what it has; the matching rule lives in :mod:`url4.dag.processor` so it
    has one definition rather than one per adapter. Adapters with no route
    registry simply don't implement this, and a bare id then cannot resolve.
    """

    def processor_routes(self) -> Sequence[str]: ...


@runtime_checkable
class SupportsHoldings(Protocol):
    """Optional adapter capability: ``@`` / ``@identity`` holdings resolution.

    ``identity`` is ``None`` for the node's own holdings (``@``) or the
    principal's name (``@name``); ``collection`` is the optional
    slash-qualified sub-selection (spec §5.6.2).
    """

    async def fetch_holdings(self, identity: str | None, collection: str | None) -> str: ...


@runtime_checkable
class SupportsClose(Protocol):
    """Optional adapter capability: releasing an owned transport.

    An adapter that owns resources (``HttpIOLayer`` owns its httpx client)
    implements ``aclose`` to release them. The peer lifecycle helper
    (:class:`url4.peer._owned._OwnedIO`) closes only the adapter it created;
    an injected one is the caller's to manage. Adapters with nothing to
    release simply don't implement this.
    """

    async def aclose(self) -> None: ...


async def fetch_result(io: IOLayer, request: FetchRequest) -> FetchResult:
    """Resolve ``request`` via ``fetch_ex`` when the adapter provides it.

    Old-style adapters (bare ``fetch``) are wrapped body-only — ``media_type``
    stays ``None`` so collection parsing falls back to content sniffing.
    """
    if isinstance(io, SupportsFetchEx):
        return await io.fetch_ex(request)
    return FetchResult(await io.fetch(request.target, relative=request.relative))


# --- holdings shelf resolution (spec §5.6) ------------------------------------


def resolve_shelf[T](mapping: Mapping[str | None, T], collection: str | None) -> T | None:
    """Select a holdings shelf from ``mapping`` by the one fallback rule.

    ``collection`` names the requested shelf and its exact key wins. When that
    key is absent (or ``collection`` is ``None``), the ``None``-key shelf is
    the default fallback — the spec §5.6.2 unqualified-holdings entry. An
    exact shelf is selected by presence (``is not None``), so a falsy provider
    (e.g. ``""``) is SERVED rather than skipped — the same rule the data path
    applies to falsy providers. Returns
    ``None`` when neither key is present, leaving absence handling to the
    caller (an error, a non-URL4 source, …). One definition so ``@`` and
    ``@name`` resolve collections identically across adapters and the peer
    node.
    """
    if collection is not None:
        exact = mapping.get(collection)
        if exact is not None:
            return exact
    return mapping.get(None)


__all__ = [
    "FetchRequest",
    "FetchResult",
    "IOLayer",
    "SupportsClose",
    "SupportsDefaultRoute",
    "SupportsFetchEx",
    "SupportsHoldings",
    "SupportsProcessorRoutes",
    "fetch_result",
    "parse_collection",
    "resolve_shelf",
]

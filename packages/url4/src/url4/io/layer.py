"""The I/O layer port + collection parsing (framework-free by construction).

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

:func:`parse_collection` turns fetched text into iterable items for the ``*``
iteration and ``;expand`` expansion operators, by declared media type when the
adapter reports one, by conservative sniffing otherwise.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from url4.core.errors import CollectionError


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


# --- collection parsing (spec §5.3.7) -----------------------------------------


def parse_collection(body: str, media_type: str | None = None) -> list[str]:
    """Parse ``body`` into a list of string items (spec §5.3.7).

    With a declared ``media_type`` the matching strategy is applied strictly
    (an undeclarable body is the source's fault, not the parser's guess);
    without one the type is sniffed conservatively. Structured items (objects,
    CSV rows) are JSON-encoded so downstream callers can ``json.loads``
    individual fields.

    An empty body is an empty collection — iteration over it succeeds with
    zero elements (spec §5.3.9). A value that cannot be parsed into elements
    (a scalar, a JSON object, an HTML page) raises :class:`CollectionError`
    with code ``malformed_source``.
    """
    body = body.strip()
    if not body:
        return []
    if media_type is None:
        return _sniff(body)
    return _parse_declared(body, media_type)


def _parse_declared(body: str, media_type: str) -> list[str]:
    mime = media_type.split(";", 1)[0].strip().lower()
    parser = _DECLARED.get(mime)
    if parser is None:
        raise CollectionError(f"unsupported content type {mime!r} for collection parsing")
    return parser(body)


def _sniff(body: str) -> list[str]:
    """Best-effort typing for adapters that report no media type.

    Order matters: HTML (a soft-404 signature) and JSON objects fail fast;
    then the structured formats; then multi-line plain text degrades to lines.
    A single-line non-JSON-array body is a scalar, not a collection — sniffing
    refuses to iterate it (spec §5.3.9 non-iterable). Single-row NDJSON is
    indistinguishable from a scalar here; declare ``application/x-ndjson`` to
    iterate one.
    """
    if body[:512].lstrip().lower().startswith(("<!doctype html", "<html")):
        raise CollectionError(
            "collection source returned an HTML page, not a data file "
            "(JSON array, JSONL, or CSV expected) — the source is likely missing or misrouted"
        )
    _reject_json_object(body)
    lines = _lines(body)
    for attempt in (_try_json_array, _try_jsonl, _try_csv):
        items = attempt(body, lines)
        if items is not None:
            return items
    if len(lines) > 1:
        return lines
    raise CollectionError(
        f"collection source resolved to a scalar value, not an iterable collection: {body[:80]!r}"
    )


def _reject_json_object(body: str) -> None:
    if not body.startswith("{"):
        return
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return
    if isinstance(data, dict):
        raise CollectionError(
            "iteration over a JSON object is malformed — a collection must be a JSON "
            "array, JSONL, CSV, or line-delimited text (spec §5.3.7)"
        )


def _declared_json(body: str) -> list[str]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CollectionError(f"application/json collection is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise CollectionError(
            "iteration over non-array application/json is malformed "
            f"(got {type(data).__name__}; spec §5.3.7)"
        )
    return [_item_to_str(item) for item in data]


def _declared_ndjson(body: str) -> list[str]:
    items: list[str] = []
    for line in _lines(body):
        try:
            items.append(_item_to_str(json.loads(line)))
        except json.JSONDecodeError as exc:
            raise CollectionError(f"invalid NDJSON line: {line[:80]!r}") from exc
    return items


def _declared_csv(body: str, delimiter: str = ",") -> list[str]:
    # WHY: a declared table is trusted — no header heuristics, rows as JSON objects.
    try:
        rows = list(csv.DictReader(io.StringIO(body), delimiter=delimiter))
    except csv.Error as exc:
        raise CollectionError(f"invalid CSV collection: {exc}") from exc
    return [json.dumps(dict(row)) for row in rows]


def _declared_tsv(body: str) -> list[str]:
    return _declared_csv(body, delimiter="\t")


_DECLARED: dict[str, Callable[[str], list[str]]] = {
    "application/json": _declared_json,
    "application/x-ndjson": _declared_ndjson,
    "text/csv": _declared_csv,
    "text/tab-separated-values": _declared_tsv,
    "text/plain": lambda body: _lines(body),
}


def _lines(body: str) -> list[str]:
    return [line.strip() for line in body.split("\n") if line.strip()]


def _try_json_array(body: str, _lines_unused: list[str]) -> list[str] | None:
    if not body.startswith("["):
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    return [_item_to_str(item) for item in data] if isinstance(data, list) else None


def _try_jsonl(_body: str, lines: list[str]) -> list[str] | None:
    # >=2 lines: a single valid-JSON line is indistinguishable from a scalar
    # value, and a scalar must not silently iterate (spec §5.3.9).
    if len(lines) < 2:
        return None
    items: list[str] = []
    for line in lines:
        try:
            items.append(_item_to_str(json.loads(line)))
        except json.JSONDecodeError:
            return None
    return items


def _try_csv(body: str, lines: list[str]) -> list[str] | None:
    # Only accept a genuine rectangular table: a comma-bearing header with >=2
    # columns and every data row matching it exactly. Ragged prose that merely
    # contains commas (e.g. "What is 2, 3?\nName a color, please") is rejected and
    # falls through to the plain-lines fallback rather than being mangled.
    if len(lines) < 2 or "," not in lines[0] or not _looks_like_header(lines[0]):
        return None
    try:
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
    except csv.Error:
        return None
    fieldnames = reader.fieldnames or []
    # A real table: >=2 columns and every row rectangular (no missing/extra cells,
    # which DictReader signals via a None value or a None key).
    rectangular = len(fieldnames) >= 2 and all(
        None not in row and None not in row.values() for row in rows
    )
    return [json.dumps(dict(row)) for row in rows] if rows and rectangular else None


def _looks_like_header(line: str) -> bool:
    """True when ``line`` reads like column names, not comma-bearing prose.

    Even column counts alone don't separate a real 2-column table from two lines
    of prose that each happen to contain one comma (``What is your name, please?``
    → columns ``["What is your name", " please?"]``, which passes a naive
    rectangular check). Column *names* are short labels: non-empty and single
    token. A field carrying interior spaces or sentence punctuation marks the
    "header" as prose, so the collection falls through to the plain-lines
    fallback. Trade-off: a genuine table with multi-word headers
    (``first name,last name``) degrades to plain lines rather than being parsed —
    acceptable, since silent prose-mangling is the worse failure.
    """
    fields = [f.strip() for f in line.split(",")]
    return all(f and " " not in f and f[-1] not in "?!." for f in fields)


def _item_to_str(item: object) -> str:
    return item if isinstance(item, str) else json.dumps(item)


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

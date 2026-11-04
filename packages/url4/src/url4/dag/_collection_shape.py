"""What an iteration's collection IS before any model runs: one resolver for scan and admission.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 2,
owner decision Sergey 2026-11-04).
STORY: as an ensemble author, a picture under ``$xs.rows*(…)`` or ``$zs*(…)`` (``zs=$ys``,
``ys=$xs``) is refused ``x.source_not_static`` when ``xs`` is a model's output, however many
aliases and field paths sit between them; and a picture under a model-free collection is fetched
only when that collection has rows.

INVARIANT: :func:`resolve_collection` is the only place that decides a collection's shape —
:func:`url4.dag._materialize.check_static` (no I/O) and admission's reachability both read it, so
they cannot disagree. It follows every ``$name`` hop through the enclosing bindings (cycle-safe:
a name seen twice is :data:`UNKNOWN`), keeping each hop's field path, and classifies the value it
lands on. A model anywhere on the chain makes the whole collection :data:`MODEL`.
INVARIANT (mirror execution, ``_lowering._lower_collection`` / ``_bound_blob``): a collection
reached through ``$name`` is that binding's TEXT with each hop's path applied, innermost hop
first, parsed with no media type (a ``TextNode`` payload); only a DIRECT, unpathed ``$x`` whose
binding value is a blob ref reads the blob's body (plan §2.9) — through an alias, a blob binding
is its ref text (F2).
AIDEV-NOTE: imports only ``core``; :mod:`url4.dag.source_scan` and :mod:`url4.dag._materialize`
both import it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from url4.core.blob_ref import address_of
from url4.core.nodes import (
    Expression,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    Source,
    Text,
    Url,
    VarRef,
)

MODEL = "model"  # a model's (or another node's) output: unknown until after a model call
UNKNOWN = "unknown"  # cannot be resolved before the body runs: conservatively reachable
INLINE = "inline"  # an inline ``(a, b)`` collection: its rows are its elements
TEXT = "text"  # literal text (a quoted value, or a blob binding's ref text through an alias)
FETCH = "fetch"  # a literal ``http(s)://`` or relative source: fetched under its own policy
BLOB = "blob"  # a verified blob ref's body (the run-start cache)


@dataclass(frozen=True)
class CollectionShape:
    """A collection's shape and how to read it before any model call.

    ``value`` is the node the chain lands on (descriptors unwrapped); ``descriptor`` its own
    outermost descriptor (the fetch's guard policy and ``;accept=``); ``text`` the literal body
    for :data:`TEXT`; ``paths`` each ``$name`` hop's field path, innermost first; ``via_ref``
    whether the collection is read as a binding's text (no media type).
    """

    kind: str
    value: Node
    descriptor: Source | None = None
    text: str | None = None
    paths: tuple[str, ...] = ()
    via_ref: bool = False


def resolve_collection(items: Node, bound: Mapping[str, Node]) -> CollectionShape:
    """Follow ``items`` through ``bound`` to the value it reads, and classify it."""
    paths: list[str] = []
    seen: set[str] = set()
    node, descriptor, raw = items, None, items
    while True:
        if isinstance(node, Source):
            descriptor = descriptor or node
            node = node.value
            continue
        if not isinstance(node, VarRef):
            break
        if node.name not in bound or node.name in seen:
            return CollectionShape(UNKNOWN, node)  # a row reference, holdings, or a cycle
        seen.add(node.name)
        paths.append(_path_text(node.path))
        node = raw = bound[node.name]
        descriptor = None  # the next binding's own descriptor governs its fetch
    hops = tuple(reversed(paths))
    return _classify(node, descriptor, raw, hops)


def _classify(
    node: Node, descriptor: Source | None, raw: Node, paths: tuple[str, ...]
) -> CollectionShape:
    via_ref = bool(paths)
    kind = _kind(node)
    address = address_of(node)
    if kind == MODEL:
        shape = CollectionShape(MODEL, node)
    elif address is not None:
        # WHY: execution reads a blob body only directly or via ONE unpathed binding whose value
        # IS the ref (``_bound_blob``); any other route reads the ref text (F2).
        direct = not via_ref or (paths == ("",) and raw is node)
        shape = (
            CollectionShape(BLOB, node, descriptor)
            if direct
            else CollectionShape(TEXT, node, text=address.ref, paths=paths, via_ref=True)
        )
    elif kind == INLINE and via_ref:
        shape = CollectionShape(UNKNOWN, node)  # a bound group's text is only known when run
    else:
        text = node.value if isinstance(node, Text) else None
        shape = CollectionShape(kind, node, descriptor, text, paths, via_ref)
    return shape


def _kind(node: Node) -> str:
    """The value's own kind (see :data:`MODEL` and the other kinds)."""
    kind = UNKNOWN
    if isinstance(node, Expression):
        kind = INLINE if node.intent is None and not node.broadcast else MODEL
    elif isinstance(node, (RelExpr, RemoteExpr, Iteration)):
        kind = MODEL
    elif isinstance(node, Url) and node.value.startswith(("http://", "https://")):
        kind = FETCH
    elif isinstance(node, RelUrl) and "$" not in node.value:
        kind = FETCH
    elif isinstance(node, Text):
        kind = TEXT
    return kind


def _path_text(path: tuple[str | int, ...]) -> str:
    """A VarRef path as ``resolve_field_path`` reads it (``.rows[0]``), as ``_render_ref`` does."""
    return "".join(f"[{s}]" if isinstance(s, int) else f".{s}" for s in path)


__all__ = [
    "BLOB",
    "FETCH",
    "INLINE",
    "MODEL",
    "TEXT",
    "UNKNOWN",
    "CollectionShape",
    "resolve_collection",
]

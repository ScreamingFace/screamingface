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

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

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
from url4.dag._scan_scope import definition_of, hidden_in

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
    cycle: bool = False  # a ``$name`` chain that loops: execution raises, no body ever runs


# ``$$`` is a literal ``$``; ``$N`` a position (the interpolation scanner's head, ensemble.py).
_TEMPLATE_REF = re.compile(r"\$\$|\$([A-Za-z_]\w*|[0-9]+)", re.ASCII)


def resolve_collection(items: Node, bound: Mapping[str, Node]) -> CollectionShape:
    """Follow ``items`` through ``bound`` to the value it reads, and classify it."""
    chain = _follow_aliases(items, bound)
    if isinstance(chain, CollectionShape):
        return chain
    node = chain.node
    if _TemplateWalk(chain.bound, chain.seen).model_derived(node):
        return CollectionShape(MODEL, node)
    # WHY: execution reads a bound blob's body only through ``bind:<name>``
    # (``_lowering._bound_blob``); a ``$N`` position reads the ref text.
    by_name = not (chain.names and chain.names[0].isdigit())
    hops = tuple(reversed(chain.paths))
    return _classify(node, chain.descriptor, chain.raw, hops, by_name=by_name)


@dataclass
class _Chain:
    """Where a ``$name`` alias chain lands: the value, its scope, and each hop's name and path."""

    node: Node
    raw: Node
    bound: Mapping[str, Node]
    descriptor: Source | None = None
    seen: set[int] = field(default_factory=set)  # binding VALUES by identity (names may shadow)
    names: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


def _follow_aliases(items: Node, bound: Mapping[str, Node]) -> _Chain | CollectionShape:
    """The alias chain's landing value, or the shape that ends it early."""
    chain = _Chain(items, items, bound)
    node: Node = items
    while isinstance(node, (Source, VarRef)):
        if isinstance(node, Source):
            chain.descriptor = chain.descriptor or node
            node = node.value
            continue
        if node.name not in chain.bound:
            return _unbound(node, chain)
        value = chain.bound[node.name]
        if id(value) in chain.seen:
            # INVARIANT (review round 10, owner 2026-11-05): a binding cycle never yields rows
            # (execution raises), so admission treats its body as unreachable — no fetch.
            return CollectionShape(UNKNOWN, node, cycle=True)
        chain.seen.add(id(value))
        chain.names.append(node.name)
        chain.paths.append(_path_text(node.path))
        # INVARIANT (round 11, finding 3): the value resolves where it was DEFINED.
        chain.bound = definition_of(chain.bound, node.name)
        node = chain.raw = value
        chain.descriptor = None  # the next binding's own descriptor governs its fetch
    chain.node = node
    return chain


def _unbound(node: VarRef, chain: _Chain) -> CollectionShape:
    """A ``$name`` not in scope: a hidden later sibling reads as its literal text (execution
    never binds it; a binding's text, no media type); anything else (a row reference, holdings)
    is :data:`UNKNOWN`."""
    if not hidden_in(chain.bound, node.name):
        return CollectionShape(UNKNOWN, node)
    text = f"${node.name}{_path_text(node.path)}"
    paths = tuple(reversed(chain.paths))
    return CollectionShape(TEXT, node, text=text, paths=paths, via_ref=True)


MAX_TEMPLATE_STEPS = 4096  # names one collection's templates may follow before failing closed


class _StepsExhausted(Exception):
    """The template walk ran out of steps: classified model-derived (fail closed)."""


class _TemplateWalk:
    """Whether a templated relative URL (``/rows/$xs``) substitutes a model's output.

    INVARIANT (PR #1587 review round 10, owner 2026-11-05): the URL a templated collection
    fetches is only known once its ``$name`` values are, so a template over a model-derived
    binding is itself model-derived — ``x.source_not_static`` with zero I/O, never conservatively
    reachable. A row reference, holdings, or a model-free value leaves it :data:`UNKNOWN`.
    INVARIANT (security review of round 10, algorithmic-complexity DoS): ONE visited set is
    shared by the whole walk, so every binding is followed at most once — linear in the bindings
    and template text, however the aliases fan out or refer back. WHY that is sound: the walk
    stops at the first model, so a visited name is either still being explored or known
    model-free. A walk past :data:`MAX_TEMPLATE_STEPS` names fails closed as model-derived.
    """

    def __init__(self, bound: Mapping[str, Node], chain: set[int]) -> None:
        self._bound = bound
        # Binding VALUES by identity: the alias chain already walked counts as visited. WHY not
        # names: a nested group's ``xs`` may shadow an outer ``xs`` (round 11).
        self._visited = set(chain)
        self._steps = 0

    def model_derived(self, node: Node) -> bool:
        try:
            return self._walk(node)
        except _StepsExhausted:
            return True

    def _walk(self, node: Node) -> bool:
        pending: list[tuple[Node, Mapping[str, Node]]] = [(node, self._bound)]
        while pending:
            template, scope = pending.pop()
            for name in _template_names(template):
                target = self._follow(name, scope)
                if target is not None and _kind(target[0]) == MODEL:
                    return True
                if target is not None:
                    pending.append(target)
        return False

    def _follow(
        self, name: str, scope: Mapping[str, Node]
    ) -> tuple[Node, Mapping[str, Node]] | None:
        """``name``'s value and its definition scope through its alias hops; ``None`` when
        unbound (a hidden later sibling included: execution substitutes it verbatim) or
        already visited."""
        node: Node = VarRef(name)
        while True:
            if isinstance(node, Source):
                node = node.value
                continue
            if not isinstance(node, VarRef):
                return node, scope
            if node.name not in scope:
                return None
            value = scope[node.name]
            if id(value) in self._visited:
                return None
            self._steps += 1
            if self._steps > MAX_TEMPLATE_STEPS:
                raise _StepsExhausted
            self._visited.add(id(value))
            scope = definition_of(scope, node.name)
            node = value


def _template_names(node: Node) -> list[str]:
    if not isinstance(node, RelUrl) or "$" not in node.value:
        return []
    return [m.group(1) for m in _TEMPLATE_REF.finditer(node.value) if m.group(1) is not None]


def _classify(
    node: Node, descriptor: Source | None, raw: Node, paths: tuple[str, ...], *, by_name: bool
) -> CollectionShape:
    via_ref = bool(paths)
    kind = _kind(node)
    address = address_of(node)
    if kind == MODEL:
        shape = CollectionShape(MODEL, node)
    elif address is not None:
        # WHY: execution reads a blob body only directly or via ONE unpathed binding whose value
        # IS the ref (``_bound_blob``); any other route reads the ref text (F2).
        direct = not via_ref or (by_name and paths == ("",) and raw is node)
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
    "MAX_TEMPLATE_STEPS",
    "CollectionShape",
    "resolve_collection",
]

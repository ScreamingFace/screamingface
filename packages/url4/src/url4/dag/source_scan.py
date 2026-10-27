"""The run's source scan: which file refs and attachment sources its AST names, in preorder.

Split from :mod:`url4.dag.attachments` (size) by reason to change: this module changes when the
AST walk changes (what counts as a file ref, a slot, an attachment-source occurrence, a
collection guard); ``attachments`` changes when the run's bound side-channel changes.
``url4.dag.attachments`` re-exports every public name here, so no import path moves.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F2, F1b round 7).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from url4.core.blob_ref import BlobAddress, address_of
from url4.core.errors import ErrorCode, ParseError, ResolutionError
from url4.core.grammar import parse as grammar_parse
from url4.core.nodes import (
    Binding,
    Expression,
    Iteration,
    Node,
    RelExpr,
    Source,
    Url,
    VarRef,
)
from url4.core.parser import split_top_level_commas
from url4.dag.attachment_sources import AttachmentIdentity, identity_of

_WEB_SCHEMES = ("http://", "https://")


# --- collection: which file refs the run's AST names, in source order -------------------


@dataclass(frozen=True)
class FileRef:
    """One file ref the run names. ``collection`` is True when EVERY use of it is in
    collection position (D4): then it is verified and cached, but not attached."""

    address: BlobAddress
    collection: bool = False

    @property
    def key(self) -> str:
        """The cache / dedup key: ``sha256:<hex>``, or the ref text when it has no digest."""
        digest = self.address.digest
        return self.address.ref if digest is None else f"sha256:{digest}"


def collect_file_refs(ast: Node) -> tuple[FileRef, ...]:
    """Every file ref ``ast`` names, in source pre-order, deduped by digest (first wins).

    INVARIANT (F2): structure only — value nodes the grammar parsed as file refs. Quoted text
    is :class:`~url4.core.nodes.Text` and never a ref (C4); a ``RemoteExpr`` subtree is the
    remote node's own business and is skipped (C6). A call's context and an iteration body
    are source-lists kept as raw text by the parser: each segment is parsed here the same way
    the lowering parses it; a segment that does not parse (prose, or a template that only
    parses after row substitution) contributes nothing.
    """
    return scan_sources(ast).refs


@dataclass(frozen=True, eq=False)
class CollectionGuard:
    """An iteration's collection, which a body's attachment sources are conditional on.

    ``bound`` is the enclosing scope (so ``$xs*(…)`` reaches its binding); ``slice`` is the
    iteration's ``;iteration.slice``. Reachability (F1b round 7): a body is reachable only when
    its collection yields at least one row after slicing.
    """

    items: Node
    bound: Mapping[str, Node]
    slice: tuple[int | None, int | None] | None = None


Occurrence = tuple[AttachmentIdentity, tuple[CollectionGuard, ...]]
"""One attachment-source occurrence in preorder, with the collections it is conditional on."""


@dataclass(frozen=True)
class OccurrenceSlot:
    """A slot-order marker for ``occurrences[index]`` (F1b round 7).

    WHY a per-occurrence marker, not the identity: an identity's one slot sits at its first
    REACHABLE occurrence in manifest preorder, and reachability is only known after admission
    (:func:`reachable_order` resolves the markers then).
    """

    index: int


@dataclass(frozen=True)
class SourceScan:
    """The run's file refs, and the source-order keys of its attachment slots.

    ``order`` holds, at first sight in pre-order, an attachable file ref's :attr:`FileRef.key`,
    the URL of every ``http(s)://`` text source read in scalar position (Q-B: such a source
    attaches only if its body turns out not to be text; collection position never attaches),
    and an :class:`OccurrenceSlot` for EVERY attachment-source occurrence (F1b round 7).
    ``occurrences`` lists every attachment-source occurrence in preorder with its guards.
    """

    refs: tuple[FileRef, ...]
    order: tuple[str | OccurrenceSlot, ...]
    occurrences: tuple[Occurrence, ...] = ()


@dataclass
class _Found:
    refs: dict[str, FileRef] = field(default_factory=dict)
    order: dict[str | OccurrenceSlot, None] = field(default_factory=dict)  # an ordered set
    urls: set[str] = field(default_factory=set)
    occurrences: list[Occurrence] = field(default_factory=list)


_Guards = tuple[CollectionGuard, ...]


def scan_sources(ast: Node) -> SourceScan:
    """One structural walk (see :func:`collect_file_refs`) yielding refs and slot order."""
    found = _Found()
    _walk(ast, {}, False, found, ())
    refs = tuple(found.refs.values())
    attached = {ref.key for ref in refs if not ref.collection}
    order = tuple(
        key
        for key in found.order
        if isinstance(key, OccurrenceSlot) or key in attached or key in found.urls
    )
    return SourceScan(refs, order, tuple(found.occurrences))


def _walk(
    node: Node, bound: Mapping[str, Node], collection: bool, out: _Found, guards: _Guards
) -> None:
    if _add_leaf(node, collection, out):
        return
    match node:
        case Expression():
            _walk_expression(node, bound, out, guards)
        case Binding(value=value):
            _walk(value, bound, collection, out, guards)
        case Source():
            _walk_source(node, bound, collection, out, guards)
        case Iteration():
            _walk_iteration(node, bound, out, guards)
        case RelExpr():
            _walk_rel_expr(node, bound, out, guards)
        case _:
            pass  # Text, RemoteExpr (C6), holdings, VarRef in scalar use, struct, ...


def _walk_source(
    node: Source, bound: Mapping[str, Node], collection: bool, out: _Found, guards: _Guards
) -> None:
    in_collection = collection or node.expand
    if not in_collection and _add_attachment(node, out, guards):
        return
    _walk(node.value, bound, in_collection, out, guards)


def _walk_iteration(
    node: Iteration, bound: Mapping[str, Node], out: _Found, guards: _Guards
) -> None:
    _walk_collection(node.collection, bound, out, guards)
    items = node.collection
    if isinstance(items, VarRef) and not items.path and items.name in bound:
        items = bound[items.name]  # ``$xs*(…)`` reads its enclosing binding's value
    guard = CollectionGuard(items, bound, node.directives.slice)
    _walk_source_list(node.body, bound, out, (*guards, guard))


def _add_attachment(node: Source, out: _Found, guards: _Guards) -> bool:
    """Record an attachment source (F1b round 7); ``False`` for every text source."""
    identity = identity_of(node)
    if identity is None:
        return False
    out.order.setdefault(OccurrenceSlot(len(out.occurrences)))
    out.occurrences.append((identity, guards))
    return True


def reachable_order(
    order: Sequence[str | OccurrenceSlot],
    occurrences: Sequence[Occurrence],
    first_reachable: frozenset[int],
) -> tuple[str | AttachmentIdentity, ...]:
    """The slot order once reachability is known: each identity at its first reachable occurrence.

    INVARIANT (F1b round 7): one attachment per identity, at that identity's first occurrence
    in MANIFEST preorder — the manifest holds only reachable occurrences, so an unreachable
    occurrence takes no slot; blob-ref and Q-B URL slots keep their source-order positions.
    """
    placed: list[str | AttachmentIdentity] = []
    for key in order:
        if not isinstance(key, OccurrenceSlot):
            placed.append(key)
        elif key.index in first_reachable:
            placed.append(occurrences[key.index][0])
    return tuple(placed)


def _walk_expression(
    node: Expression, bound: Mapping[str, Node], out: _Found, guards: _Guards
) -> None:
    scope = dict(bound) | _bindings(node.sources)
    for source in node.sources:
        _walk(source, scope, False, out, guards)
    if node.intent is not None:
        _walk(node.intent, scope, False, out, guards)


def _walk_rel_expr(node: RelExpr, bound: Mapping[str, Node], out: _Found, guards: _Guards) -> None:
    # INVARIANT: a context holding a holdings ref ("@") ships verbatim to the receiving
    # route and is never resolved caller-side (mirrors the lowering's _context_slots).
    if node.context is not None and "@" not in node.context:
        _walk_source_list(node.context, bound, out, guards)
    if node.intent is not None:
        _walk(node.intent, bound, False, out, guards)


def _walk_collection(items: Node, bound: Mapping[str, Node], out: _Found, guards: _Guards) -> None:
    if isinstance(items, Expression) and items.intent is None and not items.broadcast:
        _walk(items, bound, False, out, guards)  # an inline collection: its elements are values
        return
    if isinstance(items, VarRef) and not items.path and items.name in bound:
        # Plan §2.9: ``$x*(…)`` reads the bound file ref in collection position.
        items = bound[items.name]
    _walk(items, bound, True, out, guards)


def _walk_source_list(text: str, bound: Mapping[str, Node], out: _Found, guards: _Guards) -> None:
    for segment in split_top_level_commas(text):
        if not segment.strip():
            continue
        try:
            parsed = grammar_parse(segment.strip())
        except ParseError:
            continue
        _walk(parsed, bound, False, out, guards)


def _bindings(sources: tuple[Node, ...]) -> dict[str, Node]:
    named: dict[str, Node] = {}
    for source in sources:
        if isinstance(source, Binding):
            named[source.name] = source.value
        elif isinstance(source, Source) and source.name is not None:
            # WHY the descriptor, not its value: ``$xs*(…)`` admission needs the binding's
            # ``;retry=`` / ``;t=`` / ``;optional`` / ``;accept=`` (``_materialize._unwrap``).
            named[source.name] = source
    return named


def _add_leaf(node: Node, collection: bool, out: _Found) -> bool:
    """Record a file ref or an absolute URL; ``True`` when ``node`` was one (a leaf).

    An ``http(s)://`` source in scalar position takes a slot (Q-B); any other URL takes none.
    """
    address = address_of(node)
    if address is not None:
        _add(out, FileRef(address, collection))
        return True
    if not isinstance(node, Url):
        return False
    if not collection and node.value.startswith(_WEB_SCHEMES):
        out.order.setdefault(node.value)
        out.urls.add(node.value)
    return True


def _add(out: _Found, ref: FileRef) -> None:
    if not ref.collection:
        out.order.setdefault(ref.key)
    seen = out.refs.get(ref.key)
    if seen is None:
        out.refs[ref.key] = ref
    elif seen.collection and not ref.collection:
        out.refs[ref.key] = FileRef(seen.address, False)  # first scalar position, now attached


def refuse_remote(refs: Sequence[FileRef]) -> None:
    """D1 / F1: any ``url4://`` blob ref fails the run before ANY I/O, local refs included."""
    for ref in refs:
        if ref.address.form == "remote":
            raise ResolutionError(
                f"remote blob refs are not supported in v1 ({ref.address.ref!r})",
                code=ErrorCode.REMOTE_BLOB_UNSUPPORTED,
                permanent=True,
            )


__all__ = [
    "CollectionGuard",
    "FileRef",
    "Occurrence",
    "OccurrenceSlot",
    "SourceScan",
    "collect_file_refs",
    "reachable_order",
    "refuse_remote",
    "scan_sources",
]

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
    IdentityRef,
    Iteration,
    Node,
    RelExpr,
    RemoteExpr,
    SelfRef,
    Source,
    Url,
    VarRef,
    walk,
)
from url4.core.parser import split_top_level_commas
from url4.dag._scan_scope import sibling_scopes
from url4.dag.attachment_sources import AttachmentIdentity, identity_of, non_literal_attachment

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

    ``order`` holds, at first sight in pre-order, an attachable file ref's :attr:`FileRef.key`
    and an :class:`OccurrenceSlot` for EVERY attachment-source occurrence (F1b round 7). A text
    source takes no slot: it is never attached (owner decision A, 2026-10-27).
    ``occurrences`` lists every attachment-source occurrence in preorder with its guards.
    """

    refs: tuple[FileRef, ...]
    order: tuple[str | OccurrenceSlot, ...]
    occurrences: tuple[Occurrence, ...] = ()
    non_literal: tuple[str, ...] = ()  # owner decision C: refused, x.source_not_static
    malformed: tuple[str, ...] = ()  # owner 2026-11-02: refused, malformed_source
    # PR #1587 review finding 4: every url4:// remote-node call, (authority, path), in preorder.
    remote_nodes: tuple[tuple[str, str], ...] = ()
    # PR #1750 rounds 5/6: iteration-body and call-context segments the strict grammar rejected
    # (they may still compile); the remote precheck walks the compiled graph instead of this scan.
    opaque: tuple[str, ...] = ()


@dataclass
class _Found:
    refs: dict[str, FileRef] = field(default_factory=dict)
    order: dict[str | OccurrenceSlot, None] = field(default_factory=dict)  # an ordered set
    occurrences: list[Occurrence] = field(default_factory=list)
    non_literal: list[str] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)
    remote_nodes: list[tuple[str, str]] = field(default_factory=list)
    opaque: list[str] = field(default_factory=list)


_Guards = tuple[CollectionGuard, ...]


def scan_sources(ast: Node) -> SourceScan:
    """One structural walk (see :func:`collect_file_refs`) yielding refs and slot order."""
    found = _Found()
    _walk(ast, {}, False, found, ())
    refs = tuple(found.refs.values())
    attached = {ref.key for ref in refs if not ref.collection}
    order = tuple(key for key in found.order if isinstance(key, OccurrenceSlot) or key in attached)
    return SourceScan(
        refs,
        order,
        tuple(found.occurrences),
        tuple(found.non_literal),
        tuple(found.malformed),
        tuple(found.remote_nodes),
        tuple(found.opaque),
    )


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
        case RelExpr() | RemoteExpr():
            _walk_call(node, bound, out, guards)
        case _:
            pass  # Text, holdings, VarRef in scalar use, struct, ...


def _walk_source(
    node: Source, bound: Mapping[str, Node], collection: bool, out: _Found, guards: _Guards
) -> None:
    in_collection = collection or node.expand
    if not in_collection and _add_attachment(node, out, guards):
        return
    target = None if in_collection else non_literal_attachment(node)
    if target is not None:
        out.non_literal.append(target)
    _walk(node.value, bound, in_collection, out, guards)


def _walk_iteration(
    node: Iteration, bound: Mapping[str, Node], out: _Found, guards: _Guards
) -> None:
    _walk_collection(node.collection, bound, out, guards)
    # WHY the raw collection: its shape is decided ONLY by ``_collection_shape`` (finding 2),
    # which follows every ``$name`` hop and path; admission and the static check read it.
    guard = CollectionGuard(node.collection, bound, node.directives.slice)
    out.opaque.extend(_walk_source_list(node.body, bound, out, (*guards, guard), positional=True))


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
    occurrence takes no slot; blob-ref slots keep their source-order positions.
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
    # INVARIANT (round 11, findings 2 and 3): each source walks in the scope execution wires
    # for it (``_scan_scope``) — positions included, later siblings hidden from a named one.
    scopes, full = sibling_scopes(node.sources, bound, positional=True)
    for source, scope in zip(node.sources, scopes, strict=True):
        _walk(source, scope, False, out, guards)
    if node.intent is not None:
        _walk(node.intent, full, False, out, guards)


def _walk_call(
    node: RelExpr | RemoteExpr, bound: Mapping[str, Node], out: _Found, guards: _Guards
) -> None:
    if isinstance(node, RelExpr):
        _walk_rel_expr(node, bound, out, guards)
    else:
        # C6: a remote call's context is the remote node's business (never walked); the CALL
        # itself is recorded so a node context refuses it before any run-start I/O (finding 4).
        out.remote_nodes.append((node.authority, node.path))


def _walk_rel_expr(node: RelExpr, bound: Mapping[str, Node], out: _Found, guards: _Guards) -> None:
    # INVARIANT (spec §5.6.3.1/.2): a context holding a holdings ref ships verbatim to the
    # receiving route and is never resolved caller-side. Decided on the PARSED segments (F3):
    # an "@" inside a URL or quoted text is not a holdings ref and must not turn the
    # context's opted-in attachment sources into text.
    if node.context is not None and not holds_holdings_ref(node.context):
        asked = len(out.occurrences) + len(out.non_literal)
        # WHY no positions: a context registers none (``_lowering._build_ctx_nodes``).
        skipped = _walk_source_list(node.context, bound, out, guards, positional=False)
        opted_in = len(out.occurrences) + len(out.non_literal) > asked
        out.malformed.extend(s for s in skipped if opted_in or _looks_like_descriptor(s))
        # WHY (PR #1750 round 6): the lowering may defer such a segment into a caller-side group
        # that runs HERE (``_lowering._slot_from_text``), so the remote precheck must not trust
        # this scan for it.
        out.opaque.extend(skipped)
    if node.intent is not None:
        _walk(node.intent, bound, False, out, guards)


def holds_holdings_ref(text: str) -> bool:
    """``True`` when the source-list ``text`` names ``@`` / ``@identity`` anywhere in its AST.

    Nested call contexts and iteration bodies are source-lists kept as raw text by the parser,
    so they are checked the same way. WHY a segment that does not parse counts when it holds
    an ``@``: its meaning is unknown, and the receiving route may read it as a holdings ref —
    the conservative reading the substring test gave every context before F3.
    """
    for segment in split_top_level_commas(text):
        try:
            parsed = grammar_parse(segment.strip()) if segment.strip() else None
        except ParseError:
            if "@" in segment:
                return True
            continue
        if parsed is not None and any(_names_holdings(node) for node in walk(parsed)):
            return True
    return False


def _names_holdings(node: Node) -> bool:
    match node:
        case SelfRef() | IdentityRef():
            named = True
        case (
            RelExpr(context=str() as text)
            | RemoteExpr(context=str() as text)
            | Iteration(body=text)
        ):
            named = holds_holdings_ref(text)
        case _:
            named = False
    return named


def _walk_collection(items: Node, bound: Mapping[str, Node], out: _Found, guards: _Guards) -> None:
    if isinstance(items, Expression) and items.intent is None and not items.broadcast:
        _walk(items, bound, False, out, guards)  # an inline collection: its elements are values
        return
    if isinstance(items, VarRef) and not items.path and _by_name(items.name, bound):
        # Plan §2.9: ``$x*(…)`` reads the bound file ref in collection position (by NAME only:
        # execution's ``_bound_blob`` reads ``bind:<name>``; a ``$N`` position reads ref text).
        items = bound[items.name]
    _walk(items, bound, True, out, guards)


def _by_name(name: str, bound: Mapping[str, Node]) -> bool:
    return not name.isdigit() and name in bound


def _looks_like_descriptor(segment: str) -> bool:
    return "src=" in segment or ";accept=" in segment


def refuse_malformed(scan: SourceScan) -> None:
    """Owner decision 2026-11-02 ("raise only with an opt-in"): refuse before ANY I/O.

    INVARIANT: a file the caller asked for is never silently dropped. An unparseable segment
    of a call context is recorded (:func:`_walk_rel_expr`) only when the same context carries
    an attachment opt-in, or the segment itself looks like a descriptor (``src=`` /
    ``;accept=``); prose alone stays prose. Permanent ``malformed_source`` — the code a bad
    descriptor already raises (``attachment_sources.guard_policy``).
    """
    if scan.malformed:
        raise ParseError(
            f"call-context segment {scan.malformed[0]!r} does not parse beside an attachment "
            "source (or looks like one); a requested file is never dropped silently",
            code=ErrorCode.MALFORMED_SOURCE,
            permanent=True,
        )


def scan_source_list(text: str) -> SourceScan:
    """The scan of a raw source-list (an iteration body template); unparseable segments skipped.

    WHY public: a pre-built graph keeps iteration bodies as text (``MapNode.body``), so the
    run-start graph check (:mod:`url4.dag._graph_admission`) scans them the same way the AST
    walk scans an iteration body.
    """
    found = _Found()
    found.opaque.extend(_walk_source_list(text, {}, found, (), positional=True))
    return SourceScan(
        tuple(found.refs.values()),
        (),
        tuple(found.occurrences),
        tuple(found.non_literal),
        (),
        tuple(found.remote_nodes),
        tuple(found.opaque),
    )


def _walk_source_list(
    text: str, bound: Mapping[str, Node], out: _Found, guards: _Guards, *, positional: bool
) -> list[str]:
    """Walk each parsed segment; return the stripped segments that did not parse.

    WHY returned, not refused here: only a call context may refuse them (an iteration body is
    a template that may parse only after row substitution), and only on an opt-in.
    """
    skipped: list[str] = []
    parsed: list[Node | None] = []
    for segment in split_top_level_commas(text):
        if not segment.strip():
            continue
        try:
            parsed.append(grammar_parse(segment.strip()))
        except ParseError:
            skipped.append(segment.strip())
            parsed.append(None)  # keeps its position (``$N``), binds nothing
    scopes, _ = sibling_scopes(parsed, bound, positional=positional)
    for node, scope in zip(parsed, scopes, strict=True):
        if node is not None:
            _walk(node, scope, False, out, guards)
    return skipped


def _add_leaf(node: Node, collection: bool, out: _Found) -> bool:
    """Record a file ref; ``True`` when ``node`` was a file ref or another absolute URL (a leaf).

    INVARIANT (owner decision A, 2026-10-27): a plain URL — a text source — takes no slot.
    """
    address = address_of(node)
    if address is not None:
        _add(out, FileRef(address, collection))
        return True
    return isinstance(node, Url)


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
    "refuse_malformed",
    "refuse_remote",
    "scan_source_list",
    "scan_sources",
]

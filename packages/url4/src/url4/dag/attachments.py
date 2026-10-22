"""The run's ordered ``attachments[]`` side-channel and its per-run file cache.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 spec §2 F2,
plan ``docs/plan/2026-10-21-OME-1543-file-refs-carry-plan.md`` §2.2–2.4, §2.8).
STORY: as an ensemble author I name a file once and every model call the run makes —
members, reducer, map rows, guard retries — receives the same ordered attachments.

INVARIANT (F2 / D2): the list is fixed when ``run()`` starts (Case attachments first, then
the AST's file refs) and is an immutable tuple; nodes read it, never add, drop or reorder.
INVARIANT: a nested ``run()`` inherits the bound list verbatim; binding a different one is a
programming error (``ValueError``).

WHY a ``ContextVar``: spawned fragments, map rows and guard retries run in tasks created from
the run's task, so the binding reaches all of them; an HTTP ingress builds its ``Request`` in
another task with no run context, so a remote node gets nothing (D6) without extra code.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
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
from url4.dag.attachment import Attachment

_WEB_SCHEMES = ("http://", "https://")


@dataclass(frozen=True)
class CachedBlob:
    """Verified blob bytes and the media type the store reported (``None`` when it gave none).

    WHY not an :class:`Attachment`: a collection read (D4) needs the store's own media type,
    and ``Attachment`` replaces a missing one with ``application/octet-stream``.
    """

    body: bytes = field(repr=False)
    media_type: str | None


@dataclass(frozen=True, eq=False)
class RunFiles:
    """One run's attachment slots plus its file cache.

    ``slots`` is the run-start order: Case attachments, then each source-position entry — an
    attached blob ref's :class:`Attachment`, or the URL of an ``https://`` source (a slot that
    holds an attachment only once that source returns a non-text body, Q-B). ``cache`` is keyed
    by blob digest (``sha256:<hex>``) or source URL and holds the verified blob (or a text
    body). AIDEV-NOTE: the run-start resolver fills it for blob refs; ``WebFetchNode`` adds a
    non-text ``https://`` body (:meth:`attach_fetched`); nodes keep their own fetch on a miss.
    """

    slots: tuple[Attachment | str, ...]
    cache: dict[str, CachedBlob | str] = field(default_factory=dict)
    fetched: dict[str, Attachment] = field(default_factory=dict)

    @property
    def attachments(self) -> tuple[Attachment, ...]:
        """The ordered list: filled slots in order, then unslotted https bodies; one per digest.

        INVARIANT: with no ``https://`` body fetched this is exactly the run-start list.
        AIDEV-NOTE (Q-B): an ``https://`` source is lazy, so its attachment is visible to the
        calls that run after its fetch (every call that reads it), not to an earlier sibling.
        """
        slotted = {slot for slot in self.slots if isinstance(slot, str)}
        filled = [
            slot if isinstance(slot, Attachment) else self.fetched.get(slot) for slot in self.slots
        ]
        filled += [att for url, att in self.fetched.items() if url not in slotted]
        ordered: dict[str, Attachment] = {}
        for attachment in filled:
            if attachment is not None:
                ordered.setdefault(attachment.digest, attachment)
        return tuple(ordered.values())

    def attach_fetched(self, url: str, blob: CachedBlob, attachment: Attachment) -> None:
        """Record a non-text ``https://`` body: cached by URL and digest, attached at its slot."""
        self.cache.setdefault(url, blob)
        self.cache.setdefault(attachment.digest, blob)
        self.fetched.setdefault(url, attachment)


_RUN_FILES: ContextVar[RunFiles | None] = ContextVar("url4_run_files", default=None)


def current_run_files() -> RunFiles | None:
    """The bound run's files, or ``None`` outside any ``run()``."""
    return _RUN_FILES.get()


def current_attachments() -> tuple[Attachment, ...]:
    """The run's ordered attachments; empty outside a run."""
    files = _RUN_FILES.get()
    return () if files is None else files.attachments


@contextmanager
def bind_run_files(
    attachments: Sequence[Attachment | str], cache: Mapping[str, CachedBlob | str] | None = None
) -> Iterator[RunFiles]:
    """Bind ``attachments`` (and the run's cache) for one top-level run; reset on exit.

    ``attachments`` are the run's slots (:attr:`RunFiles.slots`): a ``str`` is the URL of an
    ``https://`` source that may attach later. Nested inside a bound run, the outer
    :class:`RunFiles` is reused verbatim: an empty ``attachments`` means "nothing to add", the
    same tuple is accepted, anything else raises.
    """
    outer = _RUN_FILES.get()
    wanted = tuple(attachments)
    if outer is not None:
        if wanted and wanted != outer.attachments:
            raise ValueError(
                "run(): a nested run cannot bind different attachments; the list is fixed "
                "when the outermost run starts (F2)"
            )
        yield outer
        return
    files = RunFiles(wanted, dict(cache or {}))
    token = _RUN_FILES.set(files)
    try:
        yield files
    finally:
        _RUN_FILES.reset(token)


@contextmanager
def detached_run_files() -> Iterator[None]:
    """Run the body with NO run bound: the ingress of a request from another node.

    WHY: a served request belongs to no calling run. Over a real socket that is free (a new
    task), but an in-process transport shares the caller's context; detaching makes the
    remote-node rule (D6: nothing is shipped to another node) hold for both.
    """
    token = _RUN_FILES.set(None)
    try:
        yield
    finally:
        _RUN_FILES.reset(token)


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


@dataclass(frozen=True)
class SourceScan:
    """The run's file refs, and the source-order keys of its attachment slots.

    ``order`` holds, at first sight in pre-order, an attachable file ref's :attr:`FileRef.key`
    and the URL of every ``http(s)://`` source read in scalar position (Q-B: such a source
    attaches only if its body turns out not to be text; collection position never attaches).
    """

    refs: tuple[FileRef, ...]
    order: tuple[str, ...]


@dataclass
class _Found:
    refs: dict[str, FileRef] = field(default_factory=dict)
    order: dict[str, None] = field(default_factory=dict)  # an ordered set
    urls: set[str] = field(default_factory=set)


def scan_sources(ast: Node) -> SourceScan:
    """One structural walk (see :func:`collect_file_refs`) yielding refs and slot order."""
    found = _Found()
    _walk(ast, {}, False, found)
    refs = tuple(found.refs.values())
    attached = {ref.key for ref in refs if not ref.collection}
    order = tuple(key for key in found.order if key in attached or key in found.urls)
    return SourceScan(refs, order)


def _walk(node: Node, bound: Mapping[str, Node], collection: bool, out: _Found) -> None:
    if _add_leaf(node, collection, out):
        return
    match node:
        case Expression():
            _walk_expression(node, bound, out)
        case Binding(value=value):
            _walk(value, bound, collection, out)
        case Source(value=value, expand=expand):
            _walk(value, bound, collection or expand, out)
        case Iteration(collection=items, body=body):
            _walk_collection(items, bound, out)
            _walk_source_list(body, bound, out)
        case RelExpr():
            _walk_rel_expr(node, bound, out)
        case _:
            pass  # Text, RemoteExpr (C6), holdings, VarRef in scalar use, struct, ...


def _walk_expression(node: Expression, bound: Mapping[str, Node], out: _Found) -> None:
    scope = dict(bound) | _bindings(node.sources)
    for source in node.sources:
        _walk(source, scope, False, out)
    if node.intent is not None:
        _walk(node.intent, scope, False, out)


def _walk_rel_expr(node: RelExpr, bound: Mapping[str, Node], out: _Found) -> None:
    # INVARIANT: a context holding a holdings ref ("@") ships verbatim to the receiving
    # route and is never resolved caller-side (mirrors the lowering's _context_slots).
    if node.context is not None and "@" not in node.context:
        _walk_source_list(node.context, bound, out)
    if node.intent is not None:
        _walk(node.intent, bound, False, out)


def _walk_collection(items: Node, bound: Mapping[str, Node], out: _Found) -> None:
    if isinstance(items, Expression) and items.intent is None and not items.broadcast:
        _walk(items, bound, False, out)  # an inline collection: its elements are values
        return
    if isinstance(items, VarRef) and not items.path and items.name in bound:
        # Plan §2.9: ``$x*(…)`` reads the bound file ref in collection position.
        items = bound[items.name]
    _walk(items, bound, True, out)


def _walk_source_list(text: str, bound: Mapping[str, Node], out: _Found) -> None:
    for segment in split_top_level_commas(text):
        if not segment.strip():
            continue
        try:
            parsed = grammar_parse(segment.strip())
        except ParseError:
            continue
        _walk(parsed, bound, False, out)


def _bindings(sources: tuple[Node, ...]) -> dict[str, Node]:
    named: dict[str, Node] = {}
    for source in sources:
        if isinstance(source, Binding):
            named[source.name] = source.value
        elif isinstance(source, Source) and source.name is not None:
            named[source.name] = source.value
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


def attachment_slots(
    case: Sequence[Attachment], resolved: Mapping[str, Attachment], order: Sequence[str]
) -> tuple[Attachment | str, ...]:
    """Case attachments first, then each source-order key: a resolved ref's attachment, or
    an ``https://`` URL left as a pending slot. Duplicates collapse in :attr:`RunFiles.attachments`.
    """
    return (*case, *(resolved.get(key, key) for key in order))


__all__ = [
    "CachedBlob",
    "FileRef",
    "RunFiles",
    "bind_run_files",
    "collect_file_refs",
    "current_attachments",
    "current_run_files",
    "detached_run_files",
    "SourceScan",
    "attachment_slots",
    "refuse_remote",
    "scan_sources",
]

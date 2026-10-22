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
    VarRef,
)
from url4.core.parser import split_top_level_commas
from url4.dag.attachment import Attachment


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
    """One run's fixed attachment list plus its file cache.

    ``cache`` is keyed by blob digest (``sha256:<hex>``) or source URL and holds the verified
    blob (or a text body). AIDEV-NOTE: only the run-start resolver fills it; nodes read it on a
    hit and keep their own fetch on a miss (a node evaluated outside ``run()``).
    """

    attachments: tuple[Attachment, ...]
    cache: dict[str, CachedBlob | str] = field(default_factory=dict)


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
    attachments: Sequence[Attachment], cache: Mapping[str, CachedBlob | str] | None = None
) -> Iterator[RunFiles]:
    """Bind ``attachments`` (and the run's cache) for one top-level run; reset on exit.

    Nested inside a bound run, the outer :class:`RunFiles` is reused verbatim: an empty
    ``attachments`` means "nothing to add", the same tuple is accepted, anything else raises.
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
    found: dict[str, FileRef] = {}
    _walk(ast, {}, False, found)
    return tuple(found.values())


def _walk(node: Node, bound: Mapping[str, Node], collection: bool, out: dict[str, FileRef]) -> None:
    address = address_of(node)
    if address is not None:
        _add(out, FileRef(address, collection))
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


def _walk_expression(node: Expression, bound: Mapping[str, Node], out: dict[str, FileRef]) -> None:
    scope = dict(bound) | _bindings(node.sources)
    for source in node.sources:
        _walk(source, scope, False, out)
    if node.intent is not None:
        _walk(node.intent, scope, False, out)


def _walk_rel_expr(node: RelExpr, bound: Mapping[str, Node], out: dict[str, FileRef]) -> None:
    # INVARIANT: a context holding a holdings ref ("@") ships verbatim to the receiving
    # route and is never resolved caller-side (mirrors the lowering's _context_slots).
    if node.context is not None and "@" not in node.context:
        _walk_source_list(node.context, bound, out)
    if node.intent is not None:
        _walk(node.intent, bound, False, out)


def _walk_collection(items: Node, bound: Mapping[str, Node], out: dict[str, FileRef]) -> None:
    if isinstance(items, Expression) and items.intent is None and not items.broadcast:
        _walk(items, bound, False, out)  # an inline collection: its elements are values
        return
    if isinstance(items, VarRef) and not items.path and items.name in bound:
        # Plan §2.9: ``$x*(…)`` reads the bound file ref in collection position.
        items = bound[items.name]
    _walk(items, bound, True, out)


def _walk_source_list(text: str, bound: Mapping[str, Node], out: dict[str, FileRef]) -> None:
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


def _add(out: dict[str, FileRef], ref: FileRef) -> None:
    seen = out.get(ref.key)
    if seen is None:
        out[ref.key] = ref
    elif seen.collection and not ref.collection:
        out[ref.key] = FileRef(seen.address, False)  # first position, now attached


def refuse_remote(refs: Sequence[FileRef]) -> None:
    """D1 / F1: any ``url4://`` blob ref fails the run before ANY I/O, local refs included."""
    for ref in refs:
        if ref.address.form == "remote":
            raise ResolutionError(
                f"remote blob refs are not supported in v1 ({ref.address.ref!r})",
                code=ErrorCode.REMOTE_BLOB_UNSUPPORTED,
                permanent=True,
            )


def merge_attachments(
    case: Sequence[Attachment], resolved: Sequence[tuple[FileRef, Attachment]]
) -> tuple[Attachment, ...]:
    """Case attachments first, then the attached url4 refs; one entry per digest."""
    ordered: dict[str, Attachment] = {}
    for attachment in case:
        ordered.setdefault(attachment.digest, attachment)
    for ref, attachment in resolved:
        if not ref.collection:
            ordered.setdefault(attachment.digest, attachment)
    return tuple(ordered.values())


__all__ = [
    "CachedBlob",
    "FileRef",
    "RunFiles",
    "bind_run_files",
    "collect_file_refs",
    "current_attachments",
    "current_run_files",
    "detached_run_files",
    "merge_attachments",
    "refuse_remote",
]

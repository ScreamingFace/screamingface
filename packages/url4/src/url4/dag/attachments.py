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
from types import MappingProxyType

from url4.core.errors import ResolutionError
from url4.dag.attachment import Attachment
from url4.dag.attachment_sources import AttachmentIdentity
from url4.io.layer import FetchRequest, FetchResult

# WHY: the AST scan lives in :mod:`url4.dag.source_scan` (size, reason to change); the
# redundant aliases keep every ``url4.dag.attachments.<name>`` import path working.
from url4.dag.source_scan import CollectionGuard as CollectionGuard  # isort: skip
from url4.dag.source_scan import FileRef as FileRef  # isort: skip
from url4.dag.source_scan import Occurrence as Occurrence  # isort: skip
from url4.dag.source_scan import SourceScan as SourceScan  # isort: skip
from url4.dag.source_scan import collect_file_refs as collect_file_refs  # isort: skip
from url4.dag.source_scan import refuse_remote as refuse_remote  # isort: skip
from url4.dag.source_scan import scan_sources as scan_sources  # isort: skip


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
    """One run's attachment slots plus its file cache — frozen when the run starts.

    ``slots`` is the run-start order: Case attachments, then each source-position entry — an
    attached blob ref's :class:`Attachment`, or an attachment source's identity (filled from
    ``manifest``). ``cache`` is keyed by blob digest (``sha256:<hex>``) and holds the verified
    blob; nodes keep their own fetch on a miss.

    INVARIANT (F2 freeze, owner decision A/E 2026-10-27): nothing adds to the list after the
    run starts — ``slots`` is a tuple and ``manifest`` a read-only view, the only two inputs of
    :attr:`attachments`, so it is the same list for every model call and the caps checked at
    run start (:mod:`url4.dag._caps`) hold for the whole run. ``cache`` is a read-through
    store of verified bytes only; it never feeds the list.
    """

    slots: tuple[Attachment | AttachmentIdentity, ...]
    cache: dict[str, CachedBlob | str] = field(default_factory=dict)
    # F1b round 7: each materialized identity's outcome (frozen before the first model call),
    # and the collection fetches the admission phase made, replayed once each by execution.
    manifest: Mapping[AttachmentIdentity, Attachment | ResolutionError] = field(
        default_factory=lambda: MappingProxyType({})
    )
    prefetched: dict[tuple, list[FetchResult | Exception]] = field(default_factory=dict)

    @property
    def attachments(self) -> tuple[Attachment, ...]:
        """The ordered list: filled slots in order, one per dedup key."""
        ordered: dict[object, Attachment] = {}
        for key, attachment in map(self._filled, self.slots):
            if attachment is not None:
                ordered.setdefault(key, attachment)
        return tuple(ordered.values())

    def _filled(self, slot: Attachment | AttachmentIdentity) -> tuple[object, Attachment | None]:
        """A slot's dedup key and attachment (``None`` when its identity was omitted).

        INVARIANT (F1b round 7): an attachment identity is its own key — never merged with
        another identity or a blob ref, even for equal bytes; everything else dedups by digest.
        """
        if isinstance(slot, AttachmentIdentity):
            outcome = self.manifest.get(slot)
            return slot, outcome if isinstance(outcome, Attachment) else None
        return slot.digest, slot

    def take_prefetched(self, request: FetchRequest) -> FetchResult | None:
        """Replay (once) a collection fetch the admission phase already made, else ``None``.

        WHY one-shot: execution then performs exactly the fetches it performs today, minus the
        ones admission made for it — a collection is resolved once, not twice.
        """
        pending = self.prefetched.get(prefetch_key(request))
        if not pending:
            return None
        outcome = pending.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def prefetch_key(request: FetchRequest) -> tuple:
    """The identity of a collection fetch: target, relativity, kind and ``;accept=``."""
    return (request.target, request.relative, request.kind, request.accept)


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
    attachments: Sequence[Attachment | AttachmentIdentity],
    cache: Mapping[str, CachedBlob | str] | None = None,
    *,
    manifest: Mapping[AttachmentIdentity, Attachment | ResolutionError] | None = None,
    prefetched: Mapping[tuple, list[FetchResult | Exception]] | None = None,
) -> Iterator[RunFiles]:
    """Bind ``attachments`` (and the run's cache) for one top-level run; reset on exit.

    ``attachments`` are the run's slots (:attr:`RunFiles.slots`). Nested inside a bound run,
    the outer :class:`RunFiles` is reused verbatim: an empty ``attachments`` means "nothing to
    add", the same tuple is accepted, anything else raises.
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
    files = RunFiles(
        wanted,
        dict(cache or {}),
        MappingProxyType(dict(manifest or {})),
        dict(prefetched or {}),
    )
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


def attachment_slots(
    case: Sequence[Attachment],
    resolved: Mapping[str, Attachment],
    order: Sequence[str | AttachmentIdentity],
) -> tuple[Attachment | AttachmentIdentity, ...]:
    """Case attachments first, then each source-order key: a resolved blob ref's attachment, or
    an attachment source's identity. Duplicates collapse in :attr:`RunFiles.attachments`.
    """
    return (
        *case,
        *(key if isinstance(key, AttachmentIdentity) else resolved[key] for key in order),
    )


__all__ = [
    "CachedBlob",
    "CollectionGuard",
    "FileRef",
    "Occurrence",
    "RunFiles",
    "bind_run_files",
    "collect_file_refs",
    "current_attachments",
    "current_run_files",
    "detached_run_files",
    "SourceScan",
    "attachment_slots",
    "prefetch_key",
    "refuse_remote",
    "scan_sources",
]

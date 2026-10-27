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
    """One run's attachment slots plus its file cache.

    ``slots`` is the run-start order: Case attachments, then each source-position entry — an
    attached blob ref's :class:`Attachment`, or the URL of an ``https://`` source (a slot that
    holds an attachment only once that source returns a non-text body, Q-B). ``cache`` is keyed
    by blob digest (``sha256:<hex>``) or source URL and holds the verified blob (or a text
    body). AIDEV-NOTE: the run-start resolver fills it for blob refs; ``WebFetchNode`` adds a
    non-text ``https://`` body (:meth:`attach_fetched`); nodes keep their own fetch on a miss.
    """

    slots: tuple[Attachment | str | AttachmentIdentity, ...]
    cache: dict[str, CachedBlob | str] = field(default_factory=dict)
    fetched: dict[str, Attachment] = field(default_factory=dict)
    # F1b round 7: each materialized identity's outcome (frozen before the first model call),
    # and the collection fetches the admission phase made, replayed once each by execution.
    manifest: Mapping[AttachmentIdentity, Attachment | ResolutionError] = field(
        default_factory=dict
    )
    prefetched: dict[tuple, list[FetchResult | Exception]] = field(default_factory=dict)

    @property
    def attachments(self) -> tuple[Attachment, ...]:
        """The ordered list: filled slots in order, then unslotted https bodies; one per digest.

        INVARIANT: with no ``https://`` body fetched this is exactly the run-start list.
        AIDEV-NOTE (Q-B): an ``https://`` source is lazy, so its attachment is visible to the
        calls that run after its fetch (every call that reads it), not to an earlier sibling.
        """
        slotted = {slot for slot in self.slots if isinstance(slot, str)}
        filled = [self._filled(slot) for slot in self.slots]
        filled += [(att.digest, att) for url, att in self.fetched.items() if url not in slotted]
        ordered: dict[object, Attachment] = {}
        for key, attachment in filled:
            if attachment is not None:
                ordered.setdefault(key, attachment)
        return tuple(ordered.values())

    def _filled(
        self, slot: Attachment | str | AttachmentIdentity
    ) -> tuple[object, Attachment | None]:
        """A slot's dedup key and attachment (``None`` while empty or omitted).

        INVARIANT (F1b round 7): an attachment identity is its own key — never merged with
        another identity or a blob ref, even for equal bytes; everything else dedups by digest.
        """
        if isinstance(slot, AttachmentIdentity):
            outcome = self.manifest.get(slot)
            return slot, outcome if isinstance(outcome, Attachment) else None
        attachment = slot if isinstance(slot, Attachment) else self.fetched.get(slot)
        return (None if attachment is None else attachment.digest), attachment

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

    def attach_fetched(self, url: str, blob: CachedBlob, attachment: Attachment) -> None:
        """Record a non-text ``https://`` body: cached by URL and digest, attached at its slot."""
        self.cache.setdefault(url, blob)
        self.cache.setdefault(attachment.digest, blob)
        self.fetched.setdefault(url, attachment)


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
    attachments: Sequence[Attachment | str | AttachmentIdentity],
    cache: Mapping[str, CachedBlob | str] | None = None,
    *,
    manifest: Mapping[AttachmentIdentity, Attachment | ResolutionError] | None = None,
    prefetched: Mapping[tuple, list[FetchResult | Exception]] | None = None,
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
    files = RunFiles(wanted, dict(cache or {}), {}, dict(manifest or {}), dict(prefetched or {}))
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
) -> tuple[Attachment | str | AttachmentIdentity, ...]:
    """Case attachments first, then each source-order key: a resolved ref's attachment, or
    an ``https://`` URL left as a pending slot. Duplicates collapse in :attr:`RunFiles.attachments`.
    """
    return (
        *case,
        *(key if isinstance(key, AttachmentIdentity) else resolved.get(key, key) for key in order),
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

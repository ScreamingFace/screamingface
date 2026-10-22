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

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from url4.dag.attachment import Attachment


@dataclass(frozen=True, eq=False)
class RunFiles:
    """One run's fixed attachment list plus its file cache.

    ``cache`` is keyed by blob digest (``sha256:<hex>``) or source URL and holds the verified
    :class:`Attachment` (or a text body). AIDEV-NOTE: only the run-start resolver fills it;
    nodes read it on a hit and keep their own fetch on a miss.
    """

    attachments: tuple[Attachment, ...]
    cache: dict[str, Attachment | str] = field(default_factory=dict)


_RUN_FILES: ContextVar[RunFiles | None] = ContextVar("url4_run_files", default=None)


def current_run_files() -> RunFiles | None:
    """The bound run's files, or ``None`` outside any ``run()``."""
    return _RUN_FILES.get()


def current_attachments() -> tuple[Attachment, ...]:
    """The run's ordered attachments; empty outside a run."""
    files = _RUN_FILES.get()
    return () if files is None else files.attachments


@contextmanager
def bind_run_files(attachments: Sequence[Attachment]) -> Iterator[RunFiles]:
    """Bind ``attachments`` (and a fresh cache) for one top-level run; reset on exit.

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
    files = RunFiles(wanted)
    token = _RUN_FILES.set(files)
    try:
        yield files
    finally:
        _RUN_FILES.reset(token)


__all__ = [
    "RunFiles",
    "bind_run_files",
    "current_attachments",
    "current_run_files",
]

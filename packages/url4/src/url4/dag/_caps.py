"""The per-run attachment caps: 20 entries, 8,000,000 decoded bytes, over the WHOLE list.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; #1450 F1b "Per-run caps").
STORY: as a node operator, a run cannot make the node hold or send more than 20 attachments or
8 MB of them, whatever mix of Case files, blob refs and ``https://`` attachment sources it names.

INVARIANT (owner decision E, 2026-10-27): the caps are enforced on EVERY path that adds to
``attachments[]`` while the list is built — Case attachments, local blob refs, attachment-source
flights — and nothing adds after the run starts (:class:`~url4.dag.attachments.RunFiles` is
frozen). :class:`CapBudget` refuses as soon as the known entries or the bytes received so far
breach a cap, so a breach stops the remaining fetches (a raise inside ``gather_or_cancel``
cancels its siblings); :func:`check_caps` is the authoritative check over the final list.

INVARIANT (push security review "resource-cap-defeat", owner decision 2026-11-03): the byte cap
is a shared LIVE budget. Every flight draws from it as its bytes arrive
(:meth:`CapBudget.charge_bytes`, the ``FetchRequest.on_chunk`` hook), so the run is refused once
the running total crosses the cap — peak memory is about the cap plus one read chunk per flight.
A failed attempt gives its bytes back (:meth:`CapBudget.release`); :meth:`CapBudget.charge`
settles a landed entry once per key.

AIDEV-NOTE: keys follow :attr:`RunFiles.attachments` dedup — a digest for Case attachments and
blob refs, the :class:`~url4.dag.attachment_sources.AttachmentIdentity` for an attachment
source — so the budget never counts an entry the final list collapses.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Coroutine, Hashable, Iterable, Sequence
from functools import partial
from typing import Any

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag.attachment import Attachment
from url4.dag.node import gather_or_cancel

MAX_ATTACHMENTS = 20
MAX_ATTACHMENT_BYTES = 8_000_000


def _too_many(count: int) -> ResolutionError:
    return ResolutionError(
        f"the run has {count} attachments; at most {MAX_ATTACHMENTS} are allowed",
        code=ErrorCode.ATTACHMENTS_TOO_MANY,
        permanent=True,
    )


def _too_large(total: int) -> ResolutionError:
    return ResolutionError(
        f"the run's attachments hold {total} bytes; at most {MAX_ATTACHMENT_BYTES} are allowed",
        code=ErrorCode.ATTACHMENTS_TOO_LARGE,
        permanent=True,
    )


def whole_body_refused() -> ResolutionError:
    """The refusal of a body whose size cannot be drawn before its read (a whole-body provider).

    WHY one factory for the direct raise (``peer._bytes``) and the sticky one (:meth:`reserve`):
    the run surfaces the STICKY refusal, so both must name the remedy — serve in chunks (owner
    2026-11-06; it read "undeclared size" before, which no operator could act on).
    """
    return ResolutionError(
        "a data provider that hands over its body whole cannot be read within a run's live "
        f"{MAX_ATTACHMENT_BYTES}-byte budget; serve it in chunks (read_chunks)",
        code=ErrorCode.ATTACHMENTS_TOO_LARGE,
        permanent=True,
    )


class CapBudget:
    """The caps, counted while ``attachments[]`` is built (before any model call).

    Thread- and task-safe: every method runs under one re-entrant lock and never awaits.
    """

    def __init__(self, case: Sequence[Attachment] = ()) -> None:
        self._entries: set[Hashable] = set()  # every entry known to come
        self._charged: set[Hashable] = set()  # entries whose bytes are counted
        self._sizes: dict[Hashable, int] = {}  # each counted entry's counted size
        self._bytes = 0  # settled: landed entries
        self._live: dict[Hashable, int] = {}  # in flight: bytes received so far, per key
        self._live_total = 0  # the live bytes that count (see _counted_live)
        self._refused: Callable[[], ResolutionError] | None = None  # the run-ending refusal
        self._lock = threading.RLock()
        for attachment in case:
            self.charge(attachment.digest, len(attachment.body))

    def expect(self, keys: Iterable[Hashable]) -> None:
        """Count entries known before their bytes arrive (a required one always lands or fails
        the run), so a count breach is refused before any of their I/O is spent."""
        with self._lock:
            self._entries.update(keys)
            if len(self._entries) > MAX_ATTACHMENTS:
                raise _too_many(len(self._entries))

    def charge(self, key: Hashable, size: int) -> None:
        """Count one received entry's decoded bytes (once per key) and re-check both caps.

        Settles ``key``: its live bytes (:meth:`charge_bytes`) become these counted ones. A key
        already counted (a Case attachment's digest read again from the store) only gives its
        live bytes back: the final list dedups it.
        """
        with self._lock:
            if key in self._charged:
                self.release(key)
                return
            self._live_total -= self._counted_live(key, self._live.pop(key, 0))
            self._charged.add(key)
            self._sizes[key] = size
            self._bytes += size
            self.expect((key,))
            self._check()

    def charge_bytes(self, key: Hashable, size: int) -> None:
        """Draw ``size`` more bytes of ``key``'s in-flight body; refuse once the total passes.

        INVARIANT (PR #1587 review gap 2, owner 2026-11-04): a read of a key whose bytes are
        already counted draws only the bytes BEYOND its counted size — an honest re-read adds
        nothing to the list, an oversized one is refused once the run passes the cap.
        """
        with self._lock:
            before = self._counted_live(key, self._live.get(key, 0))
            self._live[key] = self._live.get(key, 0) + size
            self._live_total += self._counted_live(key, self._live[key]) - before
            self._check()

    def reserve(self, key: Hashable, size: int | None) -> None:
        """Draw an EXACT ``size`` (a held ``str``) BEFORE the body is kept (``on_declared``).

        INVARIANT (PR #1587 review round 11, decision B, owner 2026-11-05 — FAIL CLOSED): a
        provider's declared size is its word, not a count, so only an exact size is drawn. A
        whole-body read reports ``None`` and is refused unread, stickily (an ``;optional``
        guard cannot swallow it).
        """
        with self._lock:
            if size is None:
                self._refused = self._refused or whole_body_refused
                raise self._refused()
            self.charge_bytes(key, size)

    def release(self, key: Hashable) -> None:
        """Give back ``key``'s in-flight bytes: its attempt failed, or a retry starts over."""
        with self._lock:
            self._live_total -= self._counted_live(key, self._live.pop(key, 0))

    def remaining(self) -> int:
        """The bytes left after the SETTLED entries: a new flight's read ceiling.

        WHY settled only: in-flight bytes may still be given back (a failed ``;optional``
        source), so a ceiling counting them could refuse a body the run has room for; the live
        total is enforced chunk by chunk by :meth:`charge_bytes` instead.
        """
        with self._lock:
            return max(0, MAX_ATTACHMENT_BYTES - self._bytes)

    def ceiling(self, key: Hashable) -> int:
        """``key``'s read ceiling: :meth:`remaining`, plus its own counted size when counted."""
        with self._lock:
            return self.remaining() + self._sizes.get(key, 0)

    def _counted_live(self, key: Hashable, received: int) -> int:
        return max(0, received - self._sizes[key]) if key in self._charged else received

    def raise_if_refused(self) -> None:
        """Re-raise the byte-cap refusal, if any — e.g. one an ``;optional`` guard swallowed."""
        if self._refused is not None:
            raise self._refused()

    def _check(self) -> None:
        # INVARIANT: once refused, every later draw is refused too — a breaching flight giving
        # its bytes back must not let its siblings read on before the refusal ends the run.
        self.raise_if_refused()
        total = self._bytes + self._live_total
        if total > MAX_ATTACHMENT_BYTES:
            self._refused = partial(_too_large, total)
            raise self._refused()


async def gather_charged[T](budget: CapBudget, coros: Iterable[Coroutine[Any, Any, T]]) -> list[T]:
    """:func:`gather_or_cancel` over flights that draw from ``budget``; the cap refusal wins.

    INVARIANT (PR #1587 review finding 6, owner 2026-11-04): when the concurrent flights fail and
    ``budget`` is refused (sticky), the run fails ``x.attachments_too_large`` — never a sibling's
    source error that ``gather_or_cancel``'s first-leaf pick happened to surface. A failure
    with no refusal re-raises unchanged.
    """
    try:
        return await gather_or_cancel(coros)
    except Exception:
        budget.raise_if_refused()
        raise


def check_caps(attachments: Sequence[Attachment]) -> None:
    """F1b per-run caps over the WHOLE final list: 20 entries, 8,000,000 decoded bytes."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise _too_many(len(attachments))
    total = sum(len(attachment.body) for attachment in attachments)
    if total > MAX_ATTACHMENT_BYTES:
        raise _too_large(total)


__all__ = ["MAX_ATTACHMENTS", "MAX_ATTACHMENT_BYTES", "CapBudget", "check_caps", "gather_charged"]

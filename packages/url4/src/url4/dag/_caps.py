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
from collections.abc import Hashable, Iterable, Sequence

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag.attachment import Attachment

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


class CapBudget:
    """The caps, counted while ``attachments[]`` is built (before any model call).

    Thread- and task-safe: every method runs under one re-entrant lock and never awaits.
    """

    def __init__(self, case: Sequence[Attachment] = ()) -> None:
        self._entries: set[Hashable] = set()  # every entry known to come
        self._charged: set[Hashable] = set()  # entries whose bytes are counted
        self._bytes = 0  # settled: landed entries
        self._live: dict[Hashable, int] = {}  # in flight: bytes received so far, per key
        self._live_total = 0
        self._refused: int | None = None  # the total that first crossed the cap
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

        Settles ``key``: its live bytes (:meth:`charge_bytes`) become these counted ones.
        """
        with self._lock:
            if key in self._charged:
                return
            self._charged.add(key)
            self._live_total -= self._live.pop(key, 0)
            self._bytes += size
            self.expect((key,))
            self._check()

    def charge_bytes(self, key: Hashable, size: int) -> None:
        """Draw ``size`` more bytes of ``key``'s in-flight body; refuse once the total passes."""
        with self._lock:
            self._live[key] = self._live.get(key, 0) + size
            self._live_total += size
            self._check()

    def release(self, key: Hashable) -> None:
        """Give back ``key``'s in-flight bytes: its attempt failed, or a retry starts over."""
        with self._lock:
            self._live_total -= self._live.pop(key, 0)

    def remaining(self) -> int:
        """The bytes left after the SETTLED entries: a new flight's read ceiling.

        WHY settled only: in-flight bytes may still be given back (a failed ``;optional``
        source), so a ceiling counting them could refuse a body the run has room for; the live
        total is enforced chunk by chunk by :meth:`charge_bytes` instead.
        """
        with self._lock:
            return max(0, MAX_ATTACHMENT_BYTES - self._bytes)

    def raise_if_refused(self) -> None:
        """Re-raise the byte-cap refusal, if any — e.g. one an ``;optional`` guard swallowed."""
        if self._refused is not None:
            raise _too_large(self._refused)

    def _check(self) -> None:
        # INVARIANT: once refused, every later draw is refused too — a breaching flight giving
        # its bytes back must not let its siblings read on before the refusal ends the run.
        self.raise_if_refused()
        total = self._bytes + self._live_total
        if total > MAX_ATTACHMENT_BYTES:
            self._refused = total
            raise _too_large(total)


def check_caps(attachments: Sequence[Attachment]) -> None:
    """F1b per-run caps over the WHOLE final list: 20 entries, 8,000,000 decoded bytes."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise _too_many(len(attachments))
    total = sum(len(attachment.body) for attachment in attachments)
    if total > MAX_ATTACHMENT_BYTES:
        raise _too_large(total)


__all__ = ["MAX_ATTACHMENTS", "MAX_ATTACHMENT_BYTES", "CapBudget", "check_caps"]

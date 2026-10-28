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

AIDEV-NOTE: keys follow :attr:`RunFiles.attachments` dedup — a digest for Case attachments and
blob refs, the :class:`~url4.dag.attachment_sources.AttachmentIdentity` for an attachment
source — so the budget never counts an entry the final list collapses.
"""

from __future__ import annotations

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
    """The caps, counted while ``attachments[]`` is built (before any model call)."""

    def __init__(self, case: Sequence[Attachment] = ()) -> None:
        self._entries: set[Hashable] = set()  # every entry known to come
        self._charged: set[Hashable] = set()  # entries whose bytes are counted
        self._bytes = 0
        for attachment in case:
            self.charge(attachment.digest, len(attachment.body))

    def expect(self, keys: Iterable[Hashable]) -> None:
        """Count entries known before their bytes arrive (a required one always lands or fails
        the run), so a count breach is refused before any of their I/O is spent."""
        self._entries.update(keys)
        if len(self._entries) > MAX_ATTACHMENTS:
            raise _too_many(len(self._entries))

    def charge(self, key: Hashable, size: int) -> None:
        """Count one received entry's decoded bytes (once per key) and re-check both caps."""
        if key in self._charged:
            return
        self._charged.add(key)
        self._bytes += size
        self.expect((key,))
        if self._bytes > MAX_ATTACHMENT_BYTES:
            raise _too_large(self._bytes)


def check_caps(attachments: Sequence[Attachment]) -> None:
    """F1b per-run caps over the WHOLE final list: 20 entries, 8,000,000 decoded bytes."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise _too_many(len(attachments))
    total = sum(len(attachment.body) for attachment in attachments)
    if total > MAX_ATTACHMENT_BYTES:
        raise _too_large(total)


__all__ = ["MAX_ATTACHMENTS", "MAX_ATTACHMENT_BYTES", "CapBudget", "check_caps"]

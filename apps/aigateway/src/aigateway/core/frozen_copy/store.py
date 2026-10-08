"""The frozen-copy store: open, capture, seal and replay lookup (OME-1307, design §3 and §4).

INVARIANT (F1): an entry is only inserted into an ``open`` copy. The status is re-read under a row
lock inside the insert's own transaction, so a seal that lands between the route's check and the
insert wins, and the late entry is refused instead of slipping into a sealed copy. (SQLite ignores
the lock; its single writer gives the same ordering. The Postgres lock is not covered by the unit
suite, which has no Postgres here.)

INVARIANT: the digest of an entry is computed here and nowhere else, from the same
``canonical_digest`` every cache lane uses, so capture and replay cannot disagree about a request.

The store never logs and never returns a stored request: the route that calls it owns both.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from tortoise.transactions import in_transaction

from aigateway.core.request_cache.canonical import canonical_digest

from .models import STATUS_OPEN, STATUS_SEALED, FrozenCopy, FrozenCopyEntry

__all__ = [
    "FrozenCopyEntryTooLarge",
    "FrozenCopySealed",
    "FrozenCopyStore",
    "frozen_copy_store_for",
    "log_capture_failure",
    "request_digest",
    "request_digest_prefix",
]

logger = logging.getLogger(__name__)

EntryKind = Literal["chat", "tool"]

_SUCCESS_STATUS = 200


class FrozenCopySealed(Exception):
    """The copy is not open any more, so it accepts no insert."""


class FrozenCopyEntryTooLarge(Exception):
    """Request plus response JSON is over the per-entry cap (design F3)."""


def request_digest(kind: EntryKind, request: Any) -> str:
    return canonical_digest({"kind": kind, "request": request})


def request_digest_prefix(kind: EntryKind, request: Any) -> str:
    """The first 12 digest characters, for a log line; never raises, never carries the request."""
    try:
        return request_digest(kind, request)[:12]
    except Exception:
        return "unavailable"


def log_capture_failure(
    kind: EntryKind, exc: BaseException, *, copy_id: Any = None, request: Any = None
) -> None:
    """The ONE log line for a capture that did not store (design Q18, best effort).

    INVARIANT: the copy id, the kind, a digest prefix and the exception CLASS only — never the
    request, and never the exception message, which can carry the prompt.
    """
    logger.warning(
        "frozen copy capture failed copy=%s digest=%s kind=%s error=%s",
        "n/a" if copy_id is None else copy_id,
        "n/a" if request is None else request_digest_prefix(kind, request),
        kind,
        type(exc).__name__,
    )


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


class FrozenCopyStore:
    def __init__(self, *, max_entry_bytes: int) -> None:
        self._max_entry_bytes = max_entry_bytes

    @property
    def max_entry_bytes(self) -> int:
        return self._max_entry_bytes

    async def open(self, account_id: UUID) -> FrozenCopy:
        return await FrozenCopy.create(account_id=account_id)

    async def get(self, copy_id: UUID) -> FrozenCopy | None:
        return await FrozenCopy.get_or_none(id=copy_id)

    async def seal(self, copy_id: UUID, account_id: UUID) -> FrozenCopy | None:
        """Seal the owner's copy; ``None`` for an unknown copy or a non-owner (no leak)."""
        async with in_transaction():
            copy = (
                await FrozenCopy.filter(id=copy_id, account_id=account_id)
                .select_for_update()
                .first()
            )
            if copy is None:
                return None
            if copy.status == STATUS_SEALED:
                return copy
            copy.entries = await FrozenCopyEntry.filter(frozen_copy_id=copy.id).count()
            copy.status = STATUS_SEALED
            copy.sealed_at = datetime.now(UTC)
            await copy.save(update_fields=["entries", "status", "sealed_at"])
            return copy

    async def capture(
        self,
        copy: FrozenCopy,
        kind: EntryKind,
        request: Any,
        response: Any,
        status_code: int,
    ) -> None:
        """Insert one entry. Raises on any failure; the caller decides what that means.

        Raises:
            FrozenCopyEntryTooLarge: request plus response is over the per-entry cap.
            FrozenCopySealed: the copy is not open.
            CanonicalizationError: the request cannot be digested deterministically.
        """
        digest = request_digest(kind, request)
        if _json_bytes(request) + _json_bytes(response) > self._max_entry_bytes:
            raise FrozenCopyEntryTooLarge
        async with in_transaction():
            current = await FrozenCopy.filter(id=copy.id).select_for_update().first()
            if current is None or current.status != STATUS_OPEN:
                raise FrozenCopySealed
            # INVARIANT: capture order is a counter advanced under the same row lock as the
            # status check, so two inserts of one copy can never share a position.
            current.entry_seq += 1
            await current.save(update_fields=["entry_seq"])
            await FrozenCopyEntry.create(
                frozen_copy_id=copy.id,
                kind=kind,
                request_digest=digest,
                request_json=request,
                response_json=response,
                status_code=status_code,
                seq=current.entry_seq,
            )

    async def find(
        self, copy: FrozenCopy, kind: EntryKind, request: Any, occurrence: int
    ) -> FrozenCopyEntry | None:
        """The replay lookup rule (design §4.4); ``None`` is a miss.

        1. Successful entries in capture order: entry ``occurrence``, or the last one when
           ``occurrence`` is past the end.
        2. No success: the latest captured error.
        3. Nothing: ``None``.
        """
        entries = FrozenCopyEntry.filter(
            frozen_copy_id=copy.id, kind=kind, request_digest=request_digest(kind, request)
        )
        successes = entries.filter(status_code=_SUCCESS_STATUS)
        count = await successes.count()
        if count:
            return await successes.order_by("seq").offset(min(occurrence, count - 1)).first()
        return await entries.order_by("-seq").first()


def frozen_copy_store_for(app: Any) -> FrozenCopyStore:
    """The one store of this app, built from its settings on first use."""
    store = getattr(app.state, "frozen_copy_store", None)
    if store is None:
        store = FrozenCopyStore(max_entry_bytes=app.state.settings.frozen_copy_max_entry_bytes)
        app.state.frozen_copy_store = store
    return store

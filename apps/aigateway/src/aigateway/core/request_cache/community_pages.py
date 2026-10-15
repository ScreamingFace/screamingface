"""Read the community cache one page at a time, in write order (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
Spec: ``docs/spec/2026-10-15-community-cache.md``.

A client walks the shareable rows of ``request_cache_entries`` page after page: each page is the
rows after a cursor, and the cursor is the last row's ``(updated_at, key_hash)``. Each page is
read in batches of ``BATCH_ROWS``, every batch its own short keyset query on the
``(updated_at, key_hash)`` index (migration 0015), so no connection or transaction is held between
batches and the caller can write each batch out before the next is read.

WHY write order: a row written while a walk is under way lands after the cursor, so the same walk
reaches it. ``updated_at`` rather than ``created_at`` because a snapshot restore inserts rows with
their source's ``created_at`` and overwrites rows without changing it; ``updated_at`` moves in
both cases.
INVARIANT: a cache hit never moves ``updated_at`` (``store.record_hit_metadata``). If it did,
every hit row would jump to the end of the order and every pull would re-send it.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from tortoise.expressions import Q
from tortoise.queryset import QuerySet

from .models import RequestCacheEntry

PAGE_SCHEMA: Final = "screamingface.cache-page.v1"
MAX_PAGE_ROWS: Final = 5000
BATCH_ROWS: Final = 100

# INVARIANT (spec decision 7): what crosses. No ``id``, ``hit_count`` or ``last_hit_at``: they
# describe the platform's usage, not the cached answer.
PAGE_FIELDS: Final[tuple[str, ...]] = (
    "key_hash",
    "prompt_hash",
    "provider",
    "model",
    "response_json",
    "response_size_bytes",
    "created_at",
    "updated_at",
    "expires_at",
    "metadata_json",
)

_KEY_HASH = re.compile(r"[0-9a-f]{64}")
_ORDER: Final = ("updated_at", "key_hash")


class InvalidCursor(ValueError):
    """The ``after`` token is not a cursor this module issued."""


@dataclass(frozen=True)
class PageCursor:
    """The last row a client received: where the next page starts."""

    updated_at: datetime
    key_hash: str

    @classmethod
    def decode(cls, token: str) -> PageCursor:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
            stamp, key_hash = raw.split("|")
            updated_at = datetime.fromisoformat(stamp)
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise InvalidCursor("not a cursor this route issued") from exc
        if updated_at.tzinfo is None or not _KEY_HASH.fullmatch(key_hash):
            raise InvalidCursor("not a cursor this route issued")
        return cls(updated_at=updated_at, key_hash=key_hash)

    def encode(self) -> str:
        raw = f"{self.updated_at.isoformat()}|{self.key_hash}".encode("ascii")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _eligible(models: Sequence[str], now: datetime) -> QuerySet[RequestCacheEntry]:
    # WHY no Tavily: its keys hash the caller's account id — one account's private entries,
    # useless (and nobody else's business) anywhere else.
    rows = RequestCacheEntry.exclude(provider="tavily").filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    return rows.filter(model__in=list(models)) if models else rows


def _after(rows: QuerySet[RequestCacheEntry], cursor: PageCursor | None) -> QuerySet:
    if cursor is None:
        return rows
    # INVARIANT: ties on updated_at (a restore stamps many rows with one time) split by key_hash,
    # so a page boundary inside a run of equal times skips and repeats nothing.
    return rows.filter(
        Q(updated_at__gt=cursor.updated_at)
        | Q(updated_at=cursor.updated_at, key_hash__gt=cursor.key_hash)
    )


async def count_rows(*, after: PageCursor | None, models: Sequence[str], now: datetime) -> int:
    """How many rows a walk from ``after`` would return (approximate once writes continue)."""
    return await _after(_eligible(models, now), after).count()


async def iter_page(
    *, after: PageCursor | None, limit: int, models: Sequence[str], now: datetime
) -> AsyncIterator[list[dict[str, Any]]]:
    """Yield one page of at most ``limit`` rows, in batches of at most ``BATCH_ROWS``."""
    eligible = _eligible(models, now)
    cursor = after
    left = limit
    while left > 0:
        size = min(BATCH_ROWS, left)
        batch = await _after(eligible, cursor).order_by(*_ORDER).limit(size).values(*PAGE_FIELDS)
        if not batch:
            return
        yield batch
        left -= len(batch)
        cursor = PageCursor(updated_at=batch[-1]["updated_at"], key_hash=batch[-1]["key_hash"])
        if len(batch) < size:
            return


def cursor_after(page: Sequence[dict[str, Any]], *, limit: int) -> PageCursor | None:
    """The cursor for the page after ``page``, or None when ``page`` was the last one.

    A full page might be followed by more rows; a short one cannot be.
    """
    if len(page) < limit:
        return None
    last = page[-1]
    return PageCursor(updated_at=last["updated_at"], key_hash=last["key_hash"])


__all__ = [
    "BATCH_ROWS",
    "MAX_PAGE_ROWS",
    "PAGE_FIELDS",
    "PAGE_SCHEMA",
    "InvalidCursor",
    "PageCursor",
    "count_rows",
    "cursor_after",
    "iter_page",
]

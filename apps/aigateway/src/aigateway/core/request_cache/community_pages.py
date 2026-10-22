"""Read the community cache one page at a time, in write order (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
Spec: ``docs/spec/2026-10-15-community-cache.md``.

A client walks the shareable rows of ``request_cache_entries`` page after page: each page is the
rows after a cursor, and the cursor is the last row's ``(updated_at, key_hash)``. Each page is
read in batches, every batch short keyset reads on the ``(updated_at, key_hash)`` index
(migration 0015) — the next keys and their sizes (after a cursor, two reads: the rest of its tie
run, then later rows; see ``_after``), then the rows themselves — so no connection or transaction
is held between batches and the caller can write each batch out before the next is read.
INVARIANT: a batch holds at most ``BATCH_BYTES`` of responses (or one row, if a single response is
larger) and at most ``BATCH_ROWS`` rows. The second query reads exactly the rows the first one
sized — same ``key_hash``, ``updated_at`` and size — so a row rewritten between the two (a merge
restore) is neither read at its new size nor sent out of order; it comes later in the walk, at its
new ``updated_at``. The page's ``next`` comes from the keys scanned (``PageScan``), not the rows
sent, so a row that moved or vanished between the queries cannot end the page early.
A response can be up to 1 MB (``AIGW_REQUEST_CACHE_MAX_RESPONSE_BYTES``), so a row count alone
would let one batch of the largest responses reach ~100 MB — several times that once the route
encodes it — against ~240 MiB of headroom on a gateway pod.

WHY write order: a row written while a walk is under way normally lands after the cursor, so the
same walk reaches it. ``updated_at`` rather than ``created_at`` because a merge restore inserts
rows with their source's ``created_at`` and overwrites rows without changing it; ``updated_at``
moves in both cases.
AIDEV-NOTE: two writes can land behind a walk's cursor and be missed by it (spec decision 13):
a write that commits after the cursor passed its ``updated_at`` (stamped before commit), and a
*replace* restore, which keeps the archive's ``updated_at``. Either row comes with the next
pull, which in v1 walks from the start.
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
from .tavily_retrieval import TAVILY_PROVIDER

PAGE_SCHEMA: Final = "screamingface.cache-page.v1"
MAX_PAGE_ROWS: Final = 5000
BATCH_ROWS: Final = 100
# WHY 8 MB: the route holds a batch about three times over while encoding it (rows, encoded
# lines, the joined chunk), so ~24 MB per request at most; a batch of typical rows (~3 KB) is
# still capped by ``BATCH_ROWS`` long before this.
BATCH_BYTES: Final = 8_000_000

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


@dataclass
class PageScan:
    """How far a page's scan got: the last key it read, whether or not that row was sent."""

    cursor: PageCursor | None = None


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
    rows = RequestCacheEntry.exclude(provider=TAVILY_PROVIDER).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    return rows.filter(model__in=list(models)) if models else rows


def _after(
    rows: QuerySet[RequestCacheEntry], cursor: PageCursor | None
) -> tuple[QuerySet[RequestCacheEntry], ...]:
    """What follows ``cursor``, in order: the rest of its tie run, then every later time.

    INVARIANT: ties on updated_at (a restore stamps many rows with one time) split by key_hash,
    so a page boundary inside a run of equal times skips and repeats nothing.
    WHY two ranges, not ``updated_at > X OR (updated_at = X AND key_hash > Y)``: that OR is no
    index range, so every batch walked the ``(updated_at, key_hash)`` index from its start and
    dropped the rows before the cursor (~1.4 s a batch 200k rows into dev's cache, where bulk
    restores stamped ~188k rows with one time). Each part here starts at the cursor (~1 ms).
    Tortoise has no row-value comparison, which would be one range.
    """
    if cursor is None:
        return (rows,)
    return (
        rows.filter(updated_at=cursor.updated_at, key_hash__gt=cursor.key_hash),
        rows.filter(updated_at__gt=cursor.updated_at),
    )


async def count_rows(*, after: PageCursor | None, models: Sequence[str], now: datetime) -> int:
    """How many rows a walk from ``after`` would return (approximate once writes continue)."""
    return sum([await part.count() for part in _after(_eligible(models, now), after)])


async def has_rows_after(*, after: PageCursor, models: Sequence[str], now: datetime) -> bool:
    """Whether any eligible row follows ``after`` — so a full page knows whether it was the last."""
    for part in _after(_eligible(models, now), after):
        if await part.exists():
            return True
    return False


def _within_bytes(sizes: list[dict[str, Any]]) -> int:
    """How many of the next rows fit in one batch: up to ``BATCH_BYTES``, and always one."""
    total = 0
    for taken, row in enumerate(sizes):
        total += max(0, row["response_size_bytes"] or 0)
        if taken and total > BATCH_BYTES:
            return taken
    return len(sizes)


async def _keys_in(part: QuerySet[RequestCacheEntry], n: int) -> list[dict[str, Any]]:
    return (
        await part.order_by(*_ORDER)
        .limit(n)
        .values("key_hash", "updated_at", "response_size_bytes")
    )


async def _next_keys(
    eligible: QuerySet[RequestCacheEntry], cursor: PageCursor | None, want: int
) -> tuple[list[dict[str, Any]], bool]:
    """The next keys after ``cursor`` (at most ``want``), and whether fewer than that remain.

    ``exhausted`` counts the keys read, before a duplicate is dropped, so a shorter list is not by
    itself the end of the rows.
    """
    keys: list[dict[str, Any]] = []
    for part in _after(eligible, cursor):
        keys += await _keys_in(part, want - len(keys))
        if len(keys) == want:
            break
    # WHY: the parts are read by separate statements, so a row a merge restore moves out of the
    # tie run between them can be read by both; its later copy is the row as it now stands. A
    # new copy beyond the later read leaves only the stale one, which ``_exactly`` then skips and
    # the walk sends at its new time.
    last = {key["key_hash"]: at for at, key in enumerate(keys)}
    return [key for at, key in enumerate(keys) if last[key["key_hash"]] == at], len(keys) < want


def _exactly(keys: Sequence[dict[str, Any]]) -> Q:
    return Q(
        *(
            Q(
                key_hash=key["key_hash"],
                updated_at=key["updated_at"],
                response_size_bytes=key["response_size_bytes"],
            )
            for key in keys
        ),
        join_type="OR",
    )


async def iter_page(
    *,
    after: PageCursor | None,
    limit: int,
    models: Sequence[str],
    now: datetime,
    scan: PageScan | None = None,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Yield one page of at most ``limit`` rows, in batches bounded by rows and bytes.

    ``scan``, when given, is kept at the last key read, which is where the next page starts.
    """
    eligible = _eligible(models, now)
    cursor = after
    left = limit
    while left > 0:
        want = min(BATCH_ROWS, left)
        sizes, exhausted = await _next_keys(eligible, cursor, want)
        if not sizes:
            return
        taken = sizes[: _within_bytes(sizes)]
        batch = await eligible.filter(_exactly(taken)).order_by(*_ORDER).values(*PAGE_FIELDS)
        # WHY the cursor and the count come from the keys, not the rows: a row rewritten or
        # deleted between the two queries is simply absent, and must neither end the page nor
        # move it backwards.
        left -= len(taken)
        cursor = PageCursor(updated_at=taken[-1]["updated_at"], key_hash=taken[-1]["key_hash"])
        if scan is not None:
            scan.cursor = cursor
        if batch:
            yield batch
        if exhausted and len(taken) == len(sizes):
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
    "BATCH_BYTES",
    "PageCursor",
    "PageScan",
    "count_rows",
    "cursor_after",
    "has_rows_after",
    "iter_page",
]

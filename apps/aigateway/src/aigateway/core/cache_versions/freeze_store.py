"""The Tortoise adapter of the freeze and export stores (OME-1307, GW-freeze).

FEATURE: OME-1307 (E14) - reads the capture, prompt and live-cache rows and writes one version.

INVARIANT: an entry and a version are immutable once written. This adapter only inserts them and
flips ``status`` from ``frozen`` to ``archived``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from ..request_cache.models import RequestCacheEntry
from .models import (
    CacheCaptureEntry,
    CacheVersion,
    CacheVersionBlob,
    CacheVersionEntry,
    RequestCachePrompt,
)
from .ports import (
    ArchiveEntry,
    CanonicalJson,
    CaptureRow,
    CoverageStatus,
    LiveAnswer,
    NewBlob,
    NewEntry,
    StoredVersion,
    VersionAlreadyExists,
)

# WHY 500: SQLite limits the number of bound variables in one statement.
_CHUNK = 500


def _chunks(values: Collection[str]) -> Iterator[list[str]]:
    items = sorted(values)
    for start in range(0, len(items), _CHUNK):
        yield items[start : start + _CHUNK]


def _stored(row: CacheVersion) -> StoredVersion:
    return StoredVersion(
        id=row.id,
        owner_account_id=row.owner_account_id,
        trace_id=row.trace_id,
        status=row.status,
        entry_count=row.entry_count,
        call_count=row.call_count,
        missing_count=row.missing_count,
        coverage_status=cast(CoverageStatus, row.coverage_status),
        archive_sha256=row.archive_sha256,
        archive_key=row.archive_key,
        created_at=row.created_at,
    )


def _archive_entries(
    rows: Sequence[tuple[str, int, str, str, str | None]],
) -> list[ArchiveEntry]:
    # INVARIANT: the stored columns are canonical text (the freeze wrote them from
    # `canonical_material`), so they are wrapped and NEVER parsed. The exporter's digest check
    # still catches a stored row that is not canonical.
    return [
        ArchiveEntry(
            key_hash=key_hash,
            first_ordinal=first_ordinal,
            request=CanonicalJson(request_json),
            response=CanonicalJson(response_json),
            metadata=CanonicalJson(metadata_json) if metadata_json is not None else None,
        )
        for key_hash, first_ordinal, request_json, response_json, metadata_json in rows
    ]


class TortoiseFreezeStore:
    async def find_version(self, owner_account_id: str, trace_id: str) -> StoredVersion | None:
        row = await CacheVersion.get_or_none(owner_account_id=owner_account_id, trace_id=trace_id)
        return _stored(row) if row is not None else None

    async def load_capture(self, account_id: str, trace_id: str) -> list[CaptureRow]:
        # INVARIANT (CV-D2): the account filter is part of the query, so another account's rows
        # are invisible and a foreign trace looks like an unknown one.
        rows = (
            await CacheCaptureEntry.filter(account_id=account_id, trace_id=trace_id)
            .order_by("ordinal")
            .values_list("ordinal", "key_hash", "outcome", "response_json")
        )
        return [CaptureRow(*row) for row in cast("list[tuple[Any, ...]]", rows)]

    async def load_prompts(self, key_hashes: Collection[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for chunk in _chunks(key_hashes):
            rows = await RequestCachePrompt.filter(key_hash__in=chunk).values_list(
                "key_hash", "request_json"
            )
            found.update(cast("list[tuple[str, str]]", rows))
        return found

    async def load_live_answers(self, key_hashes: Collection[str]) -> dict[str, LiveAnswer]:
        found: dict[str, LiveAnswer] = {}
        # Same rule as the live read (`request_cache.store`): a past `expires_at` is a miss.
        alive = Q(expires_at__isnull=True) | Q(expires_at__gt=datetime.now(UTC))
        for chunk in _chunks(key_hashes):
            rows = (
                await RequestCacheEntry.filter(alive, key_hash__in=chunk)
                .only("key_hash", "response_json", "metadata_json")
                .all()
            )
            for row in rows:
                found[row.key_hash] = LiveAnswer(row.response_json, row.metadata_json)
        return found

    async def load_blob_metadata(self, shas: Collection[str]) -> dict[str, str | None]:
        found: dict[str, str | None] = {}
        for chunk in _chunks(shas):
            rows = await CacheVersionBlob.filter(sha256__in=chunk).values_list(
                "sha256", "metadata_json"
            )
            found.update(cast("list[tuple[str, str | None]]", rows))
        return found

    async def insert_version(
        self, version: StoredVersion, blobs: Sequence[NewBlob], entries: Sequence[NewEntry]
    ) -> None:
        try:
            # WHY the explicit transaction: on Postgres a unique violation aborts the transaction it
            # happens in. The three writes stay all-or-nothing, and the loser leaves nothing behind.
            #
            # AIDEV-NOTE: the `except IntegrityError` below stays OUTSIDE the `async with`. Moving
            # it inside leaves the aborted Postgres transaction in place, and the next statement
            # fails with "current transaction is aborted" (same trap as `request_cache.store`).
            async with in_transaction():
                await CacheVersionBlob.bulk_create(
                    [
                        CacheVersionBlob(
                            sha256=b.sha256,
                            request_json=b.request_json,
                            response_json=b.response_json,
                            metadata_json=b.metadata_json,
                            size_bytes=b.size_bytes,
                        )
                        for b in blobs
                    ],
                    ignore_conflicts=True,  # a blob shared with an earlier version keeps its row
                    batch_size=_CHUNK,
                )
                await CacheVersion.create(
                    id=version.id,
                    owner_account_id=version.owner_account_id,
                    trace_id=version.trace_id,
                    status=version.status,
                    entry_count=version.entry_count,
                    call_count=version.call_count,
                    missing_count=version.missing_count,
                    coverage_status=version.coverage_status,
                    archive_sha256=version.archive_sha256,
                    archive_key=version.archive_key,
                    created_at=version.created_at,
                )
                await CacheVersionEntry.bulk_create(
                    [
                        CacheVersionEntry(
                            version_id=version.id,
                            key_hash=e.key_hash,
                            blob_id=e.blob_sha256,  # the native FK column name (D8)
                            first_ordinal=e.first_ordinal,
                        )
                        for e in entries
                    ],
                    batch_size=_CHUNK,
                )
        except IntegrityError as exc:
            raise VersionAlreadyExists from exc

    async def list_frozen(self, limit: int, exclude: Collection[UUID] = ()) -> list[StoredVersion]:
        query = CacheVersion.filter(status="frozen")
        if exclude:
            query = query.exclude(id__in=list(exclude))
        rows = await query.order_by("created_at").limit(limit)
        return [_stored(row) for row in rows]

    async def count_frozen(self) -> int:
        return await CacheVersion.filter(status="frozen").count()

    async def load_archive_entries(self, version_id: UUID) -> list[ArchiveEntry]:
        rows = cast(
            list[tuple[str, int, str, str, str | None]],
            await CacheVersionEntry.filter(version_id=version_id)
            .order_by("first_ordinal")
            .values_list(
                "key_hash",
                "first_ordinal",
                "blob__request_json",
                "blob__response_json",
                "blob__metadata_json",
            ),
        )
        return _archive_entries(rows)

    async def mark_archived(self, version_id: UUID) -> None:
        # INVARIANT: conditional, so two replicas that export one version cannot undo each other.
        await CacheVersion.filter(id=version_id, status="frozen").update(status="archived")

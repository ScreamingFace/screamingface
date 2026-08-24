"""Postgres bulk loader for cache snapshots: stage via COPY, then merge or replace (OME-952).

This is the SQL-direct half of the admin upload. A snapshot's COPY block is re-fed to Postgres
through asyncpg's COPY protocol — the server re-reads its own dump format, so no value is ever
parsed, unescaped, or re-serialised by this process (spec invariants 1 and 4).

WHY Tortoise is bypassed for the load: the ORM lane (``set_if_absent``) is row-by-row and
create-only by design, built for the request path. A snapshot is ~190k already-final rows whose
per-row guarantees (key validity, payload shape) were established by the gateway that wrote
them; moving them is a bulk COPY plus one set-based merge, seconds rather than minutes.

MERGE keeps the live row's identity and serving history (``id``, ``created_at``, ``hit_count``,
``last_hit_at``) and replaces only the content columns — the same create-or-replace discipline
as ``set_if_absent``: a stored answer may be replaced by its snapshot version, never removed.
REPLACE is a wholesale contents swap behind the caller's loss acknowledgement.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO, Final, Literal, NamedTuple, Protocol

from tortoise import Tortoise
from tortoise.backends.asyncpg.client import AsyncpgDBClient

from .snapshot import CopyBlockSource, open_snapshot_stream

_TABLE: Final = "request_cache_entries"
_STAGING: Final = "request_cache_entries_staging"
_BATCH_BYTES: Final = 1 << 20  # 1 MiB per asyncpg chunk — enough for throughput, small in memory.

# Column lists for the final INSERT statements. The staging side names every column (the dump
# carries all of them); on the merge target `id` is generated (`gen_random_uuid()`: snapshot
# ids belong to the deployment that wrote them, and fresh ids make cross-deployment id
# collisions impossible) and `updated_at` reads `now()` — the row changed here.
_MERGE_INSERT_COLUMNS: Final = (
    "id, key_hash, prompt_hash, provider, model, response_json, response_size_bytes, "
    "created_at, updated_at, expires_at, last_hit_at, hit_count"
)
_REPLACE_COLUMNS: Final = (
    "id, key_hash, prompt_hash, provider, model, response_json, response_size_bytes, "
    "created_at, updated_at, expires_at, last_hit_at, hit_count"
)

_MERGE_SQL: Final = f"""
INSERT INTO {_TABLE} ({_MERGE_INSERT_COLUMNS})
SELECT gen_random_uuid(), s.key_hash, s.prompt_hash, s.provider, s.model, s.response_json,
       s.response_size_bytes, s.created_at, now(), s.expires_at, s.last_hit_at, s.hit_count
  FROM {_STAGING} AS s
ON CONFLICT (key_hash) DO UPDATE SET
    prompt_hash         = EXCLUDED.prompt_hash,
    provider            = EXCLUDED.provider,
    model               = EXCLUDED.model,
    response_json       = EXCLUDED.response_json,
    response_size_bytes = EXCLUDED.response_size_bytes,
    expires_at          = EXCLUDED.expires_at,
    updated_at          = now()
"""

_REPLACE_SQL: Final = (
    f"INSERT INTO {_TABLE} ({_REPLACE_COLUMNS}) SELECT {_REPLACE_COLUMNS} FROM {_STAGING} AS s"
)


class CacheUploadUnsupportedDatabase(RuntimeError):
    """The active database is not Postgres, so the COPY protocol path cannot run."""


class StagedRowCountMismatch(RuntimeError):
    """The staged row count disagrees with the manifest's declared ``row_count``."""

    def __init__(self, staged: int, declared: int) -> None:
        self.staged = staged
        self.declared = declared
        super().__init__(f"staged {staged} rows but the manifest declared {declared}")


class ReplaceGuardBlocked(RuntimeError):
    """Replace would discard live rows written after the snapshot was taken."""

    def __init__(self, live: int, staged: int) -> None:
        self.live = live
        self.staged = staged
        super().__init__(
            f"the live table holds {live} rows but the snapshot carries {staged}; "
            f"{live - staged} row(s) newer than the snapshot would be destroyed"
        )


class LoadOutcome(NamedTuple):
    staged_rows: int
    live_before: int
    live_after: int


class _PhaseCallback(Protocol):
    async def __call__(self, phase: Literal["loading", "merging"]) -> None: ...


def _postgres_client() -> AsyncpgDBClient:
    client = Tortoise.get_connection("default")
    if not isinstance(client, AsyncpgDBClient):
        raise CacheUploadUnsupportedDatabase(
            "the cache snapshot loader speaks Postgres COPY; this deployment's database is "
            f"{type(client).__name__}"
        )
    return client


async def load_snapshot(
    path: Path,
    *,
    mode: Literal["merge", "replace"],
    expected_rows: int | None,
    acknowledge_loss: bool,
    on_phase: _PhaseCallback | None = None,
) -> LoadOutcome:
    """Stage, verify, and load one snapshot file into the live cache table.

    Raises before ANY live-table write: :class:`NoCopyBlock` / :class:`CopyHeaderMismatch`
    (no honest load possible), :class:`StagedRowCountMismatch` (manifest lied about its rows),
    :class:`ReplaceGuardBlocked` (replace would lose newer rows, unacknowledged). The caller
    maps each to the job's ``refused`` state.
    """
    if on_phase is not None:
        await on_phase("loading")

    client = _postgres_client()
    staged_rows = 0

    async with client.acquire_connection() as raw:
        # A staging twin, created once and TRUNCATEd per run: no indexes, no constraints, no
        # defaults — the dump supplies every column, and a bare copy of the column shape loads
        # fastest. Dropping it between runs would trade a CREATE per upload for nothing.
        await raw.execute(f"CREATE TABLE IF NOT EXISTS {_STAGING} (LIKE {_TABLE})")
        await raw.execute(f"TRUNCATE {_STAGING}")

        stream: BinaryIO = open_snapshot_stream(path)
        # The `finally` closes the (possibly gzip-wrapped) stream on every exit; the raw file
        # beneath a gzip wrapper is closed by the wrapper itself.
        try:
            source = CopyBlockSource(stream)
            await asyncio.to_thread(source.header)
            staged_rows = await _copy_stream_into_staging(raw, source)
        finally:
            await asyncio.to_thread(stream.close)

        if expected_rows is not None and staged_rows != expected_rows:
            raise StagedRowCountMismatch(staged_rows, expected_rows)

        live_before: int = await raw.fetchval(f"SELECT count(*) FROM {_TABLE}")  # type: ignore[assignment]

        if mode == "replace" and live_before > staged_rows and not acknowledge_loss:
            raise ReplaceGuardBlocked(live_before, staged_rows)

        if on_phase is not None:
            await on_phase("merging")

        # One transaction for the load: readers see the old contents until commit (MVCC), and
        # a mid-load failure leaves the live table untouched rather than half-replaced.
        async with raw.transaction():
            if mode == "merge":
                await raw.execute(_MERGE_SQL)
            else:
                await raw.execute(f"TRUNCATE {_TABLE}")
                await raw.execute(_REPLACE_SQL)
            live_after: int = await raw.fetchval(f"SELECT count(*) FROM {_TABLE}")  # type: ignore[assignment]

        await raw.execute(f"TRUNCATE {_STAGING}")

    return LoadOutcome(staged_rows=staged_rows, live_before=live_before, live_after=live_after)


def _read_batch(source: CopyBlockSource) -> bytes:
    """Accumulate data lines into ~1 MiB, newline-terminated, bytes verbatim (thread-side)."""
    buffer = bytearray()
    for line in source.data_lines():
        buffer += line
        if len(buffer) >= _BATCH_BYTES:
            break
    return bytes(buffer)


async def _copy_stream_into_staging(raw: object, source: CopyBlockSource) -> int:
    """Feed the block to Postgres COPY; return the row count actually delivered."""
    rows = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal rows
        while True:
            # gzip reads are blocking; keep them off the event loop the gateway serves on.
            chunk = await asyncio.to_thread(_read_batch, source)
            if not chunk:
                return
            rows += chunk.count(b"\n")
            yield chunk

    await raw.copy_to_table(  # type: ignore[attr-defined]
        _STAGING, source=chunks(), timeout=600
    )
    return rows


__all__ = [
    "CacheUploadUnsupportedDatabase",
    "LoadOutcome",
    "ReplaceGuardBlocked",
    "StagedRowCountMismatch",
    "load_snapshot",
]

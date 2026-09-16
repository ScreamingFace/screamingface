"""Postgres bulk loader for cache snapshots: stage via COPY, then merge or replace (OME-952).

This is the SQL-direct half of the admin upload. A snapshot's COPY block is re-fed to Postgres
through asyncpg's COPY protocol — the server re-reads its own dump format, so no value is ever
parsed, unescaped, or re-serialised by this process (spec invariants 1 and 4).

WHY Tortoise is bypassed for the load: the ORM lane (``set_if_absent``) is row-by-row and
create-only by design, built for the request path. A snapshot is ~190k already-final rows whose
per-row guarantees (key validity, payload shape) were established by the gateway that wrote
them; moving them is a bulk COPY plus one set-based merge, seconds rather than minutes.

MERGE keeps the live row's identity and serving history (``id``, ``created_at``, ``hit_count``,
``last_hit_at``) and replaces only the content columns — ``response_json``, ``metadata_json`` and
the rest — the same create-or-replace discipline
as ``set_if_absent``: a stored answer may be replaced by its snapshot version, never removed.
REPLACE is a wholesale contents swap behind the caller's loss acknowledgement.

TWO ARCHIVE LAYOUTS are accepted (``snapshot.ACCEPTED_COLUMN_LAYOUTS``): the current 13-column
layout and the 12-column layout written before the metadata column existed. The COPY names the
columns the dump's own header lists, so a legacy row leaves ``metadata_json`` NULL instead of
being padded with an invented block.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO, Final, Literal, NamedTuple, Protocol

from tortoise import Tortoise
from tortoise.backends.asyncpg.client import AsyncpgDBClient

from .snapshot import CopyBlockSource, open_snapshot_stream

logger = logging.getLogger(__name__)

_TABLE: Final = "request_cache_entries"
_STAGING: Final = "request_cache_entries_staging"
_BATCH_BYTES: Final = 1 << 20  # 1 MiB per asyncpg chunk — enough for throughput, small in memory.

# Column lists for the final INSERT statements. The staging side names every column (the dump
# carries all of them); on the merge target `id` is generated (`gen_random_uuid()`: snapshot
# ids belong to the deployment that wrote them, and fresh ids make cross-deployment id
# collisions impossible) and `updated_at` reads `now()` — the row changed here.
_MERGE_INSERT_COLUMNS: Final = (
    "id, key_hash, prompt_hash, provider, model, response_json, response_size_bytes, "
    "created_at, updated_at, expires_at, last_hit_at, hit_count, metadata_json"
)
_REPLACE_COLUMNS: Final = (
    "id, key_hash, prompt_hash, provider, model, response_json, response_size_bytes, "
    "created_at, updated_at, expires_at, last_hit_at, hit_count, metadata_json"
)

_MERGE_SQL: Final = f"""
INSERT INTO {_TABLE} ({_MERGE_INSERT_COLUMNS})
SELECT gen_random_uuid(), s.key_hash, s.prompt_hash, s.provider, s.model, s.response_json,
       s.response_size_bytes, s.created_at, now(), s.expires_at, s.last_hit_at, s.hit_count,
       s.metadata_json
  FROM {_STAGING} AS s
ON CONFLICT (key_hash) DO UPDATE SET
    prompt_hash         = EXCLUDED.prompt_hash,
    provider            = EXCLUDED.provider,
    model               = EXCLUDED.model,
    response_json       = EXCLUDED.response_json,
    response_size_bytes = EXCLUDED.response_size_bytes,
    metadata_json       = EXCLUDED.metadata_json,
    expires_at          = EXCLUDED.expires_at,
    updated_at          = now()
"""

_REPLACE_SQL: Final = (
    f"INSERT INTO {_TABLE} ({_REPLACE_COLUMNS}) SELECT {_REPLACE_COLUMNS} FROM {_STAGING} AS s"
)

# WHY this count exists: the merge above sets `metadata_json = EXCLUDED.metadata_json`, and for a
# legacy 12-column archive EXCLUDED is NULL — so a restore silently turns priced rows back into
# unknown ones (ERD E7). That is intended and irreversible for the row; what was missing is any
# signal AT THE MOMENT IT HAPPENS. Without it the only trace is `cache.saved_cost.unpriced_hits`
# drifting upward on a later engine run, which points the operator at the engine rather than at
# the restore that caused it.
# INVARIANT: counts rows the merge DEGRADES — a live block this load turns to NULL — never rows
# that were already unknown, and never rows the archive does not mention.
#
# There are TWO ways a row degrades, and round 2 counted only the first (review round 3, finding
# 4). The second arm mirrors the stale-metadata TRIGGER's own `WHEN` clause, substituting the
# merge's `EXCLUDED` (which is `s`) for `NEW` and the live row (`t`) for `OLD`:
#
#   arm 1 — the archive carries NO block: `EXCLUDED.metadata_json` is NULL and the SET writes
#           NULL straight onto the row.
#   arm 2 — the archive carries the SAME block beside a DIFFERENT response: the SET leaves
#           `metadata_json` unchanged while `response_json` changes, which is precisely the
#           trigger's firing condition, and the trigger then clears the block to NULL.
#
# Without arm 2 a load could clear blocks and still report `metadata_degraded = 0` — a figure the
# API documents as "this load degraded nothing", which is the one reading it must never support.
#
# AIDEV-NOTE: the `response_json` comparison in arm 2 DETOASTS both sides for every colliding row.
# Deliberate, and not a regression of the hot-path detoast fix in the trigger's column list: this
# statement runs once per merge, off the serving path. Do not copy it into anything a hit reaches.
_DEGRADED_COUNT_SQL: Final = f"""
SELECT count(*)
  FROM {_TABLE} AS t
  JOIN {_STAGING} AS s USING (key_hash)
 WHERE t.metadata_json IS NOT NULL
   AND (s.metadata_json IS NULL
        OR (s.response_json IS DISTINCT FROM t.response_json
            AND s.metadata_json IS NOT DISTINCT FROM t.metadata_json))
"""

# INVARIANT: the load never blocks serving (OME-951 spec §7). Round 2 took SHARE ROW EXCLUSIVE on
# the live table for the merge's whole duration to make the count above EXACT. That mode conflicts
# with the ROW EXCLUSIVE every cache hit takes to bump `hit_count`/`last_hit_at` — and the store
# AWAITS that bump before returning the cached body — so every hit stalled until the merge
# committed. Sharpening a telemetry field does not justify suspending an approved availability
# contract (review round 3, finding 2), so the lock is gone and the count is a LOWER BOUND.
#
# What that costs, precisely: the count and the merge are two statements, and READ COMMITTED gives
# each its own snapshot while `ON CONFLICT DO UPDATE` re-reads the latest committed row. A fill
# that commits between them is degraded but uncounted. The error is one-directional — the figure
# can UNDERSTATE the damage, never overstate it — which is the safe direction for a number an
# operator acts on: it never blames a restore for a degradation that did not happen.
#
# AIDEV-NOTE: do not "fix" the bound by reintroducing a table lock. Exactness here needs an
# approved change to the snapshot contract first, not a lock added under a telemetry rationale.
# Row-level `SELECT … FOR UPDATE` over the colliding join was considered and rejected for round 3:
# it cannot lock a row that does not exist yet, so it buys accuracy under concurrency without
# reaching exactness — the published wording stays "at least" either way.


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
    # How many live rows this load was OBSERVED to turn from "priced" back to "unknown" (ERD E7).
    # A lower bound — see `_DEGRADED_COUNT_SQL`. Merge only:
    # replace discards the whole table by contract, behind the caller's own loss acknowledgement,
    # so per-row degradation is not the fact being reported there.
    metadata_degraded: int = 0


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
        # A staging twin left behind by a gateway that pre-dates the metadata column is 12
        # columns wide, and `CREATE TABLE IF NOT EXISTS` will not widen it — the next 13-column
        # COPY would then fail on the missing column. Idempotent, and a no-op on a fresh twin.
        await raw.execute(f"ALTER TABLE {_STAGING} ADD COLUMN IF NOT EXISTS metadata_json TEXT")
        await raw.execute(f"TRUNCATE {_STAGING}")

        stream: BinaryIO = open_snapshot_stream(path)
        # The `finally` closes the (possibly gzip-wrapped) stream on every exit; the raw file
        # beneath a gzip wrapper is closed by the wrapper itself.
        try:
            source = CopyBlockSource(stream)
            # The dump's OWN header names the columns the data lines carry — the current 13, or
            # the legacy 12. Feeding exactly those to COPY is what makes a legacy row load with
            # metadata_json NULL rather than be refused or padded.
            columns = await asyncio.to_thread(source.header)
            staged_rows = await _copy_stream_into_staging(raw, source, columns=columns)
        finally:
            await asyncio.to_thread(stream.close)

        if expected_rows is not None and staged_rows != expected_rows:
            raise StagedRowCountMismatch(staged_rows, expected_rows)

        live_before: int = await raw.fetchval(f"SELECT count(*) FROM {_TABLE}")  # type: ignore[assignment]

        if mode == "replace" and live_before > staged_rows and not acknowledge_loss:
            raise ReplaceGuardBlocked(live_before, staged_rows)

        if on_phase is not None:
            await on_phase("merging")

        metadata_degraded = 0

        # One transaction for the load: readers see the old contents until commit (MVCC), and
        # a mid-load failure leaves the live table untouched rather than half-replaced.
        async with raw.transaction():
            if mode == "merge":
                # Counted BEFORE the merge, inside the same transaction: afterwards the live
                # block is already gone and the two states are indistinguishable. Nothing locks
                # the gap between this statement and the merge below — the count is a lower
                # bound by design; see `_DEGRADED_COUNT_SQL` for why that beats a stalled cache.
                metadata_degraded = await raw.fetchval(_DEGRADED_COUNT_SQL) or 0
                await raw.execute(_MERGE_SQL)
            else:
                await raw.execute(f"TRUNCATE {_TABLE}")
                await raw.execute(_REPLACE_SQL)
            live_after: int = await raw.fetchval(f"SELECT count(*) FROM {_TABLE}")  # type: ignore[assignment]

        await raw.execute(f"TRUNCATE {_STAGING}")

    if metadata_degraded:
        logger.warning(
            "cache snapshot merge degraded at least %d of %d row(s) to unknown metadata: the "
            "archive carries no block for them, or replaces their response while carrying the "
            "block they already had, so what those responses cost is no longer recorded",
            metadata_degraded,
            staged_rows,
        )

    return LoadOutcome(
        staged_rows=staged_rows,
        live_before=live_before,
        live_after=live_after,
        metadata_degraded=metadata_degraded,
    )


def _read_batch(source: CopyBlockSource) -> bytes:
    """Accumulate data lines into ~1 MiB, newline-terminated, bytes verbatim (thread-side)."""
    buffer = bytearray()
    for line in source.data_lines():
        buffer += line
        if len(buffer) >= _BATCH_BYTES:
            break
    return bytes(buffer)


async def _copy_stream_into_staging(
    raw: object, source: CopyBlockSource, *, columns: tuple[str, ...]
) -> int:
    """Feed the block to Postgres COPY; return the row count actually delivered.

    ``columns`` is the dump's own header list, so the column set is never guessed here.
    """
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
        _STAGING, source=chunks(), columns=columns, timeout=600
    )
    return rows


__all__ = [
    "CacheUploadUnsupportedDatabase",
    "LoadOutcome",
    "ReplaceGuardBlocked",
    "StagedRowCountMismatch",
    "load_snapshot",
]

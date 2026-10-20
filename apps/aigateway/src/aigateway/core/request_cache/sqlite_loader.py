"""Load community-cache pages into a local SQLite gateway (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, each page I pull lands in my local cache and is
served as an ordinary hit, without disturbing what I already had.
Spec: ``docs/spec/2026-10-15-community-cache.md`` (decisions 10 and 11).

The client process calls this between downloads, so it is plain ``sqlite3`` against the local
gateway's database file — no ORM registry, no running gateway. Rows arrive as the wire's JSON
objects (``community_pages.PAGE_FIELDS``) and are written in the storage format the gateway's ORM
uses, so the gateway reads them back as its own.

INVARIANT: one transaction per ``load_page`` call, and a key the local cache already holds is
kept, never replaced (``ON CONFLICT(key_hash) DO NOTHING``). Reloading rows therefore adds
nothing, which is what makes resuming after a crash safe.
INVARIANT: only a row a local lookup can serve is written (``_parameters``): both hashes are
SHA-256 hex, the text fields fit their columns, ``response_json`` passes the lookup's own decoder
(``store.decode_cached_response``), the size and timestamps are coherent, and the row has not
expired. Because a kept key is never replaced, a row written that could not be served would hold
its key unservable for good.
WHY a row that fails is skipped and counted rather than refusing the call (owner decision,
2026-10-20): rows are independent cache entries, and a pull resumes from the same cursor, so a
refusal would stop every pull at that row until the hosted side was fixed. A skipped row is not
written, so a later valid row for its key still loads.
AIDEV-NOTE: the SDK calls ``load_page`` once per 500-row batch as a page streams in, not once per
page. A transaction spanning a page would hold the write lock for the page's whole download, and
the running gateway's own writes wait only 5 s for it (SQLite WAL, Tortoise's default).
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .entry_metadata import CACHE_ENTRY_METADATA_MAX_BYTES, CacheEntryMetadata
from .revisions import PARAMETER_CONTRACT_KEY
from .store import decode_cached_response

_TABLE: Final = "request_cache_entries"
_COLUMNS: Final = (
    "id",
    "key_hash",
    "prompt_hash",
    "provider",
    "model",
    "response_json",
    "response_size_bytes",
    "created_at",
    "updated_at",
    "expires_at",
    "last_hit_at",
    "hit_count",
    "metadata_json",
)
_INSERT: Final = (
    f"INSERT INTO {_TABLE} ({', '.join(_COLUMNS)})"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)"
    " ON CONFLICT(key_hash) DO NOTHING"
)
_HASH = re.compile(r"[0-9a-f]{64}")
# The model's column lengths (``models/request_cache_entry.py``).
_PROVIDER_MAX: Final = 64
_MODEL_MAX: Final = 255
# WHY a sanity bound, not the hosted cap: the cap (`AIGW_REQUEST_CACHE_MAX_RESPONSE_BYTES`, 1 MB
# by default) is the hosted gateway's setting and this process cannot read it. 16 MiB refuses
# nonsense without refusing any row a hosted gateway could have written.
_RESPONSE_MAX_BYTES: Final = 16 * 1024 * 1024


class PageRejected(ValueError):
    """A page, or the database it was meant for, cannot be loaded. ``reason`` names why."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class PageLoad:
    rows: int
    inserted: int
    # Rows that failed validation and were not written (``_parameters``).
    skipped: int = 0


def check_revisions(remote: Mapping[str, str], local: Mapping[str, str]) -> None:
    """Refuse a page whose cache keys were computed under revisions this gateway does not use.

    A revision both sides report must be equal, and the core parameter contract must be on
    both. The two one-sided cases are not symmetric:

    - Only the hosted side reports it: allowed. A local process may load fewer provider plugins
      than the hosted gateway, and rows for a provider it lacks are never looked up there, so
      they cannot mis-hit.
    - Only the local side reports it: refused. The hosted gateway may still hold rows for an
      adapter it no longer loads, keyed under a revision it cannot vouch for; they would load
      here and never hit.
    """
    if PARAMETER_CONTRACT_KEY not in remote or PARAMETER_CONTRACT_KEY not in local:
        raise PageRejected("revision_mismatch", f"{PARAMETER_CONTRACT_KEY} missing on one side")
    differing = sorted(k for k in remote.keys() & local.keys() if remote[k] != local[k])
    if differing:
        raise PageRejected("revision_mismatch", f"differs for {', '.join(differing)}")
    # AIDEV-NOTE: a plugin that only ever runs locally and registers a revision would trip this
    # on every pull; refine the rule (e.g. per provider) before adding one.
    unvouched = sorted(local.keys() - remote.keys())
    if unvouched:
        raise PageRejected("revision_mismatch", f"not reported upstream: {', '.join(unvouched)}")


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("a timestamp is not text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("a timestamp has no time zone")
    # WHY OverflowError here: a valid ISO date at the calendar's edge with a large offset (for
    # example ``0001-01-01T00:00:00+14:00``) cannot be expressed in UTC.
    try:
        return parsed.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("a timestamp is outside the UTC range") from exc


def _stored(instant: datetime) -> str:
    # The ORM's SQLite storage format: '2026-10-01 12:00:00.123456+00:00'.
    return instant.isoformat(sep=" ", timespec="microseconds")


def _text(row: Mapping[str, Any], field: str, max_length: int) -> str:
    value = row[field]
    if not isinstance(value, str) or not 0 < len(value) <= max_length:
        raise ValueError(f"{field} is not text of 1 to {max_length} characters")
    return value


def _metadata(value: Any) -> str | None:
    # WHY NULL rather than skipping the row: a lookup treats an unreadable block as absent and
    # still serves the body (ERD §5.5), so storing NULL is what it would read anyway.
    if not isinstance(value, str) or len(value.encode()) > CACHE_ENTRY_METADATA_MAX_BYTES:
        return None
    return value if CacheEntryMetadata.parse(value) is not None else None


def _parameters(row: Mapping[str, Any], now: datetime) -> tuple[Any, ...]:
    """The insert parameters of a row a local lookup can serve; ``ValueError`` otherwise."""
    for field in ("key_hash", "prompt_hash"):
        if not isinstance(row[field], str) or not _HASH.fullmatch(row[field]):
            raise ValueError(f"{field} is not a SHA-256 hex digest")
    response = row["response_json"]
    if not isinstance(response, str) or len(response.encode()) > _RESPONSE_MAX_BYTES:
        raise ValueError("response_json is not text within bounds")
    decode_cached_response(response)
    size = row["response_size_bytes"]
    if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= _RESPONSE_MAX_BYTES:
        raise ValueError("response_size_bytes is not a size within bounds")
    created, updated = _instant(row["created_at"]), _instant(row["updated_at"])
    expires = None if row["expires_at"] is None else _instant(row["expires_at"])
    if expires is not None and expires <= now:
        raise ValueError("the row has expired")
    return (
        str(uuid.uuid4()),
        row["key_hash"],
        row["prompt_hash"],
        _text(row, "provider", _PROVIDER_MAX),
        _text(row, "model", _MODEL_MAX),
        response,
        size,
        _stored(created),
        _stored(updated),
        None if expires is None else _stored(expires),
        _metadata(row["metadata_json"]),
    )


def _valid(row: Mapping[str, Any], now: datetime) -> tuple[Any, ...] | None:
    try:
        return _parameters(row, now)
    except (KeyError, TypeError, ValueError, RecursionError):
        return None


def _check_schema(conn: sqlite3.Connection, database: Path) -> None:
    # WHY the columns, not only the table: a local gateway not started since a migration that
    # added a column (0011's metadata_json) has the table, and the INSERT would fail with a raw
    # sqlite3.OperationalError instead of a reason the client can explain.
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({_TABLE})")}
    if not present:
        raise PageRejected("not_a_gateway_database", f"{database} has no {_TABLE} table")
    missing = [column for column in _COLUMNS if column not in present]
    if missing:
        raise PageRejected(
            "outdated_gateway_database",
            f"{database} lacks {', '.join(missing)}; apply the gateway's migrations to it first",
        )
    # WHY: ``ON CONFLICT(key_hash)`` needs a unique index on exactly ``key_hash``; a table without
    # one would pass the column check and then fail every insert with a raw OperationalError.
    if not _has_unique_key_hash(conn):
        raise PageRejected("not_a_gateway_database", f"{database} has no unique key on key_hash")


def _has_unique_key_hash(conn: sqlite3.Connection) -> bool:
    for index in conn.execute(f"PRAGMA index_list({_TABLE})"):
        name, unique = index[1], index[2]
        columns = [column[2] for column in conn.execute(f"PRAGMA index_info('{name}')")]
        if unique and columns == ["key_hash"]:
            return True
    return False


def check_database(database: Path) -> None:
    """Refuse a database a pull could not load into, before anything is downloaded.

    WHY ``mode=rw``: a plain connect creates a missing file, which would leave an empty
    ``aigateway.sqlite3`` behind for the gateway to find.
    """
    try:
        conn = sqlite3.connect(f"{database.resolve().as_uri()}?mode=rw", uri=True, timeout=30.0)
    except sqlite3.OperationalError as exc:
        raise PageRejected("not_a_gateway_database", f"{database} cannot be opened: {exc}") from exc
    with closing(conn):
        _check_schema(conn, database)


def load_page(rows: Sequence[Mapping[str, Any]], database: Path) -> PageLoad:
    """Insert the servable rows into the local gateway database, in one transaction.

    A row that fails validation is skipped and counted in ``PageLoad.skipped``; it never stops
    the load (see the module's WHY).
    """
    now = datetime.now(UTC)
    checked = [_valid(row, now) for row in rows]
    parameters = [values for values in checked if values is not None]
    with closing(sqlite3.connect(database, timeout=30.0)) as conn, conn:
        _check_schema(conn, database)
        before = conn.total_changes
        conn.executemany(_INSERT, parameters)
        return PageLoad(
            rows=len(checked),
            inserted=conn.total_changes - before,
            skipped=len(checked) - len(parameters),
        )


__all__ = ["PageLoad", "PageRejected", "check_database", "check_revisions", "load_page"]

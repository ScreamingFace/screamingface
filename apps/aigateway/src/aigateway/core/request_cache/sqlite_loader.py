"""Load community-cache pages into a local SQLite gateway (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, each page I pull lands in my local cache and is
served as an ordinary hit, without disturbing what I already had.
Spec: ``docs/spec/2026-10-15-community-cache.md`` (decisions 10 and 11).

The client process calls this between downloads, so it is plain ``sqlite3`` against the local
gateway's database file — no ORM registry, no running gateway. Rows arrive as the wire's JSON
objects (``community_pages.PAGE_FIELDS``) and are written in the storage format the gateway's ORM
uses, so the gateway reads them back as its own.

INVARIANT: one transaction per page, and a key the local cache already holds is kept, never
replaced (``ON CONFLICT(key_hash) DO NOTHING``). Reloading a page therefore adds nothing, which
is what makes resuming after a crash safe.
WHY a malformed row rolls back only its page: rows are independent cache entries, so pages
already committed leave a correct, smaller cache.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .revisions import PARAMETER_CONTRACT_KEY

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
_TEXT_FIELDS: Final = ("key_hash", "prompt_hash", "provider", "model", "response_json")


class PageRejected(ValueError):
    """A page, or the database it was meant for, cannot be loaded. ``reason`` names why."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class PageLoad:
    rows: int
    inserted: int


def check_revisions(remote: Mapping[str, str], local: Mapping[str, str]) -> None:
    """Refuse a page whose cache keys were computed under revisions this gateway does not use.

    A revision both sides report must be equal, and the core parameter contract must be on
    both. An adapter revision only one side reports is not a mismatch: a local process may load
    fewer provider plugins than the hosted gateway, and rows for a provider it lacks are never
    looked up there, so they cannot mis-hit.
    """
    if PARAMETER_CONTRACT_KEY not in remote or PARAMETER_CONTRACT_KEY not in local:
        raise PageRejected("revision_mismatch", f"{PARAMETER_CONTRACT_KEY} missing on one side")
    differing = sorted(k for k in remote.keys() & local.keys() if remote[k] != local[k])
    if differing:
        raise PageRejected("revision_mismatch", f"differs for {', '.join(differing)}")


def _timestamp(value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"not an ISO timestamp: {value!r}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {value!r}")
    # The ORM's SQLite storage format: '2026-10-01 12:00:00.123456+00:00'.
    return parsed.astimezone(UTC).isoformat(sep=" ", timespec="microseconds")


def _parameters(row: Mapping[str, Any]) -> tuple[Any, ...]:
    for field in _TEXT_FIELDS:
        if not isinstance(row[field], str):
            raise ValueError(f"{field} is not text")
    size = row["response_size_bytes"]
    if not isinstance(size, int) or isinstance(size, bool):
        raise ValueError("response_size_bytes is not an integer")
    metadata = row["metadata_json"]
    if metadata is not None and not isinstance(metadata, str):
        raise ValueError("metadata_json is not text")
    return (
        str(uuid.uuid4()),
        *(row[field] for field in _TEXT_FIELDS),
        size,
        _timestamp(row["created_at"]),
        _timestamp(row["updated_at"]),
        _timestamp(row["expires_at"], nullable=True),
        metadata,
    )


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


def load_page(rows: Sequence[Mapping[str, Any]], database: Path) -> PageLoad:
    """Insert one page's rows into the local gateway database, in one transaction."""
    try:
        parameters = [_parameters(row) for row in rows]
    except (KeyError, ValueError) as exc:
        raise PageRejected("malformed_row", str(exc)) from exc
    with closing(sqlite3.connect(database, timeout=30.0)) as conn, conn:
        _check_schema(conn, database)
        before = conn.total_changes
        conn.executemany(_INSERT, parameters)
        return PageLoad(rows=len(parameters), inserted=conn.total_changes - before)


__all__ = ["PageLoad", "PageRejected", "check_revisions", "load_page"]

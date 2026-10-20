"""Loading community-cache pages into a local SQLite gateway (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, each page I pull lands in my local cache and is
served as an ordinary hit, without disturbing what I already had.

Pinned here: a page round-trips into a table the gateway's ORM created and reads back through
that ORM unchanged (text verbatim, timestamps, NULLs), with a fresh id and no hit history; a key
the local cache already holds is kept, never replaced; reloading a page adds nothing; a row a
local lookup could not serve is skipped and counted, never written, so a later valid row for its
key still loads (owner decision, 2026-10-20); a file that is not a gateway database, or has no
unique key on ``key_hash``, is refused; and revisions are compared before any row is read.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.sqlite_loader import (
    PageLoad,
    PageRejected,
    check_database,
    check_revisions,
    load_page,
)
from aigateway.db import build_tortoise_config

_TEXT = '{"choices": [{"message": {"content": "tab\\there, quote \\" and \\u00e9"}}]}'
_METADATA = CacheEntryMetadata(metadata_status="complete").serialize()


def _row(key: str = "a", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key_hash": key.ljust(64, "0"),
        "prompt_hash": "f" * 64,
        "provider": "openrouter",
        "model": "openrouter/anthropic/claude-opus-5.5",
        "response_json": _TEXT,
        "response_size_bytes": len(_TEXT),
        "created_at": "2026-10-01T12:00:00.123456+00:00",
        "updated_at": "2026-10-02T08:30:00+00:00",
        "expires_at": None,
        "metadata_json": _METADATA,
    }
    row.update(overrides)
    return row


@pytest_asyncio.fixture
async def database(tmp_path: Path):
    """A local gateway database whose table the gateway's own ORM created."""
    path = tmp_path / "aigateway.sqlite3"
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{path}"), _enable_global_fallback=True
    )
    await Tortoise.generate_schemas()
    yield path
    await Tortoise.close_connections()


# --- loading -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_page_reads_back_through_the_orm_unchanged(database: Path) -> None:
    outcome = load_page([_row("a"), _row("b", expires_at="2027-01-01T00:00:00+00:00")], database)

    assert outcome == PageLoad(rows=2, inserted=2)
    a = await RequestCacheEntry.get(key_hash="a".ljust(64, "0"))
    b = await RequestCacheEntry.get(key_hash="b".ljust(64, "0"))
    assert a.response_json == _TEXT
    assert a.response_size_bytes == len(_TEXT)
    assert a.created_at == datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)
    assert a.updated_at == datetime(2026, 10, 2, 8, 30, tzinfo=UTC)
    assert a.expires_at is None
    assert b.expires_at == datetime(2027, 1, 1, tzinfo=UTC)
    assert a.metadata_json == _METADATA
    assert (a.hit_count, a.last_hit_at) == (0, None)
    assert isinstance(a.id, uuid.UUID) and a.id != b.id


@pytest.mark.asyncio
async def test_a_key_already_held_locally_is_kept(database: Path) -> None:
    local = await RequestCacheEntry.create(
        key_hash="a".ljust(64, "0"),
        prompt_hash="p" * 64,
        provider="openrouter",
        model="m",
        response_json='{"local": true}',
        response_size_bytes=15,
        hit_count=4,
    )

    outcome = load_page([_row("a"), _row("b")], database)

    assert outcome == PageLoad(rows=2, inserted=1)
    kept = await RequestCacheEntry.get(key_hash="a".ljust(64, "0"))
    assert (kept.id, kept.response_json, kept.hit_count) == (local.id, '{"local": true}', 4)


@pytest.mark.asyncio
async def test_reloading_a_page_adds_nothing(database: Path) -> None:
    page = [_row("a"), _row("b")]
    load_page(page, database)

    assert load_page(page, database) == PageLoad(rows=2, inserted=0)
    assert await RequestCacheEntry.all().count() == 2


@pytest.mark.asyncio
async def test_an_empty_page_is_a_no_op(database: Path) -> None:
    assert load_page([], database) == PageLoad(rows=0, inserted=0)


# --- refusals ------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"key_hash": None},
        {"key_hash": "Z" * 64},
        {"key_hash": "a" * 63},
        {"prompt_hash": "not-a-digest"},
        {"provider": ""},
        {"provider": "p" * 65},
        {"model": "m" * 256},
        {"response_json": 12},
        {"response_json": "not-json"},
        {"response_json": "[1, 2]"},
        {"response_json": '{"x": NaN}'},
        {"response_size_bytes": "12"},
        {"response_size_bytes": True},
        {"response_size_bytes": -7},
        {"created_at": "yesterday"},
        {"updated_at": "2026-10-02T08:30:00"},  # naive: no place on the UTC timeline
        {"created_at": "0001-01-01T00:00:00+14:00"},  # valid ISO, outside the UTC range
        {"expires_at": 5},
        {"expires_at": "2000-01-01T00:00:00+00:00"},  # already expired
    ],
)
async def test_a_row_a_lookup_could_not_serve_is_skipped_and_counted(
    database: Path, bad: dict[str, Any]
) -> None:
    # WHY skip, not refuse (owner decision, 2026-10-20): a refusal would stop every pull at this
    # row, while the valid rows beside it are independent entries worth loading.
    outcome = load_page([_row("a"), _row("b", **bad)], database)

    assert outcome == PageLoad(rows=2, inserted=1, skipped=1)
    assert [e.key_hash[0] for e in await RequestCacheEntry.all()] == ["a"]


@pytest.mark.asyncio
async def test_a_row_missing_a_field_is_skipped(database: Path) -> None:
    row = _row("a")
    del row["model"]

    assert load_page([row], database) == PageLoad(rows=1, inserted=0, skipped=1)


@pytest.mark.asyncio
async def test_a_skipped_row_does_not_hold_its_key_against_a_later_valid_row(
    database: Path,
) -> None:
    # INVARIANT: a kept key is never replaced, so an unservable row written once would hold its
    # key unservable for good. Skipping it leaves the key free for the next valid row.
    load_page([_row("a", response_json="not-json", response_size_bytes=-7)], database)

    assert load_page([_row("a")], database) == PageLoad(rows=1, inserted=1, skipped=0)
    assert (await RequestCacheEntry.get(key_hash="a".ljust(64, "0"))).response_json == _TEXT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    ["not-json", '{"schema": "aigw.cache-entry-metadata.v1"}', 12, "x" * 100_000],
)
async def test_unreadable_or_oversized_metadata_is_stored_as_null(
    database: Path, metadata: object
) -> None:
    # WHY NULL, not a skipped row: a lookup treats an unreadable block as absent and still serves
    # the body, so NULL is what it would read anyway.
    assert load_page([_row("a", metadata_json=metadata)], database).inserted == 1
    assert (await RequestCacheEntry.get(key_hash="a".ljust(64, "0"))).metadata_json is None


def test_a_file_that_is_not_a_gateway_database_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "other.sqlite3"
    with sqlite3.connect(other) as conn:
        conn.execute("create table something_else (x)")

    with pytest.raises(PageRejected) as refused:
        load_page([_row("a")], other)

    assert refused.value.reason == "not_a_gateway_database"


def test_a_gateway_database_from_before_the_metadata_column_is_refused(tmp_path: Path) -> None:
    # WHY: a local gateway not started since migration 0011 has the table but no
    # metadata_json column; the client must get a PageRejected it can explain, not a raw
    # sqlite3.OperationalError from the INSERT.
    old = tmp_path / "old.sqlite3"
    with sqlite3.connect(old) as conn:
        conn.execute(
            "create table request_cache_entries (id, key_hash unique, prompt_hash, provider,"
            " model, response_json, response_size_bytes, created_at, updated_at, expires_at,"
            " last_hit_at, hit_count)"
        )

    with pytest.raises(PageRejected) as refused:
        load_page([_row("a")], old)

    assert refused.value.reason == "outdated_gateway_database"
    assert "metadata_json" in str(refused.value)
    with sqlite3.connect(old) as conn:
        assert conn.execute("select count(*) from request_cache_entries").fetchone() == (0,)


# --- checking a database before a pull -----------------------------------------------------------


def test_a_gateway_database_the_orm_created_passes_the_check(database: Path) -> None:
    check_database(database)


def test_the_check_refuses_a_file_that_is_not_a_gateway_database(tmp_path: Path) -> None:
    other = tmp_path / "other.sqlite3"
    with sqlite3.connect(other) as conn:
        conn.execute("create table something_else (x)")

    with pytest.raises(PageRejected) as refused:
        check_database(other)

    assert refused.value.reason == "not_a_gateway_database"


def test_the_check_refuses_a_gateway_database_from_before_the_metadata_column(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old.sqlite3"
    with sqlite3.connect(old) as conn:
        conn.execute(
            "create table request_cache_entries (id, key_hash unique, prompt_hash, provider,"
            " model, response_json, response_size_bytes, created_at, updated_at, expires_at,"
            " last_hit_at, hit_count)"
        )

    with pytest.raises(PageRejected) as refused:
        check_database(old)

    assert refused.value.reason == "outdated_gateway_database"
    assert "metadata_json" in str(refused.value)


def test_the_check_refuses_a_lookalike_table_without_a_unique_key_hash(tmp_path: Path) -> None:
    # WHY: ``ON CONFLICT(key_hash)`` needs that unique index; without it every insert would fail
    # with a raw OperationalError after the download had started.
    lookalike = tmp_path / "lookalike.sqlite3"
    columns = ", ".join(
        f"{name} TEXT"
        for name in (
            "id", "key_hash", "prompt_hash", "provider", "model", "response_json",
            "response_size_bytes", "created_at", "updated_at", "expires_at", "last_hit_at",
            "hit_count", "metadata_json",
        )
    )  # fmt: skip
    with sqlite3.connect(lookalike) as conn:
        conn.execute(f"create table request_cache_entries ({columns})")

    with pytest.raises(PageRejected) as refused:
        check_database(lookalike)

    assert refused.value.reason == "not_a_gateway_database"
    assert "unique key" in str(refused.value)


def test_the_check_refuses_a_missing_database_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "aigateway.sqlite3"

    with pytest.raises(PageRejected) as refused:
        check_database(missing)

    assert refused.value.reason == "not_a_gateway_database"
    assert not missing.exists()


# --- revisions -----------------------------------------------------------------------------------


def test_matching_revisions_pass() -> None:
    revisions = {"parameter_contract": "r1", "tavily_retrieval": "t1", "openrouter": "o1"}

    check_revisions(dict(revisions), revisions)


def test_a_differing_revision_is_refused() -> None:
    # WHY: rows keyed under another revision would load cleanly and then never be hit.
    with pytest.raises(PageRejected) as refused:
        check_revisions(
            {"parameter_contract": "r1", "openrouter": "o2"},
            {"parameter_contract": "r1", "openrouter": "o1"},
        )

    assert refused.value.reason == "revision_mismatch"


def test_an_adapter_known_to_one_side_only_is_not_a_mismatch() -> None:
    # WHY: a local process may load fewer provider plugins than the hosted gateway; rows for a
    # provider the local side does not have are never served there, so they cannot mis-hit.
    check_revisions(
        {"parameter_contract": "r1", "openrouter": "o1", "tavily_retrieval": "t1"},
        {"parameter_contract": "r1", "openrouter": "o1"},
    )


@pytest.mark.parametrize(
    ("remote", "local"),
    [
        ({"openrouter": "o1"}, {"parameter_contract": "r1", "openrouter": "o1"}),
        ({"parameter_contract": "r1"}, {"openrouter": "o1"}),
    ],
)
def test_the_parameter_contract_must_be_on_both_sides(
    remote: dict[str, str], local: dict[str, str]
) -> None:
    with pytest.raises(PageRejected) as refused:
        check_revisions(remote, local)

    assert refused.value.reason == "revision_mismatch"


def test_an_adapter_the_hosted_side_does_not_report_is_refused() -> None:
    # WHY: the hosted gateway may hold rows for an adapter it no longer loads, keyed under a
    # revision it cannot vouch for; they would load here and never hit. Fail closed.
    with pytest.raises(PageRejected) as refused:
        check_revisions(
            {"parameter_contract": "r1"},
            {"parameter_contract": "r1", "openrouter_adapter": "o1"},
        )

    assert refused.value.reason == "revision_mismatch"
    assert "openrouter_adapter" in str(refused.value)

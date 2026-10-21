"""Reading the community cache in pages (epic OME-1311): the cursor, the order, what crosses.

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: pages run in write order, ``(updated_at, key_hash)``, so a row written mid-walk is
reached by the same walk and rows sharing a timestamp are neither skipped nor repeated; the
cursor round-trips that pair exactly; a page yields at most ``limit`` rows in batches of at most
``BATCH_ROWS``; Tavily and expired rows never cross; the model filter is exact; ids and hit
statistics never cross; ``count_rows`` counts what the walk would return; and a cache hit
leaves ``updated_at`` alone — the property write order depends on.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache import community_pages
from aigateway.core.request_cache.community_pages import (
    BATCH_BYTES,
    BATCH_ROWS,
    MAX_PAGE_ROWS,
    PAGE_FIELDS,
    InvalidCursor,
    PageCursor,
    PageScan,
    count_rows,
    cursor_after,
    has_rows_after,
    iter_page,
)
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import record_hit_metadata
from aigateway.db import build_tortoise_config

_T0 = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)
_NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(tmp_path):
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{tmp_path / 'pages.sqlite3'}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


async def _row(
    key: str,
    *,
    updated_at: datetime = _T0,
    provider: str = "openrouter",
    model: str = "openrouter/m",
    expires_at: datetime | None = None,
    response_json: str = '{"choices": []}',
    hit_count: int = 0,
) -> RequestCacheEntry:
    entry = await RequestCacheEntry.create(
        key_hash=key.ljust(64, "0"),
        prompt_hash="p" * 64,
        provider=provider,
        model=model,
        response_json=response_json,
        response_size_bytes=len(response_json),
        expires_at=expires_at,
        hit_count=hit_count,
        last_hit_at=_T0 if hit_count else None,
        metadata_json='{"schema": "aigw.cache-entry-metadata.v1"}',
    )
    # auto_now stamps the write time; tests place rows on a timeline of their own.
    await RequestCacheEntry.filter(id=entry.id).update(updated_at=updated_at)
    return entry


async def _walk(*, limit: int = MAX_PAGE_ROWS, models: tuple[str, ...] = ()) -> list[str]:
    """Every key a client would receive, page after page, until the cursor runs out."""
    keys: list[str] = []
    after: PageCursor | None = None
    while True:
        page = [
            row
            async for batch in iter_page(after=after, limit=limit, models=models, now=_NOW)
            for row in batch
        ]
        keys.extend(row["key_hash"] for row in page)
        after = cursor_after(page, limit=limit)
        if after is None:
            return keys


# --- the cursor ---------------------------------------------------------------------------------


def test_a_cursor_round_trips_its_timestamp_and_key_exactly() -> None:
    cursor = PageCursor(updated_at=_T0, key_hash="ab" * 32)

    assert PageCursor.decode(cursor.encode()) == cursor


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not base64 at all!",
        base64.urlsafe_b64encode(b"no-separator").decode(),
        base64.urlsafe_b64encode(b"2026-10-01T12:00:00+00:00|short").decode(),
        base64.urlsafe_b64encode(b"2026-10-01T12:00:00+00:00|" + b"G" * 64).decode(),
        base64.urlsafe_b64encode(b"not-a-time|" + b"a" * 64).decode(),
        # A naive time cannot be placed on the table's UTC timeline.
        base64.urlsafe_b64encode(b"2026-10-01T12:00:00|" + b"a" * 64).decode(),
    ],
)
def test_a_malformed_cursor_is_refused(token: str) -> None:
    with pytest.raises(InvalidCursor):
        PageCursor.decode(token)


# --- order --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pages_run_in_write_order_and_ties_split_by_key(db) -> None:
    await _row("c", updated_at=_T0)
    await _row("a", updated_at=_T0 + timedelta(seconds=1))
    await _row("b", updated_at=_T0)

    assert [k[0] for k in await _walk(limit=1)] == ["b", "c", "a"]


@pytest.mark.asyncio
async def test_a_walk_returns_every_row_once_across_many_ties(db) -> None:
    # INVARIANT: a restore stamps many rows with one time; a page boundary inside such a run
    # must neither skip nor repeat a row.
    keys = [f"{i:02x}" for i in range(23)]
    for i, key in enumerate(keys):
        await _row(key, updated_at=_T0 + timedelta(seconds=i // 10))

    walked = await _walk(limit=4)

    assert sorted(walked) == sorted(k.ljust(64, "0") for k in keys)
    assert len(walked) == len(set(walked))


@pytest.mark.asyncio
async def test_a_row_written_mid_walk_is_reached_by_the_same_walk(db) -> None:
    await _row("a", updated_at=_T0)
    await _row("b", updated_at=_T0 + timedelta(seconds=1))
    first = [
        row async for batch in iter_page(after=None, limit=1, models=(), now=_NOW) for row in batch
    ]

    # Written after the walk started: a later write time, but a key that sorts first.
    await _row("0", updated_at=_T0 + timedelta(seconds=2))
    rest: list[str] = []
    after = cursor_after(first, limit=1)
    while after is not None:
        page = [
            row
            async for batch in iter_page(after=after, limit=1, models=(), now=_NOW)
            for row in batch
        ]
        rest.extend(row["key_hash"][0] for row in page)
        after = cursor_after(page, limit=1)

    assert [first[0]["key_hash"][0], *rest] == ["a", "b", "0"]


# --- page size ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_page_holds_at_most_limit_rows_in_batches(db) -> None:
    for i in range(BATCH_ROWS * 2 + 5):
        await _row(f"{i:03x}", updated_at=_T0 + timedelta(microseconds=i))

    batches = [
        batch async for batch in iter_page(after=None, limit=BATCH_ROWS + 7, models=(), now=_NOW)
    ]

    assert [len(b) for b in batches] == [BATCH_ROWS, 7]


@pytest.mark.asyncio
async def test_the_cursor_ends_only_on_a_short_page(db) -> None:
    for key in ("a", "b"):
        await _row(key)
    full = [
        row async for batch in iter_page(after=None, limit=2, models=(), now=_NOW) for row in batch
    ]

    after = cursor_after(full, limit=2)
    assert after == PageCursor(updated_at=_T0, key_hash="b".ljust(64, "0"))

    empty = [
        row async for batch in iter_page(after=after, limit=2, models=(), now=_NOW) for row in batch
    ]
    assert empty == []
    assert cursor_after(empty, limit=2) is None


def test_the_page_cap_is_five_thousand_rows() -> None:
    assert MAX_PAGE_ROWS == 5000


# --- what crosses -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tavily_and_expired_rows_never_cross(db) -> None:
    await _row("a")
    await _row("b", provider="tavily")
    await _row("c", expires_at=_NOW - timedelta(seconds=1))
    await _row("d", expires_at=_NOW + timedelta(days=1))

    assert sorted(k[0] for k in await _walk()) == ["a", "d"]


@pytest.mark.asyncio
async def test_the_model_filter_is_exact_and_optional(db) -> None:
    await _row("a", model="openrouter/anthropic/claude-opus-5.5")
    await _row("b", model="openrouter/google/gemini-3.1-pro-preview")
    await _row("c", model="openrouter/anthropic/claude-opus-5.5-mini")

    only = await _walk(models=("openrouter/anthropic/claude-opus-5.5",))
    two = await _walk(
        models=("openrouter/anthropic/claude-opus-5.5", "openrouter/google/gemini-3.1-pro-preview")
    )
    unknown = await _walk(models=("openrouter/nobody/none",))

    assert [k[0] for k in only] == ["a"]
    assert sorted(k[0] for k in two) == ["a", "b"]
    assert unknown == []
    assert sorted(k[0] for k in await _walk()) == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_rows_carry_the_shareable_fields_only_and_the_stored_text_verbatim(db) -> None:
    # WHY no id or hit statistics: they describe the platform's usage, not the cached answer.
    text = '{"choices": [{"message": {"content": "tab\\there, quote \\" and \\u00e9"}}]}'
    await _row("a", response_json=text, hit_count=7)

    [row] = [
        r async for batch in iter_page(after=None, limit=10, models=(), now=_NOW) for r in batch
    ]

    assert tuple(row) == PAGE_FIELDS
    assert not {"id", "hit_count", "last_hit_at"} & set(row)
    assert row["response_json"] == text
    assert row["updated_at"] == _T0


# --- count --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_matches_what_the_walk_returns_after_a_cursor(db) -> None:
    await _row("a", model="m1", updated_at=_T0)
    await _row("b", model="m2", updated_at=_T0 + timedelta(seconds=1))
    await _row("c", model="m1", updated_at=_T0 + timedelta(seconds=2))
    await _row("d", provider="tavily", model="m1", updated_at=_T0 + timedelta(seconds=3))
    await _row("e", model="m1", expires_at=_NOW - timedelta(days=1))

    assert await count_rows(after=None, models=(), now=_NOW) == 3
    assert await count_rows(after=None, models=("m1",), now=_NOW) == 2
    after_a = PageCursor(updated_at=_T0, key_hash="a".ljust(64, "0"))
    assert await count_rows(after=after_a, models=(), now=_NOW) == 2
    assert await count_rows(after=after_a, models=("m1",), now=_NOW) == 1


# --- the property write order depends on ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cache_hit_leaves_updated_at_alone(db) -> None:
    # INVARIANT (spec, Risks): updated_at means "content written". If a hit moved it, every hit
    # row would jump to the end of the order and pulls would keep re-sending it.
    entry = await _row("a", updated_at=_T0)

    await record_hit_metadata(entry.id, _NOW)

    refreshed = await RequestCacheEntry.get(id=entry.id)
    assert refreshed.hit_count == 1
    assert refreshed.updated_at == _T0


def test_the_postgres_hit_statements_do_not_set_updated_at() -> None:
    from aigateway.core.request_cache import store

    for sql in (store._HIT_IF_FREE_SQL, store._HIT_UNLESS_MERGING_SQL):
        assert "updated_at" not in sql


# --- memory: batches bounded by bytes (PR #1433 review, finding 1) --------------------------------


async def _sized(key: str, size: int, *, seconds: int) -> None:
    entry = await _row(key, updated_at=_T0 + timedelta(seconds=seconds))
    # The stored size is what bounds a batch; the body itself stays small in a unit test.
    await RequestCacheEntry.filter(id=entry.id).update(response_size_bytes=size)


@pytest.mark.asyncio
async def test_a_batch_of_large_responses_is_cut_at_the_byte_bound(db) -> None:
    # INVARIANT: a batch holds at most BATCH_BYTES of responses, whatever the row count — 100
    # rows of 1 MB responses would otherwise be ~100 MB before the route even encodes them.
    for i in range(30):
        await _sized(f"{i:02x}", 1_000_000, seconds=i)

    batches = [b async for b in iter_page(after=None, limit=1000, models=(), now=_NOW)]

    per_batch = BATCH_BYTES // 1_000_000
    assert [len(b) for b in batches] == [per_batch, per_batch, per_batch, 30 - 3 * per_batch]
    assert all(sum(r["response_size_bytes"] for r in b) <= BATCH_BYTES for b in batches)


@pytest.mark.asyncio
async def test_a_single_response_larger_than_the_bound_still_crosses_alone(db) -> None:
    await _sized("a", BATCH_BYTES + 1, seconds=0)
    await _sized("b", 10, seconds=1)

    batches = [b async for b in iter_page(after=None, limit=10, models=(), now=_NOW)]

    assert [[r["key_hash"][0] for r in b] for b in batches] == [["a"], ["b"]]


@pytest.mark.asyncio
async def test_a_byte_cut_at_the_end_of_the_table_loses_no_row(db) -> None:
    # The last, short fetch can still be cut by bytes; the rows beyond the cut must follow.
    await _sized("a", BATCH_BYTES - 1, seconds=0)
    await _sized("b", 2, seconds=1)
    await _sized("c", 2, seconds=2)

    walked = [
        r["key_hash"][0]
        async for b in iter_page(after=None, limit=10, models=(), now=_NOW)
        for r in b
    ]

    assert walked == ["a", "b", "c"]


# --- a row rewritten or deleted between the two queries (PR #1433 review round 2) -----------------


def _between_queries(monkeypatch: pytest.MonkeyPatch, change) -> None:
    """Run ``change`` once, after the first batch's keys are read and before its rows are."""
    original = community_pages._next_keys
    pending = [change]

    async def next_keys(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        keys = await original(*args, **kwargs)
        while pending:
            await pending.pop()()
        return keys

    monkeypatch.setattr(community_pages, "_next_keys", next_keys)


@pytest.mark.asyncio
async def test_a_row_rewritten_between_the_queries_is_sent_later_not_at_its_new_size(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: a merge restore rewrites a row with a new updated_at and size. Read by key alone, it
    # would cross at its new size (breaking the byte bound) and out of order (its new place).
    for i, key in enumerate("abcd"):
        await _sized(key, 10, seconds=i)

    async def rewrite_b() -> None:
        await RequestCacheEntry.filter(key_hash="b".ljust(64, "0")).update(
            updated_at=_T0 + timedelta(seconds=100), response_size_bytes=50_000_000
        )

    _between_queries(monkeypatch, rewrite_b)
    scan = PageScan()

    first = [
        r["key_hash"][0]
        async for b in iter_page(after=None, limit=3, models=(), now=_NOW, scan=scan)
        for r in b
    ]

    assert first == ["a", "c"]
    assert scan.cursor is not None and scan.cursor.key_hash[0] == "c"
    assert await has_rows_after(after=scan.cursor, models=(), now=_NOW)
    rest = [
        r["key_hash"][0]
        async for b in iter_page(after=scan.cursor, limit=10, models=(), now=_NOW)
        for r in b
    ]
    assert rest == ["d", "b"]


@pytest.mark.asyncio
async def test_rows_deleted_between_the_queries_still_move_the_scan_on(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: with every selected row gone, nothing is sent; the next page must still start after
    # them rather than the page ending with next: null while rows remain.
    await _sized("a", 10, seconds=0)
    await _sized("b", 10, seconds=1)
    await _sized("c", 10, seconds=2)

    async def delete_a_and_b() -> None:
        await RequestCacheEntry.filter(
            key_hash__in=["a".ljust(64, "0"), "b".ljust(64, "0")]
        ).delete()

    _between_queries(monkeypatch, delete_a_and_b)
    scan = PageScan()

    sent = [b async for b in iter_page(after=None, limit=2, models=(), now=_NOW, scan=scan)]

    assert sent == []
    assert scan.cursor is not None and scan.cursor.key_hash[0] == "b"
    assert await has_rows_after(after=scan.cursor, models=(), now=_NOW)


# --- the last page (PR #1433 review, non-blocking) -----------------------------------------------


@pytest.mark.asyncio
async def test_has_rows_after_says_whether_a_full_page_was_the_last(db) -> None:
    await _row("a", updated_at=_T0)
    await _row("b", updated_at=_T0 + timedelta(seconds=1))

    assert await has_rows_after(
        after=PageCursor(updated_at=_T0, key_hash="a".ljust(64, "0")), models=(), now=_NOW
    )
    assert not await has_rows_after(
        after=PageCursor(updated_at=_T0 + timedelta(seconds=1), key_hash="b".ljust(64, "0")),
        models=(),
        now=_NOW,
    )

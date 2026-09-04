"""OME-1044 — the Tavily retrieval cache store.

INVARIANT under test: insert-only, first fill wins, and every failure degrades rather
than raising into the request path. The row shape is pinned too, because this lane
shares `request_cache_entries` with the chat lane and is told apart ONLY by
`provider='tavily'` — the documented per-provider reset depends on that.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import CacheUnavailable
from aigateway.core.request_cache.tavily_store import (
    TavilyRetrievalCacheStore,
    TavilyRetrievalCacheWrite,
)
from aigateway.db import build_tortoise_config

_KEY = "a" * 64
_OTHER_KEY = "b" * 64
_RESULT = "Title: OpenMined\nURL: https://openmined.org\nContent: a privacy community"


@pytest_asyncio.fixture
async def store(tmp_path) -> AsyncIterator[TavilyRetrievalCacheStore]:
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{tmp_path / 'tavily-cache.sqlite3'}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield TavilyRetrievalCacheStore()
    finally:
        await Tortoise.close_connections()


def _write(key_hash: str = _KEY, result: str = _RESULT) -> TavilyRetrievalCacheWrite:
    return TavilyRetrievalCacheWrite(key_hash=key_hash, tool="web_search", result=result)


@pytest.mark.asyncio
async def test_a_filled_result_round_trips(store: TavilyRetrievalCacheStore) -> None:
    assert await store.set_if_absent(_write()) == "stored"
    hit = await store.get(_KEY)
    assert hit is not None
    assert hit.result == _RESULT
    assert hit.age_seconds >= 0


@pytest.mark.asyncio
async def test_an_unknown_key_is_a_miss(store: TavilyRetrievalCacheStore) -> None:
    assert await store.get(_OTHER_KEY) is None


@pytest.mark.asyncio
async def test_the_row_carries_the_provider_that_makes_a_targeted_reset_possible(
    store: TavilyRetrievalCacheStore,
) -> None:
    # INVARIANT: `DELETE FROM request_cache_entries WHERE provider = 'tavily'` is the
    # documented correction path for this lane, and it only works if every row says so.
    await store.set_if_absent(_write())
    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.provider == "tavily"
    assert row.model == "web_search"
    # The chat lane writes the full-call digest here too; there is no second digest.
    assert row.prompt_hash == _KEY
    # INVARIANT: no expiry — 1:1 with the chat lane (owner decision).
    assert row.expires_at is None


@pytest.mark.asyncio
async def test_the_payload_is_a_json_object_not_a_bare_string(
    store: TavilyRetrievalCacheStore,
) -> None:
    # WHY: the column is shared with the chat lane and generic readers (admin cache,
    # snapshot, bulk loader) assume a JSON object. A bare string would parse but break
    # the `isinstance(..., dict)` contract those readers rely on.
    await store.set_if_absent(_write())
    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert json.loads(row.response_json) == {"result": _RESULT}


@pytest.mark.asyncio
async def test_the_first_fill_wins_and_is_never_overwritten(
    store: TavilyRetrievalCacheStore,
) -> None:
    assert await store.set_if_absent(_write(result="first")) == "stored"
    assert await store.set_if_absent(_write(result="second")) == "race_lost"
    hit = await store.get(_KEY)
    assert hit is not None
    assert hit.result == "first"


@pytest.mark.asyncio
async def test_a_hit_records_its_metadata(store: TavilyRetrievalCacheStore) -> None:
    await store.set_if_absent(_write())
    await store.get(_KEY)
    await store.get(_KEY)
    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.hit_count == 2
    assert row.last_hit_at is not None


@pytest.mark.asyncio
async def test_an_undecodable_row_is_refused_rather_than_served(
    store: TavilyRetrievalCacheStore,
) -> None:
    # INVARIANT: never serve a half-understood payload. The row is left untouched so a
    # human can inspect it; the caller sees the cache as unavailable and dispatches.
    await RequestCacheEntry.create(
        key_hash=_KEY,
        prompt_hash=_KEY,
        provider="tavily",
        model="web_search",
        response_json="{not json",
        response_size_bytes=9,
        expires_at=None,
    )
    with pytest.raises(CacheUnavailable):
        await store.get(_KEY)
    assert await RequestCacheEntry.filter(key_hash=_KEY).exists()


@pytest.mark.asyncio
async def test_a_row_missing_the_result_member_is_refused(
    store: TavilyRetrievalCacheStore,
) -> None:
    await RequestCacheEntry.create(
        key_hash=_KEY,
        prompt_hash=_KEY,
        provider="tavily",
        model="web_search",
        response_json=json.dumps({"unexpected": "shape"}),
        response_size_bytes=24,
        expires_at=None,
    )
    with pytest.raises(CacheUnavailable):
        await store.get(_KEY)


def test_the_store_takes_no_operator_gate() -> None:
    # INVARIANT: the lane is UNCONDITIONAL (owner decision) — no switch, no chart value,
    # no availability object. A constructor argument reappearing here would mean a
    # configuration layer crept back in.
    assert inspect.signature(TavilyRetrievalCacheStore).parameters == {}
    assert not hasattr(TavilyRetrievalCacheStore, "cache_available")

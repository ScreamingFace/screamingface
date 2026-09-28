"""S15 / ERD E9 — the Tavily retrieval lane stays out of the metadata feature.

INVARIANT under test: every row this second writer creates carries ``metadata_json = NULL``.
The lane holds no cost signal of any kind, and NULL is the documented "unknown" — a fabricated
empty block, or a literal ``0``, would be a price the lane never measured.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.tavily_store import (
    TavilyRetrievalCacheStore,
    TavilyRetrievalCacheWrite,
)
from aigateway.db import build_tortoise_config

_KEY = "a" * 64


@pytest_asyncio.fixture
async def store(tmp_path) -> AsyncIterator[TavilyRetrievalCacheStore]:
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{tmp_path / 'tavily-metadata.sqlite3'}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield TavilyRetrievalCacheStore()
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_a_tavily_row_is_written_with_null_entry_metadata(
    store: TavilyRetrievalCacheStore,
) -> None:
    entry = TavilyRetrievalCacheWrite(
        key_hash=_KEY, tool="web_search", result="Title: OpenMined\nURL: https://openmined.org"
    )
    assert await store.set_if_absent(entry) == "stored"

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.provider == "tavily"
    assert row.metadata_json is None

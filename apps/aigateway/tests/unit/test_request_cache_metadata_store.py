"""The cache-entry metadata write and read path on the store (PRD tests #9, #14, #15).

PRD task A4/A5/A6; ERD §5.4 (write path), §5.5 (read path), invariants E6, E7, S8,
S9, S10, S11.
"""

from __future__ import annotations

import json
import logging

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import (
    RequestCacheWrite,
    TortoiseRequestCacheStore,
)
from aigateway.db import build_tortoise_config

_KEY = "a" * 64
_RESPONSE = {
    "id": "cmpl-1",
    "model": "anthropic/claude-haiku-4-5",
    "choices": [{"message": {"role": "assistant", "content": "SECRET-ANSWER"}}],
}

_USAGE = {
    "status": "complete",
    "source": "provider_raw_response",
    "input": {
        "total": 11,
        "uncached": 11,
        "cache_read": 0,
        "cache_write": 0,
        "cache_write_by_ttl": [],
    },
    "output": {"total": 3, "reasoning": None},
}


def _metadata(**overrides) -> CacheEntryMetadata:
    values = {
        "metadata_status": "complete",
        "observed_at": "2026-09-13T12:00:00Z",
        "response_model": "anthropic/claude-haiku-4-5",
        "usage": _USAGE,
        "direct_cost": {
            "status": "reported",
            "amount": "0.0038799200000000002",
            "unit": "openrouter_credits",
            "source": "openrouter.usage.cost",
        },
        "provider_latency_ms": 812,
    }
    values.update(overrides)
    return CacheEntryMetadata(**values)


def _write(key_hash: str = _KEY, **overrides) -> RequestCacheWrite:
    values = {
        "key_hash": key_hash,
        "prompt_hash": "p" * 64,
        "provider": "anthropic",
        "model": "anthropic/claude-haiku-4-5",
        "response": _RESPONSE,
        "response_size_bytes": 128,
    }
    values.update(overrides)
    return RequestCacheWrite(**values)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "cache-entry-metadata.sqlite3"
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{db_path}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest_asyncio.fixture
async def store(db) -> TortoiseRequestCacheStore:
    return TortoiseRequestCacheStore()


# --- write path ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_priced_write_persists_the_block_and_a_hit_reads_it_back(store) -> None:
    metadata = _metadata()

    assert await store.set_if_absent(_write(metadata=metadata)) == "stored"

    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.metadata == metadata
    assert entry.response == _RESPONSE


@pytest.mark.asyncio
async def test_a_write_without_metadata_stores_null(store) -> None:
    assert await store.set_if_absent(_write()) == "stored"

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.metadata_json is None

    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.metadata is None


# --- PRD test #15 — a serialization failure writes NULL and never fails the request -------------


@pytest.mark.asyncio
async def test_a_metadata_serialization_failure_stores_null_and_serves_the_body(
    store, monkeypatch, caplog
) -> None:
    def _boom(_self: CacheEntryMetadata) -> str | None:
        raise ValueError("cannot serialize")

    monkeypatch.setattr(CacheEntryMetadata, "serialize", _boom)

    with caplog.at_level(logging.WARNING, logger="aigateway.core.request_cache.store"):
        assert await store.set_if_absent(_write(metadata=_metadata())) == "stored"

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.metadata_json is None
    assert json.loads(row.response_json) == _RESPONSE
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert _KEY[:12] in warnings[0].getMessage()
    assert "SECRET-ANSWER" not in warnings[0].getMessage()


# --- PRD test #9 — a lost race leaves the winner's metadata in place (I4, S10) ------------------


@pytest.mark.asyncio
async def test_a_lost_write_race_keeps_the_winners_metadata(store) -> None:
    winner_metadata = _metadata(direct_cost={**_metadata().direct_cost, "amount": "0.0001"})
    assert await store.set_if_absent(_write(metadata=winner_metadata)) == "stored"

    loser = _write(metadata=_metadata(provider_latency_ms=1, response_model="loser-model"))
    assert await store.set_if_absent(loser) == "race_lost"

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.response_json == json.dumps(_RESPONSE, separators=(",", ":"), ensure_ascii=False)
    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.metadata == winner_metadata


# --- PRD test #14 — a corrupt block is absent and the body still serves (S11) -------------------


@pytest.mark.asyncio
async def test_a_corrupt_metadata_block_is_treated_as_absent(store, caplog) -> None:
    await store.set_if_absent(_write(metadata=_metadata()))
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.metadata_json = "{not-json"
    await row.save(update_fields=["metadata_json"])

    with caplog.at_level(logging.WARNING, logger="aigateway.core.request_cache.store"):
        entry = await store.get(_KEY)

    assert entry is not None
    assert entry.metadata is None
    assert entry.response == _RESPONSE
    assert any(_KEY[:12] in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_metadata_block_with_the_wrong_schema_is_treated_as_absent(store) -> None:
    await store.set_if_absent(_write(metadata=_metadata()))
    row = await RequestCacheEntry.get(key_hash=_KEY)
    row.metadata_json = json.dumps({"schema": "other.v9"})
    await row.save(update_fields=["metadata_json"])

    entry = await store.get(_KEY)

    assert entry is not None
    assert entry.metadata is None
    assert entry.response == _RESPONSE

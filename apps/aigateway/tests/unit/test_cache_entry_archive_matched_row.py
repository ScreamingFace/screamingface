"""An externally-priced row survives the store and certifies its price on a hit.

WHY THIS EXISTS SEPARATELY from ``test_request_cache_metadata_store.py``: that file covers a
block this gateway built itself, from a live provider response. This one covers the other
producer — a row loaded from an offline seed package, whose ``direct_cost`` carries the
``archive_matched`` status. That status is the reason the gateway admits a price it did not
observe: the amount is a real measured value from a logged call of the same kind and model, but
per-row attribution is unproven, which is exactly why it may never be summed with provider
authored money (PRD S7, ERD M8).

The seed package itself is generated and loaded out-of-band and is not part of this repository.
What IS part of this repository is the contract such a load depends on, and that is what these
tests pin: the block round-trips through the real store, a hit certifies it, an unpriced row
reports unknown rather than free, and a malformed amount is refused rather than coerced.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import RequestCacheWrite, TortoiseRequestCacheStore
from aigateway.db import build_tortoise_config
from aigateway.plugins.taxonomy import (
    CacheEntryMetadataReferenceError,
    cache_reference_from_entry_metadata,
)

_KEY = "b" * 64
_RESPONSE = {
    "id": "cmpl-seeded-1",
    "object": "chat.completion",
    "model": "openrouter/google/gemini-3.1-pro-preview",
    "choices": [{"message": {"role": "assistant", "content": "MET"}}],
}

_ARCHIVE_USAGE = {
    "status": "complete",
    "source": "provider_converted_response",
    "input": {
        "total": 1422,
        "uncached": None,
        "cache_read": None,
        "cache_write": None,
        "cache_write_by_ttl": [],
    },
    # `total` already INCLUDES `reasoning`; the two are never added together.
    "output": {"total": 79, "reasoning": 41},
}

_ARCHIVE_COST = {
    "status": "archive_matched",
    "amount": "0.003792",
    "unit": "usd",
    "source": "offline-seed:per-call-telemetry",
}


def _archive_metadata(**overrides) -> CacheEntryMetadata:
    values = {
        "metadata_status": "archive_paired",
        "observed_at": "2026-07-06T20:27:40+00:00",
        "response_model": "openrouter/google/gemini-3.1-pro-preview",
        "usage": _ARCHIVE_USAGE,
        "direct_cost": _ARCHIVE_COST,
        "provider_latency_ms": 2119,
    }
    values.update(overrides)
    return CacheEntryMetadata(**values)  # type: ignore[arg-type]


def _unpriced_metadata() -> CacheEntryMetadata:
    return CacheEntryMetadata(
        metadata_status="partial",
        observed_at=None,
        response_model="openrouter/google/gemini-3.1-pro-preview",
        usage={
            "status": "unavailable",
            "source": "provider_converted_response",
            "input": {
                "total": None,
                "uncached": None,
                "cache_read": None,
                "cache_write": None,
                "cache_write_by_ttl": [],
            },
            "output": {"total": None, "reasoning": None},
        },
        direct_cost={"status": "unavailable", "amount": None, "unit": None, "source": None},
        provider_latency_ms=None,
    )


def _write(metadata: CacheEntryMetadata) -> RequestCacheWrite:
    return RequestCacheWrite(
        key_hash=_KEY,
        prompt_hash=_KEY,
        provider="openrouter",
        model="openrouter/google/gemini-3.1-pro-preview",
        response=_RESPONSE,
        response_size_bytes=256,
        metadata=metadata,
    )


@pytest_asyncio.fixture
async def store(tmp_path):
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{tmp_path / 'archive-matched.sqlite3'}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield TortoiseRequestCacheStore()
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_an_archive_matched_block_survives_the_store_and_certifies_on_a_hit(store) -> None:
    metadata = _archive_metadata()

    assert await store.set_if_absent(_write(metadata)) == "stored"

    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.response == _RESPONSE
    assert entry.metadata is not None
    assert entry.metadata.metadata_status == "archive_paired"
    assert entry.metadata.direct_cost == _ARCHIVE_COST
    assert entry.metadata.usage == _ARCHIVE_USAGE
    assert entry.metadata.provider_latency_ms == 2119
    assert entry.metadata.observed_at == "2026-07-06T20:27:40+00:00"

    # `archive_paired` is a certifying capture, so the stored cost reaches the reference
    # verbatim — the whole point of admitting the status at all.
    reference = cache_reference_from_entry_metadata(entry.metadata)
    assert reference.direct_cost.as_json() == _ARCHIVE_COST
    assert reference.provider_latency_ms == 2119
    assert reference.incurred_in_current_request is False
    # The reference reports how THIS response reached the caller, not how the bytes first
    # arrived, so the stored provenance is rewritten on the way out.
    assert reference.usage.as_json()["source"] == "cached_converted_response"


@pytest.mark.asyncio
async def test_an_unpriced_seed_row_reports_unknown_and_never_zero(store) -> None:
    assert await store.set_if_absent(_write(_unpriced_metadata())) == "stored"

    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.metadata is not None
    assert entry.metadata.direct_cost == {
        "status": "unavailable",
        "amount": None,
        "unit": None,
        "source": None,
    }
    # I1: unknown is not free. A missing price must never be reported as a zero one.
    assert entry.metadata.direct_cost["amount"] != "0"
    assert entry.metadata.provider_latency_ms is None

    reference = cache_reference_from_entry_metadata(entry.metadata)
    assert reference.direct_cost.status == "unavailable"
    assert reference.direct_cost.amount is None


@pytest.mark.asyncio
async def test_the_stored_block_carries_no_response_body(store) -> None:
    assert await store.set_if_absent(_write(_archive_metadata())) == "stored"

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.metadata_json is not None
    # E5/M6: the block describes the response, it never quotes it.
    assert _RESPONSE["id"] not in row.metadata_json
    assert "MET" not in row.metadata_json


def test_a_non_canonical_archive_amount_is_refused_rather_than_coerced() -> None:
    # A trailing zero is a different decimal string for the same value. Money is compared and
    # totalled as text here, so the canonical form is the contract — silently normalising it
    # would let two spellings of one amount diverge downstream.
    metadata = _archive_metadata(direct_cost={**_ARCHIVE_COST, "amount": "0.0037920"})

    with pytest.raises(CacheEntryMetadataReferenceError):
        cache_reference_from_entry_metadata(metadata)


def test_an_archive_amount_without_a_unit_is_refused() -> None:
    # M2: `archive_matched` carries the same requirement as `reported` — amount, unit and
    # source must all be present, or the value cannot be certified as money at all.
    metadata = _archive_metadata(direct_cost={**_ARCHIVE_COST, "unit": None})

    with pytest.raises(CacheEntryMetadataReferenceError):
        cache_reference_from_entry_metadata(metadata)

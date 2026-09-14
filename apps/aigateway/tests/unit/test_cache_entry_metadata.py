"""The cache-entry metadata value object: codec, cap and rejection rules.

PRD ``docs/spec/2026-09-13-cache-entry-metadata-prd.md`` task A1, tests #14, #15,
#23; ERD §3.2, invariants M5, M9, S11.
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.request_cache.entry_metadata import (
    CACHE_ENTRY_METADATA_MAX_BYTES,
    CACHE_ENTRY_METADATA_SCHEMA,
    CacheEntryMetadata,
)

_USAGE = {
    "status": "complete",
    "source": "provider_raw_response",
    "input": {
        "total": 1234,
        "uncached": 1234,
        "cache_read": 0,
        "cache_write": 0,
        "cache_write_by_ttl": [],
    },
    "output": {"total": 567, "reasoning": None},
}

_DIRECT_COST = {
    "status": "reported",
    "amount": "0.012345",
    "unit": "openrouter_credits",
    "source": "openrouter.usage.cost",
}


def _metadata(**overrides) -> CacheEntryMetadata:
    values = {
        "metadata_status": "complete",
        "observed_at": "2026-09-13T12:00:00Z",
        "response_model": "anthropic/claude-fable-5",
        "usage": _USAGE,
        "direct_cost": _DIRECT_COST,
        "provider_latency_ms": 812,
    }
    values.update(overrides)
    return CacheEntryMetadata(**values)


def _serialized(metadata: CacheEntryMetadata) -> str:
    """The block's JSON. Every block built here is far under the cap, so ``None`` is a bug."""
    payload = metadata.serialize()
    assert payload is not None
    return payload


def test_the_serialized_block_uses_the_erd_shape_and_the_schema_id() -> None:
    block = json.loads(_serialized(_metadata()))

    assert list(block) == [
        "schema",
        "metadata_status",
        "observed_at",
        "response_model",
        "usage",
        "direct_cost",
        "latency",
    ]
    assert block["schema"] == CACHE_ENTRY_METADATA_SCHEMA
    assert block["latency"] == {"provider_latency_ms": 812}


def test_the_block_round_trips_through_json_exactly() -> None:
    original = _metadata()

    restored = CacheEntryMetadata.parse(original.serialize())

    assert restored is not None
    assert restored == original
    assert restored.usage == _USAGE
    assert restored.direct_cost == _DIRECT_COST


def test_the_serialized_block_is_compact_and_does_not_escape_non_ascii() -> None:
    payload = _serialized(_metadata(response_model="ünïcode/模型"))

    assert ", " not in payload and ": " not in payload
    assert "模型" in payload


def test_a_block_over_the_cap_is_dropped_whole_and_never_trimmed() -> None:
    oversized = _metadata(usage={**_USAGE, "filler": "x" * CACHE_ENTRY_METADATA_MAX_BYTES})

    assert oversized.serialize() is None


def test_a_nan_value_is_refused_rather_than_serialized() -> None:
    with pytest.raises(ValueError):
        _metadata(usage={**_USAGE, "amount": float("nan")}).serialize()


def test_parse_never_raises_on_a_corrupt_block() -> None:
    assert CacheEntryMetadata.parse("not-json") is None
    assert CacheEntryMetadata.parse('{"schema": "other.v1"}') is None
    assert CacheEntryMetadata.parse(json.dumps(["not", "an", "object"])) is None


def test_parse_rejects_non_finite_json_constants() -> None:
    payload = json.dumps(_metadata().as_json_dict(), separators=(",", ":"))
    poisoned = payload.replace("1234", "NaN", 1)

    assert CacheEntryMetadata.parse(poisoned) is None


def test_parse_rejects_an_overflowing_json_number() -> None:
    payload = json.dumps(_metadata().as_json_dict(), separators=(",", ":"))
    poisoned = payload.replace("1234", "1e9999", 1)

    assert CacheEntryMetadata.parse(poisoned) is None


def test_parse_accepts_none_and_a_prebuilt_dict() -> None:
    assert CacheEntryMetadata.parse(None) is None

    restored = CacheEntryMetadata.parse(_metadata().as_json_dict())

    assert restored == _metadata()


def test_an_unknown_metadata_status_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        _metadata(metadata_status="made_up")

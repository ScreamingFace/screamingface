"""A cache hit returns the WHOLE stored block, not three fields of it (OME-1155 follow-up).

FEATURE: cache-entry metadata end to end
(spec ``docs/spec/2026-09-28-aigateway-cache-hit-metadata.md``
§3.1).
STORY: as an operator reading a hit's ``_aigw`` I can see which model produced the cached answer
and when the gateway observed it, and not only what it cost.

INVARIANT: additive only. A block without ``response_model`` / ``observed_at`` — every row written
before this change, and every provider fallback reference built from a cached body — renders the
same bytes as before. The pinned release-fixture hashes depend on that.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.plugins.taxonomy import CacheReference, DirectCost
from aigateway.plugins.taxonomy.entry_metadata import (
    CacheEntryMetadataReferenceError,
    cache_reference_from_entry_metadata,
)
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.plugins.taxonomy.types import MAX_RESPONSE_MODEL_BYTES

_OBSERVED_AT = "2026-09-28T10:11:12Z"
_RESPONSE_MODEL = "anthropic/claude-fable-5"
_BASE_KEYS = {"kind", "coverage", "incurred_in_current_request", "usage", "direct_cost", "latency"}
_COST = {
    "status": "reported",
    "amount": "0.012345",
    "unit": "openrouter_credits",
    "source": "openrouter.usage.cost",
}


def _block(**overrides: Any) -> CacheEntryMetadata:
    values: dict[str, Any] = {
        "metadata_status": "complete",
        "observed_at": _OBSERVED_AT,
        "response_model": _RESPONSE_MODEL,
        "usage": {
            "status": "complete",
            "source": "provider_raw_response",
            "input": {"total": 100, "uncached": 100, "cache_read": 0, "cache_write": 0},
            "output": {"total": 25, "reasoning": None},
        },
        "direct_cost": dict(_COST),
        "provider_latency_ms": 812,
    }
    values.update(overrides)
    return CacheEntryMetadata(**values)


def _hit_metadata(reference: CacheReference) -> dict[str, Any]:
    return render_aigw_metadata(
        collector=None,
        supported=True,
        cache_status="hit",
        gateway_call_id="call_" + "a" * 32,
        cache_reference=reference,
    )


# --- the mapping -----------------------------------------------------------------------------


def test_a_hit_returns_the_stored_response_model_and_observed_at() -> None:
    payload = cache_reference_from_entry_metadata(_block()).as_json()

    assert payload["response_model"] == _RESPONSE_MODEL
    assert payload["observed_at"] == _OBSERVED_AT
    # The fields that were already returned are unchanged by the addition.
    assert payload["direct_cost"] == _COST
    assert payload["latency"] == {"provider_latency_ms": 812}


def test_a_block_without_the_two_fields_keeps_the_previous_wire_shape() -> None:
    """INVARIANT: absent, never ``null`` — an old row renders exactly what it rendered before."""
    payload = cache_reference_from_entry_metadata(
        _block(observed_at=None, response_model=None)
    ).as_json()

    assert set(payload) == _BASE_KEYS


def test_each_field_is_returned_on_its_own() -> None:
    only_model = cache_reference_from_entry_metadata(_block(observed_at=None)).as_json()
    only_time = cache_reference_from_entry_metadata(_block(response_model=None)).as_json()

    assert set(only_model) == _BASE_KEYS | {"response_model"}
    assert set(only_time) == _BASE_KEYS | {"observed_at"}


def test_a_partial_block_still_returns_both_fields_but_never_a_price() -> None:
    # The `partial` rule withholds the PRICE (ERD §3.5). The model and the fill time are
    # observations, not a price, so they still travel.
    payload = cache_reference_from_entry_metadata(_block(metadata_status="partial")).as_json()

    assert payload["direct_cost"]["status"] == "unavailable"
    assert payload["response_model"] == _RESPONSE_MODEL
    assert payload["observed_at"] == _OBSERVED_AT


def test_the_default_reference_carries_neither_field() -> None:
    # The provider fallback mappers build a reference from the cached BODY and must never
    # infer either field from it (PRD R2).
    reference = CacheReference()

    assert reference.response_model is None
    assert reference.observed_at is None
    assert "response_model" not in reference.as_json()
    assert "observed_at" not in reference.as_json()


# --- the constructor -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "m" * 513, "é" * 257, 7, b"model"])
def test_the_constructor_refuses_an_invalid_response_model(bad: object) -> None:
    with pytest.raises(ValueError, match="response_model"):
        CacheReference(response_model=bad)  # type: ignore[arg-type]


def test_the_response_model_bound_is_512_utf8_bytes() -> None:
    # The collector bounds the stored value at 512 UTF-8 BYTES; the reference uses the same unit.
    assert CacheReference(response_model="m" * 512).response_model == "m" * 512


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "2026-09-28",
        "2026-09-28T10:11:12",
        "2026-09-28 10:11:12Z",
        "2026-09-28T10:11:12.1234567890Z",
        "2026-09-28T10:11:12+0000",
        " 2026-09-28T10:11:12Z",
        "2026-09-28T10:11:12Z\n",
        "２０２６-09-28T10:11:12Z",
        1727518272,
    ],
)
def test_the_constructor_refuses_an_observed_at_in_any_other_format(bad: object) -> None:
    with pytest.raises(ValueError, match="observed_at"):
        CacheReference(observed_at=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "good", ["2026-09-28T10:11:12Z", "2026-07-06T20:27:40+00:00", "2026-09-28T10:11:12.123456Z"]
)
def test_the_constructor_accepts_every_rfc_3339_writer_format(good: str) -> None:
    # The out-of-band archive loader writes `+00:00`; the gateway writes `Z`. Both are real rows.
    assert CacheReference(observed_at=good).as_json()["observed_at"] == good


def test_a_malformed_stored_field_is_dropped_and_the_price_still_certifies() -> None:
    """A bad informational field must never cost the hit its price.

    The S11 fallback would replace the stored cost with whatever the cached body carries, so the
    mapper drops just the field — the answer an older row without it gives.
    """
    for block in (_block(observed_at="yesterday"), _block(response_model="")):
        payload = cache_reference_from_entry_metadata(block).as_json()
        assert payload["direct_cost"] == _COST
    assert (
        "observed_at"
        not in cache_reference_from_entry_metadata(_block(observed_at="yesterday")).as_json()
    )
    assert (
        "response_model"
        not in cache_reference_from_entry_metadata(_block(response_model="m" * 513)).as_json()
    )


@pytest.mark.parametrize(
    "impossible",
    ["2026-99-99T99:99:99+99:99", "2026-02-30T00:00:00Z", "2026-09-28T24:00:00Z"],
)
def test_an_impossible_timestamp_is_refused_even_when_it_looks_right(impossible: str) -> None:
    # The shape check alone admits these; a real calendar check must not.
    with pytest.raises(ValueError, match="observed_at"):
        CacheReference(observed_at=impossible)
    payload = cache_reference_from_entry_metadata(_block(observed_at=impossible)).as_json()
    assert "observed_at" not in payload
    assert payload["direct_cost"] == _COST


def test_a_dropped_field_is_logged_by_name_and_never_by_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A silent drop would hide a producer defect; logging the value could leak it."""
    secretish = "2026-99-99T99:99:99+99:99"
    with caplog.at_level(logging.WARNING, logger="aigateway.plugins.taxonomy.entry_metadata"):
        cache_reference_from_entry_metadata(_block(observed_at=secretish, response_model="m" * 513))

    messages = [record.getMessage() for record in caplog.records]
    assert "cache-entry metadata field dropped field=observed_at" in messages
    assert "cache-entry metadata field dropped field=response_model" in messages
    assert secretish not in caplog.text
    assert "m" * 513 not in caplog.text


def test_a_valid_or_absent_field_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="aigateway.plugins.taxonomy.entry_metadata"):
        cache_reference_from_entry_metadata(_block())
        cache_reference_from_entry_metadata(_block(observed_at=None, response_model=None))

    assert caplog.records == []


def test_a_corrupt_price_still_maps_to_the_narrow_error() -> None:
    """S11 is unchanged for the fields that carry money: the caller falls back on this error."""
    with pytest.raises(CacheEntryMetadataReferenceError):
        cache_reference_from_entry_metadata(_block(direct_cost={"status": "reported"}))


# --- the handoff schema ----------------------------------------------------------------------


def test_the_schema_accepts_a_hit_with_both_fields(accounting_schema: dict[str, Any]) -> None:
    reference = cache_reference_from_entry_metadata(_block())

    Draft202012Validator(accounting_schema).validate(_hit_metadata(reference))


def test_the_schema_accepts_a_hit_without_either_field(accounting_schema: dict[str, Any]) -> None:
    reference = cache_reference_from_entry_metadata(_block(observed_at=None, response_model=None))

    Draft202012Validator(accounting_schema).validate(_hit_metadata(reference))


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("response_model", 7),
        ("response_model", None),
        ("response_model", "m" * 513),
        ("observed_at", "2026-09-28 10:11:12Z"),
        ("observed_at", None),
        ("fill_region", "eu"),
    ],
)
def test_the_schema_refuses_a_wrong_field_or_an_unknown_key(
    field: str, bad: object, accounting_schema: dict[str, Any]
) -> None:
    # `null` is refused on purpose: the renderer OMITS an unknown value, so a `null` on the wire
    # means a producer that does not follow the contract.
    metadata = _hit_metadata(
        CacheReference(direct_cost=DirectCost.unavailable(), response_model="m")
    )
    metadata["usage_accounting"]["cache"]["reference"][field] = bad

    with pytest.raises(ValidationError):
        Draft202012Validator(accounting_schema).validate(metadata)


def test_the_reference_and_the_attempt_share_one_model_id_definition(
    accounting_schema: dict[str, Any],
) -> None:
    # One bound, declared once: the reference only adds "never empty", because it OMITS an
    # unknown model where an attempt renders a null.
    defs = accounting_schema["$defs"]
    reference = defs["cache_reference"]["properties"]["response_model"]
    attempt = defs["attempt"]["properties"]["response_model"]

    assert reference == {"$ref": "#/$defs/model_id", "minLength": 1}
    assert {"$ref": "#/$defs/model_id"} in attempt["oneOf"]
    assert defs["model_id"]["maxLength"] == MAX_RESPONSE_MODEL_BYTES

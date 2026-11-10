"""A frozen-copy replay carries the captured call's price as ``cache.reference`` (E4c, OME-1291).

FEATURE: one price source live and on replay (E4c ans:Q21b, budget BU-27). A budget Gate reads
the price of each earlier call. Live, the engine reads the last succeeded attempt of a complete
capture; on a cache hit it reads ``cache.reference``. A replay must give the engine the same
numbers, so the replay renders the captured call's price record as its reference.

INVARIANT: the reference holds exactly what the live run's engine read — the last succeeded
attempt of a complete capture, or the captured hit's own reference — and nothing for a capture
the live engine could not price.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.plugins.taxonomy import (
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    ProviderAttemptRecord,
    TokenUsage,
    cache_reference_from_entry_metadata,
)
from aigateway.plugins.taxonomy.entry_metadata import cache_reference_from_captured_aigw
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from tests.unit.test_frozen_copy_support import (
    account_id_of,
    call_key,
    chat_body,
    chat_response,
    seed_copy,
)

_CALL_ID = "call_" + "a" * 32
_UNIT = "openrouter_credits"
_SOURCE = "openrouter.usage.cost"


def _tokens(total_in: int, total_out: int) -> TokenUsage:
    return TokenUsage(
        status="complete",
        source="provider_raw_response",
        input=InputTokenUsage(total=total_in, uncached=total_in),
        output=OutputTokenUsage(total=total_out),
    )


def _record(sequence: int, **overrides: Any) -> ProviderAttemptRecord:
    values: dict[str, Any] = {
        "attempt_id": f"attempt_{sequence:032x}",
        "sequence": sequence,
        "dispatch_index": sequence,
        "attempt_index": 1,
        "provider": "openrouter",
        "transport": "litellm_async_http",
        "outcome": "succeeded",
        "http_status": 200,
        "latency_ms": 100 * sequence,
        "response_model": "openai/gpt-5",
        "usage": _tokens(10 * sequence, sequence),
        "direct_cost": DirectCost.reported(amount=f"0.00{sequence}", unit=_UNIT, source=_SOURCE),
    }
    values.update(overrides)
    return ProviderAttemptRecord(**values)


def _failed(sequence: int) -> ProviderAttemptRecord:
    return _record(
        sequence,
        outcome="provider_error",
        http_status=503,
        failure_code="provider_status_error",
        usage=TokenUsage.unavailable(),
        direct_cost=DirectCost.unavailable(),
    )


class _Collector:
    def __init__(self, *records: ProviderAttemptRecord, status: str = "complete") -> None:
        self._records = records
        self._status = status

    def records(self) -> tuple[ProviderAttemptRecord, ...]:
        return self._records

    def status(self) -> str:
        return self._status


def _live_miss(*records: ProviderAttemptRecord, status: str = "complete") -> dict[str, Any]:
    """The ``_aigw`` block a live miss served, as the capture stored it."""
    return render_aigw_metadata(
        collector=_Collector(*records, status=status),
        supported=True,
        cache_status="miss",
        gateway_call_id=_CALL_ID,
    )


def _live_hit(meta: CacheEntryMetadata) -> dict[str, Any]:
    """The ``_aigw`` block a live cache hit served, as the capture stored it."""
    return render_aigw_metadata(
        collector=None,
        supported=True,
        cache_status="hit",
        gateway_call_id=_CALL_ID,
        cache_reference=cache_reference_from_entry_metadata(meta),
    )


def _stored(status: str = "complete") -> CacheEntryMetadata:
    record = _record(3)
    return CacheEntryMetadata(
        metadata_status=status,  # type: ignore[arg-type]
        observed_at="2026-10-27T10:00:00Z",
        response_model="openai/gpt-5",
        usage=record.usage.as_json(),
        direct_cost=record.direct_cost.as_json(),
        provider_latency_ms=300,
    )


class TestCapturedMiss:
    def test_the_reference_is_the_last_succeeded_attempt(self) -> None:
        reference = cache_reference_from_captured_aigw(_live_miss(_record(1)))

        assert reference is not None
        payload = reference.as_json()
        assert payload["usage"] == {
            **_tokens(10, 1).as_json(),
            "source": "cached_converted_response",
        }
        assert payload["direct_cost"] == _record(1).direct_cost.as_json()
        assert payload["latency"] == {"provider_latency_ms": 100}
        assert payload["response_model"] == "openai/gpt-5"

    def test_a_retry_prices_only_the_attempt_that_answered(self) -> None:
        reference = cache_reference_from_captured_aigw(_live_miss(_failed(1), _record(2)))

        assert reference is not None
        assert reference.direct_cost.amount == "0.002"
        assert reference.usage.input.total == 20
        assert reference.provider_latency_ms == 200

    @pytest.mark.parametrize(
        "aigw",
        [
            _live_miss(_record(1), status="partial"),
            _live_miss(_failed(1), _failed(2)),
            {},
            {"usage_accounting": {"cache": {"status": "miss"}}},
            {"usage_accounting": "not a mapping"},
            None,
        ],
        ids=["partial-capture", "no-success", "empty", "no-attempts", "malformed", "none"],
    )
    def test_a_capture_the_live_engine_could_not_price_gives_no_reference(self, aigw: Any) -> None:
        assert cache_reference_from_captured_aigw(aigw) is None

    def test_omitted_attempts_give_no_reference(self) -> None:
        aigw = _live_miss(_record(1))
        aigw["usage_accounting"]["omitted_attempts"] = 1

        assert cache_reference_from_captured_aigw(aigw) is None

    def test_an_attempt_that_is_not_a_mapping_gives_no_reference(self) -> None:
        aigw = _live_miss(_record(1))
        aigw["usage_accounting"]["attempts"].insert(0, "garbage")

        assert cache_reference_from_captured_aigw(aigw) is None


class TestCapturedHit:
    def test_the_captured_reference_is_carried_verbatim(self) -> None:
        captured = _live_hit(_stored())
        reference = cache_reference_from_captured_aigw(captured)

        assert reference is not None
        assert reference.as_json() == captured["usage_accounting"]["cache"]["reference"]

    def test_a_hit_captured_without_a_reference_gives_none(self) -> None:
        captured = render_aigw_metadata(
            collector=None, supported=True, cache_status="hit", gateway_call_id=_CALL_ID
        )

        assert cache_reference_from_captured_aigw(captured) is None


class TestPartialStoredEntry:
    def test_a_partial_entry_prices_neither_cost_nor_tokens(self) -> None:
        # The live engine prices neither cost nor tokens of a partial capture, so a hit on the
        # entry that capture stored must not either (E4c ans:Q21b).
        reference = cache_reference_from_entry_metadata(_stored("partial"))

        assert reference.direct_cost.status == "unavailable"
        assert reference.usage.status == "unavailable"
        assert reference.usage.input.total is None
        assert reference.usage.output.total is None
        assert reference.usage.source == "cached_converted_response"


def _validator() -> Draft202012Validator:
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


class TestReplayRoute:
    def _replay(self, client: TestClient, captured: dict[str, Any]) -> dict[str, Any]:
        copy_id = seed_copy(client, account_id_of(client), [("chat", chat_body(), captured, 200)])
        response = client.post(
            f"/v1/frozen-copies/{copy_id}/chat/completions", json=chat_body(), headers=call_key()
        )
        assert response.status_code == 200, response.text
        return response.json()["_aigw"]

    def test_a_replayed_miss_carries_the_captured_price(
        self, authenticated_client: TestClient
    ) -> None:
        captured = {**chat_response("paid"), "_aigw": _live_miss(_failed(1), _record(2))}

        aigw = self._replay(authenticated_client, captured)

        reference = aigw["usage_accounting"]["cache"]["reference"]
        assert reference["direct_cost"] == _record(2).direct_cost.as_json()
        assert reference["usage"]["input"]["total"] == 20
        # Still a free hit: the replay spends nothing.
        assert aigw["request_economics"]["direct_cost_status"] == "not_applicable"
        assert aigw["usage_accounting"]["attempts"] == []
        assert aigw.pop("frozen_copy_replay") is True
        _validator().validate(aigw)

    def test_a_replayed_hit_carries_the_captured_reference(
        self, authenticated_client: TestClient
    ) -> None:
        captured_aigw = _live_hit(_stored())
        captured = {**chat_response("hit"), "_aigw": captured_aigw}

        aigw = self._replay(authenticated_client, captured)

        assert (
            aigw["usage_accounting"]["cache"]["reference"]
            == captured_aigw["usage_accounting"]["cache"]["reference"]
        )

    def test_a_replayed_body_without_aigw_has_no_reference(
        self, authenticated_client: TestClient
    ) -> None:
        aigw = self._replay(authenticated_client, chat_response("bare"))

        assert aigw["usage_accounting"]["cache"]["reference"] is None

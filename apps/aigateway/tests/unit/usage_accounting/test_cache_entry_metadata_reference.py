"""The taxonomy-side cache-entry metadata builders and the hit-path preference.

PRD ``docs/spec/2026-09-13-cache-entry-metadata-prd.md`` tasks B1, B2, B3, B5,
tests #2, #4, #13, #19, #20, #21, #23; ERD §3.2, §3.5.
"""

from __future__ import annotations

import json
from importlib.resources import files
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.plugins.taxonomy import (
    CacheReference,
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    ProviderUsageAccountingEvidence,
    RequestAccountingCollector,
    TokenUsage,
)
from aigateway.plugins.taxonomy import collector as collector_module
from aigateway.plugins.taxonomy.entry_metadata import (
    CacheEntryMetadataReferenceError,
    cache_entry_metadata_from_session,
    cache_reference_from_entry_metadata,
)
from aigateway.plugins.taxonomy.session import AccountingSession, attach_hit_metadata

_USAGE_KEYS = {"status", "source", "input", "output"}
_DIRECT_COST_KEYS = {"status", "amount", "unit", "source"}


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _session(*, provider: str = "openrouter") -> AccountingSession:
    collector = RequestAccountingCollector(
        provider=provider,
        requested_model="openrouter/x/y",
        transport="litellm_async_http",
    )
    return AccountingSession(
        provider=provider,
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )


def _observe(
    session: AccountingSession,
    *,
    evidence: ProviderUsageAccountingEvidence,
    latency_ms: int = 812,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = session.collector
    assert collector is not None
    clock = _Clock()
    monkeypatch.setattr(collector_module, "time", SimpleNamespace(monotonic=clock))
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    clock.value = latency_ms / 1000.0
    collector.on_response_completed(marker, status=200, raw_evidence={})
    collector.apply_evidence(collector.open_records()[0][0], evidence)


def _priced_evidence(*, amount: str = "0.012345") -> ProviderUsageAccountingEvidence:
    return ProviderUsageAccountingEvidence(
        supported=True,
        usage=TokenUsage(
            status="complete",
            source="provider_raw_response",
            input=InputTokenUsage(total=1234, uncached=1234, cache_read=0, cache_write=0),
            output=OutputTokenUsage(total=567),
        ),
        direct_cost=DirectCost.reported(
            amount=amount, unit="openrouter_credits", source="openrouter.usage.cost"
        ),
        response_model="anthropic/claude-fable-5",
    )


class _RecordingPlugin:
    def __init__(self, reference: CacheReference | None) -> None:
        self._reference = reference
        self.seen: list[Any] = []

    def cache_reference_from_cached_response(self, cached: Any) -> CacheReference | None:
        self.seen.append(cached)
        return self._reference


def _schema() -> dict[str, Any]:
    resource = files("aigateway.plugins.taxonomy").joinpath("usage_accounting.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


# ---- B1: build from the accounting session -------------------------------------


class TestBuildFromSession:
    def test_a_session_without_a_collector_has_no_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _session()
        session.collector = None

        assert cache_entry_metadata_from_session(session) is None

    def test_a_collector_with_no_observed_send_has_no_metadata(self) -> None:
        assert cache_entry_metadata_from_session(_session()) is None

    def test_a_failing_session_returns_none_and_never_raises(self) -> None:
        class _Exploding:
            @property
            def collector(self) -> Any:
                raise RuntimeError("collector exploded")

        # A deliberately wrong shape: the builder must swallow it, not typecheck it.
        assert cache_entry_metadata_from_session(cast(Any, _Exploding())) is None
        assert cache_entry_metadata_from_session(None) is None

    def test_a_priced_success_stores_the_canonical_usage_cost_and_latency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _session()
        _observe(session, evidence=_priced_evidence(), latency_ms=812, monkeypatch=monkeypatch)

        meta = cache_entry_metadata_from_session(session)

        assert meta is not None
        assert meta.metadata_status == "complete"
        assert meta.response_model == "anthropic/claude-fable-5"
        assert meta.usage == _priced_evidence().usage.as_json()
        assert meta.direct_cost == _priced_evidence().direct_cost.as_json()
        assert meta.provider_latency_ms == 812

    @pytest.mark.parametrize("status", ["absent", "unavailable"])
    def test_an_unpriced_provider_stores_a_null_never_zero_amount(
        self, status: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PRD test #2 / ans:Q3 / S18: a placeholder is never `0`, which would be a lie.
        session = _session(provider="anthropic")
        cost = DirectCost.absent() if status == "absent" else DirectCost.unavailable()
        _observe(
            session,
            evidence=ProviderUsageAccountingEvidence(
                supported=True, usage=TokenUsage(status="partial"), direct_cost=cost
            ),
            monkeypatch=monkeypatch,
        )

        meta = cache_entry_metadata_from_session(session)

        assert meta is not None
        assert meta.direct_cost == {
            "status": status,
            "amount": None,
            "unit": None,
            "source": None,
        }
        assert meta.direct_cost["amount"] != "0"

    @pytest.mark.parametrize("cost_status", ["unit_unknown"])
    def test_an_unknown_currency_keeps_the_amount_and_drops_the_unit(
        self, cost_status: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PRD test #19 / S14: store the amount and source, never guess a rate or a unit.
        session = _session(provider="novel")
        _observe(
            session,
            evidence=ProviderUsageAccountingEvidence(
                supported=True,
                usage=TokenUsage(status="partial"),
                direct_cost=DirectCost.unit_unknown(amount="7", source="novel.usage.cost"),
            ),
            monkeypatch=monkeypatch,
        )

        meta = cache_entry_metadata_from_session(session)

        assert meta is not None
        assert meta.direct_cost == {
            "status": cost_status,
            "amount": "7",
            "unit": None,
            "source": "novel.usage.cost",
        }
        assert "usd" not in json.dumps(meta.as_json_dict()).lower()

    def test_a_partial_capture_is_never_certified_as_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _session()
        _observe(
            session,
            evidence=ProviderUsageAccountingEvidence(
                supported=True, usage=TokenUsage(status="partial")
            ),
            monkeypatch=monkeypatch,
        )
        collector = session.collector
        assert collector is not None
        collector.mark_incomplete()

        meta = cache_entry_metadata_from_session(session)

        assert meta is not None
        assert meta.metadata_status == "partial"

    def test_provider_latency_is_summed_across_every_observed_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _session()
        collector = session.collector
        assert collector is not None
        clock = _Clock()
        monkeypatch.setattr(collector_module, "time", SimpleNamespace(monotonic=clock))
        collector.begin_dispatch()
        first = object()
        collector.on_send_admitted(first)
        clock.value = 0.100
        collector.on_response_completed(first, status=500, raw_evidence={})
        collector.on_send_admitted(object())
        clock.value = 0.812
        collector.on_response_completed(
            collector._sends[-1].request_ref, status=200, raw_evidence={}
        )
        collector.apply_evidence(collector.open_records()[0][0], _priced_evidence())

        meta = cache_entry_metadata_from_session(session)

        assert meta is not None
        assert meta.provider_latency_ms == 812


# ---- B2: the reference the hit path exposes ------------------------------------


class TestReferenceFromMetadata:
    def test_the_stored_usage_round_trips_with_a_rewritten_source(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete",
            usage=_priced_evidence().usage.as_json(),
            direct_cost=_priced_evidence().direct_cost.as_json(),
            provider_latency_ms=812,
        )

        reference = cache_reference_from_entry_metadata(meta)

        assert reference.usage.status == "complete"
        assert reference.usage.source == "cached_converted_response"
        assert reference.usage.input.total == 1234
        assert reference.usage.output.total == 567

    def test_the_stored_cost_is_passed_through_verbatim(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete",
            usage=_priced_evidence().usage.as_json(),
            direct_cost=_priced_evidence().direct_cost.as_json(),
        )

        reference = cache_reference_from_entry_metadata(meta)

        assert reference.direct_cost.status == "reported"
        assert reference.direct_cost.amount == "0.012345"
        assert reference.direct_cost.unit == "openrouter_credits"

    def test_a_partial_capture_never_certifies_a_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _session()
        _observe(session, evidence=_priced_evidence(), monkeypatch=monkeypatch)
        collector = session.collector
        assert collector is not None
        collector.mark_incomplete()
        meta = cache_entry_metadata_from_session(session)
        assert meta is not None and meta.metadata_status == "partial"

        reference = cache_reference_from_entry_metadata(meta)

        assert reference.direct_cost.status == "unavailable"
        assert reference.direct_cost.amount is None

    def test_an_archive_paired_block_is_certified_like_a_reported_one(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="archive_paired",
            usage=_priced_evidence().usage.as_json(),
            direct_cost=DirectCost.archive_matched(
                amount="0.5",
                unit="usd",
                source="draco-archive-20260806-170633-251a:metrics/phase3.eval.jsonl",
            ).as_json(),
        )

        reference = cache_reference_from_entry_metadata(meta)

        assert reference.direct_cost.status == "archive_matched"
        assert reference.direct_cost.unit == "usd"

    def test_a_corrupt_stored_cost_raises_the_narrow_internal_error(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete",
            direct_cost={"status": "reported", "amount": "NaN", "unit": "usd", "source": "s"},
        )

        with pytest.raises(CacheEntryMetadataReferenceError):
            cache_reference_from_entry_metadata(meta)

    @pytest.mark.parametrize(
        "poison",
        [
            {"status": "reported", "amount": "1", "unit": "usd", "source": "\u00b5"},
            {"status": "made_up", "amount": None, "unit": None, "source": None},
            {"status": "unit_unknown", "amount": "1", "unit": "usd", "source": "s"},
            {"status": "reported", "amount": "1.0", "unit": "usd", "source": "s"},
        ],
    )
    def test_non_ascii_non_canonical_or_unknown_money_is_refused(self, poison: dict) -> None:
        # PRD test #23: the canonical-decimal and ASCII validators are reused, not re-written.
        meta = CacheEntryMetadata(metadata_status="complete", direct_cost=poison)

        with pytest.raises(CacheEntryMetadataReferenceError):
            cache_reference_from_entry_metadata(meta)

    def test_a_corrupt_usage_block_raises_the_narrow_internal_error(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete",
            usage={
                "status": "complete",
                "source": "provider_raw_response",
                "input": {"total": "not-a-number"},
                "output": {"total": 1},
            },
        )

        with pytest.raises(CacheEntryMetadataReferenceError):
            cache_reference_from_entry_metadata(meta)


# ---- B3: archive_matched and the reference latency -----------------------------


class TestArchiveMatchedStatus:
    def test_archive_matched_requires_amount_unit_and_source(self) -> None:
        with pytest.raises(ValueError):
            DirectCost(status="archive_matched", amount="1")

    def test_archive_matched_refuses_a_non_canonical_amount(self) -> None:
        with pytest.raises(ValueError):
            DirectCost.archive_matched(amount="1.0", unit="usd", source="draco")

    def test_archive_matched_carries_its_evidence_through_as_json(self) -> None:
        cost = DirectCost.archive_matched(amount="0.5", unit="usd", source="draco")

        assert cost.as_json() == {
            "status": "archive_matched",
            "amount": "0.5",
            "unit": "usd",
            "source": "draco",
        }


class TestReferenceLatency:
    def test_a_stored_latency_is_reported_verbatim(self) -> None:
        # PRD test #20 / ans:Q1: copied from the block, never recomputed.
        meta = CacheEntryMetadata(
            metadata_status="complete",
            usage=_priced_evidence().usage.as_json(),
            direct_cost=_priced_evidence().direct_cost.as_json(),
            provider_latency_ms=812,
        )

        reference = cache_reference_from_entry_metadata(meta)

        assert reference.as_json()["latency"] == {"provider_latency_ms": 812}

    def test_a_null_latency_is_omitted_from_the_reference(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete",
            usage=_priced_evidence().usage.as_json(),
            direct_cost=_priced_evidence().direct_cost.as_json(),
            provider_latency_ms=None,
        )

        assert "latency" not in cache_reference_from_entry_metadata(meta).as_json()

    def test_the_constructor_still_refuses_current_request_spend(self) -> None:
        # PRD test #4 / I2: the raising guard is the invariant, not a convention.
        with pytest.raises(ValueError):
            CacheReference(incurred_in_current_request=True)  # type: ignore[arg-type]


# ---- B5: the hit path prefers the stored block ---------------------------------


class TestHitPrefersStoredMetadata:
    def test_a_stored_block_is_used_and_the_plugin_is_not_asked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = _session()
        _observe(session, evidence=_priced_evidence(), latency_ms=812, monkeypatch=monkeypatch)
        meta = cache_entry_metadata_from_session(session)
        plugin = _RecordingPlugin(reference=CacheReference(direct_cost=DirectCost.unavailable()))

        # A hit session has observed no send of its own: the stored block is the ONLY
        # evidence, and the new-attempt count must stay 0.
        body = attach_hit_metadata({"id": "gen-1"}, _session(), plugin=plugin, entry_metadata=meta)

        assert plugin.seen == []
        reference = body["_aigw"]["usage_accounting"]["cache"]["reference"]
        assert reference["direct_cost"]["status"] == "reported"
        assert reference["direct_cost"]["amount"] == "0.012345"
        assert reference["latency"] == {"provider_latency_ms": 812}
        assert reference["incurred_in_current_request"] is False
        assert reference["usage"]["source"] == "cached_converted_response"
        assert body["_aigw"]["request_economics"]["observed_new_attempts"] == 0
        assert body["_aigw"]["usage_accounting"]["attempts"] == []

    def test_no_stored_block_falls_back_to_the_plugin_mapper(self) -> None:
        # PRD test #13 / S4: a legacy row keeps today's behaviour exactly.
        plugin_reference = CacheReference(direct_cost=DirectCost.unavailable())
        plugin = _RecordingPlugin(reference=plugin_reference)
        cached = {"id": "gen-1", "usage": {"cost": 0.5, "prompt_tokens": 56}}

        body = attach_hit_metadata(cached, _session(), plugin=plugin, entry_metadata=None)

        assert plugin.seen == [cached]
        reference = body["_aigw"]["usage_accounting"]["cache"]["reference"]
        assert reference["direct_cost"]["status"] == "unavailable"
        assert reference["direct_cost"]["amount"] is None
        assert "latency" not in reference
        assert "0.5" not in json.dumps(reference)

    def test_an_unusable_stored_block_falls_back_to_the_plugin_mapper(self) -> None:
        plugin_reference = CacheReference(direct_cost=DirectCost.absent())
        plugin = _RecordingPlugin(reference=plugin_reference)
        corrupt = CacheEntryMetadata(
            metadata_status="complete",
            direct_cost={"status": "reported", "amount": "NaN", "unit": "usd", "source": "s"},
        )

        body = attach_hit_metadata(
            {"id": "gen-1"}, _session(), plugin=plugin, entry_metadata=corrupt
        )

        assert plugin.seen == [{"id": "gen-1"}]
        reference = body["_aigw"]["usage_accounting"]["cache"]["reference"]
        assert reference["direct_cost"]["status"] == "absent"

    def test_the_replayed_cache_row_is_never_mutated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _session()
        _observe(session, evidence=_priced_evidence(), monkeypatch=monkeypatch)
        meta = cache_entry_metadata_from_session(session)
        cached = {"id": "gen-1"}

        attach_hit_metadata(cached, session, plugin=_RecordingPlugin(None), entry_metadata=meta)

        assert cached == {"id": "gen-1"}


# ---- Serialization guarantees ---------------------------------------------------


class TestBlockShapeAndCodec:
    def test_the_block_carries_no_prompt_credential_or_account_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PRD test #21 / §4.5: assert on the serialized key set, not on a sample value.
        session = _session()
        _observe(session, evidence=_priced_evidence(), monkeypatch=monkeypatch)
        meta = cache_entry_metadata_from_session(session)
        assert meta is not None

        payload = meta.serialize()
        assert payload is not None

        block = json.loads(payload)

        assert set(block) == {
            "schema",
            "metadata_status",
            "observed_at",
            "response_model",
            "usage",
            "direct_cost",
            "latency",
        }
        assert set(block["usage"]) == _USAGE_KEYS
        assert set(block["direct_cost"]) == _DIRECT_COST_KEYS
        assert set(block["latency"]) == {"provider_latency_ms"}
        serialized = json.dumps(block).lower()
        for forbidden in ("prompt", "message", "api_key", "credential", "account", "sk-"):
            assert forbidden not in serialized

    @pytest.mark.parametrize(
        "direct_cost",
        [
            DirectCost.reported(amount="0.012345", unit="openrouter_credits", source="s").as_json(),
            DirectCost.absent().as_json(),
            DirectCost.unavailable().as_json(),
            DirectCost.unit_unknown(amount="7", source="s").as_json(),
            DirectCost.archive_matched(amount="0.5", unit="usd", source="draco").as_json(),
            # The amounts most likely to lose their exact spelling in transit: a sub-cent
            # value that `str(float)` would render in scientific notation, and an amount with
            # more significant digits than a binary float can hold. A whole number is spelled
            # `"1"` — `"1.0"` is not canonical and the constructor refuses it outright.
            DirectCost.reported(
                amount="0.0000001", unit="openrouter_credits", source="s"
            ).as_json(),
            DirectCost.reported(
                amount="0.10000000000000000555", unit="openrouter_credits", source="s"
            ).as_json(),
            DirectCost.reported(amount="1", unit="usd", source="s").as_json(),
        ],
    )
    # A latency of 0 is a real measurement and must not be confused with an absent one; the
    # large value guards the int64 end of the range.
    @pytest.mark.parametrize("latency", [None, 0, 1, 812, 2**31])
    def test_a_block_round_trips_through_json_exactly(
        self, direct_cost: dict, latency: int | None
    ) -> None:
        # PRD test #23: the universal constraint, reused on every cost vocabulary.
        meta = CacheEntryMetadata(
            metadata_status="complete",
            observed_at="2026-09-13T12:00:00Z",
            response_model="anthropic/claude-fable-5",
            usage=_priced_evidence().usage.as_json(),
            direct_cost=direct_cost,
            provider_latency_ms=latency,
        )

        restored = CacheEntryMetadata.parse(meta.serialize())

        assert restored is not None
        assert restored == meta
        assert restored.as_json_dict() == meta.as_json_dict()

    def test_a_non_finite_stored_number_is_rejected_by_the_parser(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete",
            usage={**_priced_evidence().usage.as_json(), "input": {"total": 1234}, "amount": 1},
        )
        serialized = meta.serialize()
        assert serialized is not None
        payload = serialized.replace('"amount":1', '"amount":NaN', 1)

        assert CacheEntryMetadata.parse(payload) is None

    def test_a_nan_never_serializes(self) -> None:
        meta = CacheEntryMetadata(
            metadata_status="complete", usage={"input": {"total": float("nan")}}
        )

        with pytest.raises(ValueError):
            meta.serialize()


# ---- B4: the packaged JSON Schema ------------------------------------------------


class TestPackagedSchema:
    def test_the_schema_admits_archive_matched_and_a_latency_block(self) -> None:
        schema = _schema()

        assert "archive_matched" in schema["$defs"]["direct_cost"]["properties"]["status"]["enum"]
        assert "latency" in schema["$defs"]["cache_reference"]["properties"]
        assert schema["$defs"]["cache_reference"]["additionalProperties"] is False

    def test_a_rendered_hit_with_latency_and_archive_matched_validates(self, monkeypatch) -> None:
        session = _session(provider="openrouter")
        _observe(
            session,
            evidence=ProviderUsageAccountingEvidence(
                supported=True,
                usage=_priced_evidence().usage,
                direct_cost=DirectCost.archive_matched(amount="0.5", unit="usd", source="draco"),
            ),
            latency_ms=812,
            monkeypatch=monkeypatch,
        )
        meta = cache_entry_metadata_from_session(session)
        assert meta is not None
        body = attach_hit_metadata(
            {"id": "gen-1"}, session, plugin=_RecordingPlugin(None), entry_metadata=meta
        )

        Draft202012Validator(_schema()).validate(body["_aigw"])

    def test_a_legacy_hit_without_latency_still_validates(self) -> None:
        plugin = _RecordingPlugin(reference=CacheReference(direct_cost=DirectCost.unavailable()))
        body = attach_hit_metadata({"id": "gen-1"}, _session(), plugin=plugin, entry_metadata=None)

        Draft202012Validator(_schema()).validate(body["_aigw"])

"""Authoritative exact fixture matrix for the evolving accounting contract."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from aigateway.plugins.anthropic_provider.usage_accounting import (
    cache_reference_from_cached as anthropic_cache_reference_from_cached,
)
from aigateway.plugins.anthropic_provider.usage_accounting import (
    normalize_anthropic_usage_accounting,
)
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin
from aigateway.plugins.openrouter_provider.usage_accounting import (
    cache_reference_from_cached as openrouter_cache_reference_from_cached,
)
from aigateway.plugins.openrouter_provider.usage_accounting import (
    normalize_openrouter_usage_accounting,
)
from aigateway.plugins.taxonomy import (
    CacheReference,
    CacheWriteTTL,
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    PricingContext,
    ProviderAttemptRecord,
    ProviderExtension,
    TokenUsage,
)
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.plugins.taxonomy.session import usage_accounting_strategy_for

_CALL_ID = "call_" + "f" * 32

_REQUIRED_METADATA_FIXTURES = {
    "openrouter_full_success",
    "openrouter_explicit_zero",
    "openrouter_missing_evidence",
    "openrouter_retry",
    "openrouter_failure_with_usage",
    "anthropic_full_cache_ttl_success",
    "anthropic_missing_cache_evidence",
    "anthropic_service_tier_tool_usage",
    "anthropic_cache_replay",
    "hidden_transport_resend",
    "gateway_overload_retry",
    "response_less_transport_failure",
    "conversion_failure",
    "unsupported_provider_miss",
    "cache_hit_reference",
    "bounds_overflow",
    "huggingface_pinned_backend",
    "huggingface_unpinned_backend",
}
_ROUTE_ONLY_ACCEPTANCE = {
    "default_on_response_accounting",
    "streaming_accounting_bypass",
}
_EXPECTED_FIXTURE_SHA256 = {
    "anthropic_cache_replay": ("47c556bed30b8579f1ef0f9559ec0d1348f0d9bb38cbd5720e809e867193b577"),
    "anthropic_full_cache_ttl_success": (
        "6d2d385a3b1c2f287b61dbafdcee126bb9b0f6718902b29f890105ebc02ef5d4"
    ),
    "anthropic_missing_cache_evidence": (
        "282eb9182ab8e861af349597cf3a52d5f857628acb01a296d6d0884950721349"
    ),
    "anthropic_service_tier_tool_usage": (
        "83c95a166e5fc4858f49babe15b3c414af6ac85ad5a1859dac09a76f3793a7e8"
    ),
    "bounds_overflow": ("124803ae0df7066773af1d8c016c008f8398e2bc703d558e5df07738bf94ec54"),
    "cache_hit_reference": ("f8f73e93f1f78efe022b92387c74c04357129cf79012a55b2610675b6ca0d6fe"),
    "conversion_failure": ("e8d5b40f0ec62aa78aba88d1fe0c8b466621b2e34f9cae55b01d8a548a0e1dff"),
    "gateway_overload_retry": ("e94349eef821c7d1e5e4767973bd2e33fff03ec573b8122ca53b6bafd5e4f446"),
    "hidden_transport_resend": ("4db8988561ef08e2df5b1652857747a2ce070f841ed050af722483f865d409ff"),
    "huggingface_pinned_backend": (
        "ad86415a618a16d3b5f55865e9c4380ad32179944d6d374c1dc6a49175f16176"
    ),
    "huggingface_unpinned_backend": (
        "6d719571ce09c812210b59843d20227fa877ada58b5fa53ecd3028955ee89376"
    ),
    "openrouter_explicit_zero": (
        "11cde20368800309d23654b0f41e21ce464d8c48a1364b41dcd9b67239523376"
    ),
    "openrouter_failure_with_usage": (
        "6cc20ba612e2dcd0dfb51a5862fac5391e13f9d1e1f633448cc8ff7d81405e39"
    ),
    "openrouter_full_success": ("33679566b14a19d4e99a3aef3caeae3f4bd187f6c4f0353454bd6ad55c943987"),
    "openrouter_missing_evidence": (
        "6b1f9cff9d4c56f3c4540c7bf647ca5c8196eaae913c022f1785fd34afa7c6b7"
    ),
    "openrouter_retry": ("4db8988561ef08e2df5b1652857747a2ce070f841ed050af722483f865d409ff"),
    "response_less_transport_failure": (
        "d20f7e1c93b53883b3457bfa90018a3905764e43d02ae01c84fb5f668ba2f13c"
    ),
    "unsupported_provider_miss": (
        "9830bed0c2aceb172795a45b513d6ee3e4d9aa918a0218be7988943f81537a97"
    ),
}


class _Collector:
    def __init__(
        self,
        records: tuple[ProviderAttemptRecord, ...],
        *,
        status: str = "complete",
    ) -> None:
        self._records = records
        self._status = status

    def records(self) -> tuple[ProviderAttemptRecord, ...]:
        return self._records

    def status(self) -> str:
        return self._status


def _schema() -> dict[str, Any]:
    resource = files("aigateway.plugins.taxonomy").joinpath("usage_accounting.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _usage(
    *,
    status: str = "complete",
    source: str = "provider_raw_response",
    input_total: int | None = 2,
    uncached: int | None = 2,
    cache_read: int | None = None,
    cache_write: int | None = None,
    cache_write_by_ttl: tuple[CacheWriteTTL, ...] = (),
    output_total: int | None = 1,
    reasoning: int | None = None,
) -> TokenUsage:
    return TokenUsage(
        status=status,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        input=InputTokenUsage(
            total=input_total,
            uncached=uncached,
            cache_read=cache_read,
            cache_write=cache_write,
            cache_write_by_ttl=cache_write_by_ttl,
        ),
        output=OutputTokenUsage(total=output_total, reasoning=reasoning),
    )


def _record(
    sequence: int,
    *,
    provider: str = "openrouter",
    dispatch_index: int = 1,
    attempt_index: int = 1,
    outcome: str = "succeeded",
    http_status: int | None = 200,
    latency_ms: int | None = 1,
    usage: TokenUsage | None = None,
    pricing_context: PricingContext | None = None,
    direct_cost: DirectCost | None = None,
    provider_extensions: tuple[ProviderExtension, ...] = (),
    failure_code: str | None = None,
    response_model: str | None = "fixture-model",
    provider_response_id: str | None = "",
) -> ProviderAttemptRecord:
    return ProviderAttemptRecord(
        attempt_id=f"attempt_{sequence:032x}",
        sequence=sequence,
        dispatch_index=dispatch_index,
        attempt_index=attempt_index,
        provider=provider,
        requested_model=f"{provider}/fixture-model",
        response_model=response_model,
        provider_response_id=(
            f"response-{sequence}" if provider_response_id == "" else provider_response_id
        ),
        transport="litellm_async_http",
        outcome=outcome,  # type: ignore[arg-type]
        http_status=http_status,
        latency_ms=latency_ms,
        usage=usage or _usage(),
        pricing_context=pricing_context or PricingContext(),
        direct_cost=direct_cost
        or DirectCost.reported(
            amount="0.001",
            unit="openrouter_credits",
            source="openrouter.usage.cost",
        ),
        provider_extensions=provider_extensions,
        failure_code=failure_code,
    )


def _anthropic_record(
    sequence: int, raw_usage: dict[str, Any], **overrides: Any
) -> ProviderAttemptRecord:
    evidence = normalize_anthropic_usage_accounting(
        request_body={"model": "anthropic/fixture-model"},
        raw_response={
            "id": f"response-{sequence}",
            "model": "fixture-model",
            "usage": raw_usage,
        },
        final_response=None,
    )
    return _record(
        sequence,
        provider="anthropic",
        usage=evidence.usage,
        pricing_context=evidence.pricing_context,
        direct_cost=evidence.direct_cost,
        provider_extensions=evidence.provider_extensions,
        response_model=evidence.response_model,
        provider_response_id=evidence.provider_response_id,
        **overrides,
    )


def _openrouter_record(
    sequence: int, raw_usage: dict[str, Any] | None, **overrides: Any
) -> ProviderAttemptRecord:
    raw_response = (
        {
            "id": f"response-{sequence}",
            "model": "fixture-model",
            "usage": raw_usage,
        }
        if raw_usage is not None
        else None
    )
    evidence = normalize_openrouter_usage_accounting(
        request_body={"model": "openrouter/fixture-model"},
        raw_response=raw_response,
        final_response=None,
        failed=overrides.get("outcome", "succeeded") != "succeeded",
    )
    return _record(
        sequence,
        usage=evidence.usage,
        pricing_context=evidence.pricing_context,
        direct_cost=evidence.direct_cost,
        provider_extensions=evidence.provider_extensions,
        response_model=evidence.response_model,
        provider_response_id=evidence.provider_response_id,
        **overrides,
    )


def _reference(value: CacheReference | None) -> CacheReference:
    assert value is not None
    return value


def _render(
    records: tuple[ProviderAttemptRecord, ...] = (),
    *,
    supported: bool = True,
    cache_status: str = "miss",
    capture_status: str = "complete",
    cache_reference: CacheReference | None = None,
) -> dict[str, Any]:
    collector: Any = _Collector(records, status=capture_status) if supported else None
    return render_aigw_metadata(
        collector=collector,
        supported=supported,
        cache_status=cache_status,  # type: ignore[arg-type]
        gateway_call_id=_CALL_ID,
        cache_reference=cache_reference,
    )


def _release_fixtures() -> dict[str, dict[str, Any]]:
    transport_failure = _openrouter_record(
        1,
        None,
        outcome="transport_error",
        http_status=None,
        latency_ms=None,
        failure_code="transport_connect_error",
    )
    openrouter_full_usage = {
        "prompt_tokens": 56,
        "completion_tokens": 41,
        "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 6},
        "completion_tokens_details": {"reasoning_tokens": 8},
        "cost": Decimal("0.001"),
        "cost_details": {"upstream_inference_cost": Decimal("0.0008")},
    }
    retry_success = _openrouter_record(2, openrouter_full_usage, attempt_index=2)
    anthropic_full = _anthropic_record(
        1,
        {
            "input_tokens": 100,
            "output_tokens": 25,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 10,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 7,
                "ephemeral_1h_input_tokens": 3,
            },
            "output_tokens_details": {"thinking_tokens": 7},
            "service_tier": "standard",
        },
    )
    cache_reference = _reference(
        openrouter_cache_reference_from_cached(
            {"usage": {"prompt_tokens": 2, "completion_tokens": 1, "cost": "0.001"}}
        )
    )
    anthropic_cache_reference = _reference(
        anthropic_cache_reference_from_cached(
            {
                "usage": {
                    "prompt_tokens": 130,
                    "completion_tokens": 25,
                    "prompt_tokens_details": {
                        "text_tokens": 100,
                        "cached_tokens": 20,
                        "cache_creation_tokens": 10,
                        "cache_creation_token_details": {
                            "ephemeral_5m_input_tokens": 7,
                            "ephemeral_1h_input_tokens": 3,
                        },
                    },
                }
            }
        )
    )
    fixtures = {
        "openrouter_full_success": _render((_openrouter_record(1, openrouter_full_usage),)),
        "openrouter_explicit_zero": _render(
            (
                _openrouter_record(
                    1,
                    {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                        "cost": 0,
                    },
                ),
            )
        ),
        "openrouter_missing_evidence": _render((_openrouter_record(1, {}),)),
        "openrouter_retry": _render((transport_failure, retry_success)),
        "openrouter_failure_with_usage": _render(
            (
                _openrouter_record(
                    1,
                    {"prompt_tokens": 2, "cost": Decimal("0.001")},
                    outcome="provider_error",
                    http_status=429,
                    failure_code="provider_status_error",
                ),
            )
        ),
        "anthropic_full_cache_ttl_success": _render((anthropic_full,)),
        "anthropic_missing_cache_evidence": _render(
            (
                _anthropic_record(
                    1,
                    {"input_tokens": 2, "output_tokens": 1},
                ),
            )
        ),
        "anthropic_service_tier_tool_usage": _render(
            (
                _anthropic_record(
                    1,
                    {
                        "input_tokens": 2,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "service_tier": "priority",
                        "server_tool_use": {"web_search_requests": 1},
                    },
                ),
            )
        ),
        "anthropic_cache_replay": _render(
            cache_status="hit",
            cache_reference=anthropic_cache_reference,
        ),
        "hidden_transport_resend": _render((transport_failure, retry_success)),
        "gateway_overload_retry": _render(
            (
                _openrouter_record(
                    1,
                    {},
                    outcome="provider_error",
                    http_status=529,
                    failure_code="provider_status_error",
                ),
                _openrouter_record(
                    2,
                    openrouter_full_usage,
                    dispatch_index=2,
                    attempt_index=1,
                ),
            )
        ),
        "response_less_transport_failure": _render((transport_failure,)),
        "conversion_failure": _render(
            (
                _openrouter_record(
                    1,
                    openrouter_full_usage,
                    outcome="conversion_error",
                    failure_code="response_conversion_failed",
                ),
            )
        ),
        "unsupported_provider_miss": _render(supported=False),
        "cache_hit_reference": _render(
            cache_status="hit",
            cache_reference=cache_reference,
        ),
        "bounds_overflow": _render(tuple(_record(index) for index in range(1, 66))),
        "huggingface_pinned_backend": _render(
            (
                _record(
                    1,
                    provider="huggingface",
                    pricing_context=PricingContext(backend="hf-inference-endpoint"),
                    direct_cost=DirectCost.unavailable(),
                ),
            )
        ),
        "huggingface_unpinned_backend": _render(
            (
                _record(
                    1,
                    provider="huggingface",
                    pricing_context=PricingContext(backend=None),
                    direct_cost=DirectCost.unavailable(),
                ),
            )
        ),
    }
    return fixtures


@pytest.fixture(scope="module")
def release_fixtures() -> dict[str, dict[str, Any]]:
    return _release_fixtures()


def test_release_fixture_matrix_is_complete(
    release_fixtures: dict[str, dict[str, Any]],
) -> None:
    assert set(release_fixtures) == _REQUIRED_METADATA_FIXTURES
    assert _ROUTE_ONLY_ACCEPTANCE == {
        "default_on_response_accounting",
        "streaming_accounting_bypass",
    }


def test_release_fixture_canonical_json_is_immutable(
    release_fixtures: dict[str, dict[str, Any]],
) -> None:
    actual = {
        name: sha256(
            json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        for name, metadata in release_fixtures.items()
    }
    assert actual == _EXPECTED_FIXTURE_SHA256


def test_every_release_fixture_uses_schema_valid_exact_ids_and_wire_shape(
    release_fixtures: dict[str, dict[str, Any]],
) -> None:
    validator = Draft202012Validator(_schema())
    for name, metadata in release_fixtures.items():
        errors = sorted(validator.iter_errors(metadata), key=lambda error: list(error.path))
        assert errors == [], f"{name}: {[error.message for error in errors]}"
        assert metadata["usage_accounting"]["gateway_call_id"] == _CALL_ID
        for attempt in metadata["usage_accounting"]["attempts"]:
            assert len(attempt["attempt_id"]) == len("attempt_") + 32


def test_release_fixtures_pin_retry_failure_cache_and_bound_semantics(
    release_fixtures: dict[str, dict[str, Any]],
) -> None:
    hidden = release_fixtures["hidden_transport_resend"]["usage_accounting"]["attempts"]
    overload = release_fixtures["gateway_overload_retry"]["usage_accounting"]["attempts"]
    assert [(row["dispatch_index"], row["attempt_index"]) for row in hidden] == [(1, 1), (1, 2)]
    assert [(row["dispatch_index"], row["attempt_index"]) for row in overload] == [(1, 1), (2, 1)]

    response_less = release_fixtures["response_less_transport_failure"]["usage_accounting"]
    assert response_less["attempts"][0]["http_status"] is None
    assert response_less["attempts"][0]["latency_ms"] is None
    assert response_less["attempts"][0]["outcome"] == "transport_error"
    assert response_less["attempts"][0]["response_model"] is None
    assert response_less["attempts"][0]["provider_response_id"] is None

    cache_hit = release_fixtures["cache_hit_reference"]
    assert cache_hit["usage_accounting"]["attempts"] == []
    assert (
        cache_hit["usage_accounting"]["cache"]["reference"]["incurred_in_current_request"] is False
    )
    assert cache_hit["request_economics"]["observed_new_attempts"] == 0

    overflow = release_fixtures["bounds_overflow"]
    assert overflow["usage_accounting"]["observed_attempts"] == 65
    assert overflow["usage_accounting"]["rendered_attempts"] == 64
    assert overflow["usage_accounting"]["omitted_attempts"] == 1
    assert overflow["usage_accounting"]["capture_status"] == "partial"
    assert overflow["request_economics"]["known_direct_cost_subtotals"] == []

    missing_cache = release_fixtures["anthropic_missing_cache_evidence"]["usage_accounting"][
        "attempts"
    ][0]
    assert missing_cache["usage"]["status"] == "partial"
    assert missing_cache["usage"]["input"] == {
        "total": None,
        "uncached": 2,
        "cache_read": None,
        "cache_write": None,
        "cache_write_by_ttl": [],
    }

    tool_attempt = release_fixtures["anthropic_service_tier_tool_usage"]["usage_accounting"][
        "attempts"
    ][0]
    assert tool_attempt["usage"]["input"]["total"] == 2
    assert tool_attempt["pricing_context"]["service_tier"] == "priority"
    assert tool_attempt["provider_extensions"] == [
        {
            "namespace": "anthropic.usage",
            "facts": [
                {
                    "name": "web_search_requests",
                    "kind": "integer",
                    "value": 1,
                    "unit": "requests",
                    "source": "anthropic.usage.server_tool_use.web_search_requests",
                }
            ],
            "truncated": False,
        }
    ]


def test_release_fixture_rejects_raw_provider_text_and_nested_objects(
    release_fixtures: dict[str, dict[str, Any]],
) -> None:
    clean = release_fixtures["openrouter_full_success"]
    assert "PRIVATE PROMPT" not in json.dumps(clean)

    leaked = deepcopy(clean)
    leaked["usage_accounting"]["attempts"][0]["provider_native_body"] = {"prompt": "PRIVATE PROMPT"}
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(leaked)


def test_huggingface_fixtures_prove_canonical_fit_without_claiming_support(
    release_fixtures: dict[str, dict[str, Any]],
) -> None:
    pinned = release_fixtures["huggingface_pinned_backend"]["usage_accounting"]["attempts"][0]
    unpinned = release_fixtures["huggingface_unpinned_backend"]["usage_accounting"]["attempts"][0]
    assert pinned["pricing_context"]["backend"] == "hf-inference-endpoint"
    assert unpinned["pricing_context"]["backend"] is None
    assert usage_accounting_strategy_for(HuggingFaceProviderPlugin()).is_supported is False


def test_release_fixture_exercises_private_input_without_publishing_it() -> None:
    sentinel = "PRIVATE PROMPT"
    request_body = {
        "model": "openrouter/fixture-model",
        "messages": [{"role": "user", "content": sentinel}],
    }
    raw_response = {
        "id": "response-1",
        "model": "fixture-model",
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "cost": Decimal("0.001"),
        },
        "provider_debug": {"prompt": sentinel},
    }
    evidence = normalize_openrouter_usage_accounting(
        request_body=request_body,
        raw_response=raw_response,
        final_response=None,
    )
    fixture = _render(
        (
            _record(
                1,
                usage=evidence.usage,
                pricing_context=evidence.pricing_context,
                direct_cost=evidence.direct_cost,
                provider_extensions=evidence.provider_extensions,
                response_model=evidence.response_model,
                provider_response_id=evidence.provider_response_id,
            ),
        )
    )

    assert sentinel in str({"request": request_body, "response": raw_response})
    assert sentinel not in json.dumps(fixture)
    Draft202012Validator(_schema()).validate(fixture)
    canonical = json.dumps(fixture, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert (
        sha256(canonical.encode()).hexdigest()
        == "2a38f24ed0da44a4c1057774deffd5a08242235ebebe8b770c430f523c47ece5"
    )

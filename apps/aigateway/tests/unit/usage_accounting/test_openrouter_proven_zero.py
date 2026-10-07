"""OpenRouter zero-completion insurance accounting regressions (OME-1446)."""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import (
    DirectCost,
    ProviderUsageAccountingEvidence,
    RequestAccountingCollector,
)
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/google/gemini-2.0-flash-001"


def _insured_error(
    *,
    error_type: str = "rate_limit_exceeded",
    is_byok: bool = False,
    pipeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "error": {"code": 429, "metadata": {"error_type": error_type}},
        "openrouter_metadata": {
            "attempt": 1,
            "is_byok": is_byok,
            "pipeline": pipeline if pipeline is not None else [],
        },
    }


def _collector(*attempts: tuple[int, dict[str, Any]]) -> RequestAccountingCollector:
    collector = RequestAccountingCollector(
        provider="openrouter",
        requested_model=_MODEL,
        transport="litellm_async_http",
    )
    for status, raw_response in attempts:
        collector.begin_dispatch()
        marker = object()
        collector.on_send_admitted(marker)
        collector.on_response_completed(marker, status=status, raw_evidence=raw_response)
    return collector


def _finalize(collector: RequestAccountingCollector, final_response: dict[str, Any] | None) -> None:
    session = AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )
    finalize_provider_evidence(
        session,
        plugin=OpenRouterProviderPlugin(),
        request_body={"model": _MODEL},
        final_response=final_response,
    )


def test_router_metadata_header_is_gateway_owned_and_enabled() -> None:
    body = OpenRouterProviderPlugin().prepare_chat_body(
        {
            "model": _MODEL,
            "messages": [{"role": "user", "content": "hello"}],
            "extra_headers": {
                "x-openrouter-metadata": "disabled",
                "X-OpenRouter-Experimental-Metadata": "disabled",
            },
        }
    )

    headers = body["extra_headers"]
    metadata_headers = [key for key in headers if key.lower() == "x-openrouter-metadata"]
    assert metadata_headers == ["X-OpenRouter-Metadata"]
    assert headers["X-OpenRouter-Metadata"] == "enabled"
    assert "X-OpenRouter-Experimental-Metadata" not in headers


@pytest.mark.asyncio
async def test_router_metadata_is_not_returned_or_available_to_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-1",
                "choices": [{"message": {"content": "ok"}}],
                "openrouter_metadata": {
                    "is_byok": False,
                    "attempts": [{"provider": "PrivateRoute", "status": 200}],
                },
            }
        )

    monkeypatch.setattr("litellm.acompletion", _fake_acompletion)
    monkeypatch.setattr(
        "aigateway.plugins.openrouter_provider.plugin._has_unsafe_litellm_global_state",
        lambda *_args: False,
    )

    payload = await OpenRouterProviderPlugin().chat_completion({"model": _MODEL})

    assert "openrouter_metadata" not in payload
    assert payload["choices"][0]["message"]["content"] == "ok"


def test_provider_guaranteed_zero_is_an_exact_zero_cost_value() -> None:
    cost = DirectCost.provider_guaranteed_zero(
        unit="openrouter_credits",
        source="openrouter.zero_completion_insurance",
    )

    assert cost.as_json() == {
        "status": "provider_guaranteed_zero",
        "amount": "0",
        "unit": "openrouter_credits",
        "source": "openrouter.zero_completion_insurance",
    }
    with pytest.raises(ValueError, match="exact zero"):
        DirectCost(
            status="provider_guaranteed_zero",
            amount="0.1",
            unit="openrouter_credits",
            source="openrouter.zero_completion_insurance",
        )


def test_native_429_with_complete_non_byok_metadata_is_certified_without_token_zeros() -> None:
    collector = _collector(
        (
            429,
            _insured_error(
                pipeline=[
                    {"type": "context_compression", "name": "context-compression"},
                    {"type": "guardrail", "name": "moderation"},
                    {"type": "response_healing", "name": "response-healing"},
                ]
            ),
        )
    )

    _finalize(collector, None)

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "provider_guaranteed_zero"
    assert attempt.direct_cost.amount == "0"
    assert attempt.usage.status == "unavailable"
    assert attempt.usage.input.total is None
    assert attempt.usage.output.total is None


@pytest.mark.parametrize(
    ("http_status", "raw_response"),
    [
        pytest.param(200, _insured_error(), id="not-native-429"),
        pytest.param(503, _insured_error(), id="native-503"),
        pytest.param(
            429,
            {"error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}}},
            id="bare-429",
        ),
        pytest.param(429, _insured_error(is_byok=True), id="byok"),
        pytest.param(
            429,
            _insured_error(pipeline=[{"type": "plugin", "name": "web-search"}]),
            id="plugin",
        ),
        pytest.param(
            429,
            _insured_error(pipeline=[{"type": "server_tools", "name": "server-tools"}]),
            id="server-tools",
        ),
        pytest.param(
            429,
            _insured_error(pipeline=[{"type": "future_stage", "name": "unknown"}]),
            id="unknown-stage",
        ),
        pytest.param(
            429,
            _insured_error(error_type="provider_overloaded"),
            id="wrong-error-type",
        ),
        pytest.param(
            429,
            {**_insured_error(), "choices": [{"message": {"content": "partial output"}}]},
            id="generated-output",
        ),
    ],
)
def test_incomplete_or_potentially_billable_rejections_remain_unknown(
    http_status: int, raw_response: dict[str, Any]
) -> None:
    plugin = OpenRouterProviderPlugin()
    evidence = plugin.supplement_chat_usage_accounting(
        evidence=ProviderUsageAccountingEvidence(supported=True),
        raw_response=raw_response,
        http_status=http_status,
        failed=True,
    )

    assert evidence.direct_cost.status == "unavailable"


def test_provider_reported_cost_takes_precedence_over_insurance_inference() -> None:
    plugin = OpenRouterProviderPlugin()
    base = plugin.normalize_chat_usage_accounting(
        request_body={"model": _MODEL},
        raw_response={"usage": {"cost": Decimal("0.4")}},
        final_response=None,
        failed=True,
    )

    evidence = plugin.supplement_chat_usage_accounting(
        evidence=base,
        raw_response=_insured_error(),
        http_status=429,
        failed=True,
    )

    assert evidence.direct_cost.status == "reported"
    assert evidence.direct_cost.amount == "0.4"


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param({"server_tool_use": {"web_search_requests": 1}}, id="server-tool-usage"),
        pytest.param(
            {"cost_details": {"web_search_cost": Decimal("0.25")}},
            id="auxiliary-cost-detail",
        ),
    ],
)
def test_contradictory_auxiliary_usage_prevents_zero_certification(
    usage: dict[str, Any],
) -> None:
    raw_response = {**_insured_error(), "usage": usage}
    collector = _collector((429, raw_response))

    _finalize(collector, None)

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param(
            {
                "server_tool_use_details": {
                    "tool_calls_executed": 1,
                    "tool_calls_requested": 1,
                }
            },
            id="current-chat-server-tool-usage",
        ),
        pytest.param(
            {"server_tool_use_details": []},
            id="malformed-current-chat-server-tool-usage",
        ),
        pytest.param(
            {"server_tool_use_details": {"tool_calls_executed": "1"}},
            id="malformed-current-chat-server-tool-count",
        ),
        pytest.param({"is_byok": True}, id="conflicting-byok"),
        pytest.param({"is_byok": None}, id="malformed-byok"),
        pytest.param({"is_byok": "false"}, id="non-boolean-byok"),
    ],
)
def test_current_chat_usage_conflicts_prevent_zero_certification(
    usage: dict[str, Any],
) -> None:
    raw_response = {**_insured_error(), "usage": usage}
    collector = _collector((429, raw_response))

    _finalize(collector, None)

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "unavailable"


def test_explicit_zero_auxiliary_evidence_preserves_insurance_certification() -> None:
    raw_response = {
        **_insured_error(),
        "usage": {
            "is_byok": False,
            "server_tool_use_details": {
                "tool_calls_executed": 0,
                "tool_calls_requested": 0,
            },
            "cost_details": {"server_tool_cost": Decimal("0")},
        },
    }
    collector = _collector((429, raw_response))

    _finalize(collector, None)

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "provider_guaranteed_zero"


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            {"metadata": {"error_type": "rate_limit_exceeded"}},
            id="missing-error-code",
        ),
        pytest.param(
            {"code": 500, "metadata": {"error_type": "rate_limit_exceeded"}},
            id="conflicting-error-code",
        ),
        pytest.param(
            {"code": "429", "metadata": {"error_type": "rate_limit_exceeded"}},
            id="non-integer-error-code",
        ),
    ],
)
def test_error_code_must_agree_with_native_429(error: dict[str, Any]) -> None:
    raw_response = {**_insured_error(), "error": error}
    collector = _collector((429, raw_response))

    _finalize(collector, None)

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "unavailable"


def test_supplement_failure_preserves_base_mapper_evidence() -> None:
    class _RaisingSupplementPlugin(OpenRouterProviderPlugin):
        def supplement_chat_usage_accounting(
            self, **_kwargs: Any
        ) -> ProviderUsageAccountingEvidence:
            raise RuntimeError("supplement failed")

    successful = {"usage": {"cost": Decimal("0.4")}}
    collector = _collector((200, successful))
    session = AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )

    finalize_provider_evidence(
        session,
        plugin=_RaisingSupplementPlugin(),
        request_body={"model": _MODEL},
        final_response=successful,
    )

    (attempt,) = collector.records()
    assert attempt.direct_cost.status == "reported"
    assert attempt.direct_cost.amount == "0.4"


def test_proven_zero_rejection_plus_reported_retry_is_complete_and_schema_valid() -> None:
    successful = {
        "id": "gen-success",
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "cost": Decimal("0.02"),
        },
    }
    collector = _collector((429, _insured_error()), (200, successful))
    _finalize(collector, successful)

    metadata = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )

    economics = metadata["request_economics"]
    records = collector.records()
    assert [attempt.direct_cost.status for attempt in records] == [
        "provider_guaranteed_zero",
        "reported",
    ]
    assert [
        (attempt.dispatch_index, attempt.attempt_index, attempt.http_status) for attempt in records
    ] == [(1, 1, 429), (2, 1, 200)]
    assert economics["direct_cost_status"] == "complete"
    assert economics["known_direct_cost_subtotals"] == [
        {
            "amount": "0.02",
            "unit": "openrouter_credits",
            "source": "openrouter.usage.cost",
        }
    ]

    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(metadata)


def test_only_proven_zero_attempts_do_not_create_an_empty_zero_subtotal() -> None:
    collector = _collector((429, _insured_error()))
    _finalize(collector, None)

    economics = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )["request_economics"]

    assert economics["direct_cost_status"] == "partial"
    assert economics["known_direct_cost_subtotals"] == []

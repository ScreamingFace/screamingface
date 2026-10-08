"""Adversarial fail-closed regressions for OpenRouter insured zero cost."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import RequestAccountingCollector
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/google/gemini-2.0-flash-001"


def _insured_error(
    *,
    pipeline: object = (),
    router_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    router_metadata: dict[str, Any] = {"attempt": 1, "is_byok": False}
    if pipeline is not ...:
        router_metadata["pipeline"] = list(pipeline) if isinstance(pipeline, tuple) else pipeline
    if router_overrides:
        router_metadata.update(router_overrides)
    return {
        "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
        "openrouter_metadata": router_metadata,
    }


def _record_for(
    raw_response: dict[str, Any],
    *,
    request_body: dict[str, Any] | None = None,
    status: int = 429,
    plugin: object | None = None,
):
    collector = RequestAccountingCollector(
        provider="openrouter",
        requested_model=_MODEL,
        transport="litellm_async_http",
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=status, raw_evidence=raw_response)
    session = AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )
    finalize_provider_evidence(
        session,
        plugin=plugin if plugin is not None else OpenRouterProviderPlugin(),
        request_body=request_body or {"model": _MODEL},
        final_response=None,
    )
    return collector.records()[0]


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param({"model": _MODEL, "plugins": [{"id": "web"}]}, id="provider-plugin"),
        pytest.param(
            {"model": _MODEL, "tools": [{"type": "openrouter:web_search"}]},
            id="server-web-search",
        ),
        pytest.param(
            {"model": _MODEL, "tools": [{"type": "openrouter:web_fetch"}]},
            id="server-web-fetch",
        ),
        pytest.param(
            {
                "model": _MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "summarize"},
                            {
                                "type": "file",
                                "file": {"filename": "report.pdf", "file_data": "data:..."},
                            },
                        ],
                    }
                ],
            },
            id="file-part",
        ),
    ],
)
def test_request_side_auxiliary_charge_risk_prevents_zero_certification(
    request_body: dict[str, Any],
) -> None:
    # INVARIANT: gateway-owned request facts beat an optional, truncated error envelope.
    record = _record_for(_insured_error(), request_body=request_body)

    assert record.direct_cost.status == "unavailable"


def test_ordinary_function_tools_do_not_create_auxiliary_charge_risk() -> None:
    record = _record_for(
        _insured_error(),
        request_body={"model": _MODEL, "tools": [{"type": "function"}]},
    )

    assert record.direct_cost.status == "provider_guaranteed_zero"


def test_gateway_web_search_projection_prevents_zero_certification() -> None:
    prepared = OpenRouterProviderPlugin().prepare_chat_body(
        {
            "model": _MODEL,
            "messages": [{"role": "user", "content": "latest news"}],
            "web_search": True,
        }
    )

    assert prepared["plugins"] == [{"id": "web"}]
    assert _record_for(_insured_error(), request_body=prepared).direct_cost.status == "unavailable"


def test_missing_pipeline_is_not_evidence_that_no_billable_stage_ran() -> None:
    record = _record_for(_insured_error(pipeline=...))

    assert record.direct_cost.status == "unavailable"


def test_malformed_pipeline_is_not_zero_charge_evidence() -> None:
    record = _record_for(_insured_error(pipeline={}))

    assert record.direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    "cost_usd",
    [
        pytest.param(Decimal("0.0021"), id="positive"),
        pytest.param(None, id="null"),
        pytest.param("0", id="string-zero"),
        pytest.param({}, id="mapping"),
        pytest.param(-1, id="negative"),
    ],
)
def test_pipeline_stage_cost_must_be_exact_raw_zero(cost_usd: object) -> None:
    record = _record_for(_insured_error(pipeline=[{"type": "guardrail", "cost_usd": cost_usd}]))

    assert record.direct_cost.status == "unavailable"


def test_pipeline_stage_with_exact_zero_cost_can_be_certified() -> None:
    record = _record_for(_insured_error(pipeline=[{"type": "guardrail", "cost_usd": Decimal("0")}]))

    assert record.direct_cost.status == "provider_guaranteed_zero"


@pytest.mark.parametrize(
    "usage",
    [
        pytest.param({"completion_tokens": 50}, id="completion-tokens"),
        pytest.param({"completion_tokens": "50"}, id="malformed-completion-tokens"),
        pytest.param({"output_tokens": 50}, id="output-tokens-alias"),
        pytest.param(
            {"completion_tokens_details": {"reasoning_tokens": 40}},
            id="reasoning-tokens",
        ),
        pytest.param(
            {"completion_tokens_details": {"reasoning_tokens": "40"}},
            id="malformed-reasoning-tokens",
        ),
        pytest.param({"completion_tokens_details": []}, id="malformed-output-details"),
    ],
)
def test_generated_token_evidence_prevents_zero_certification(usage: object) -> None:
    record = _record_for({**_insured_error(), "usage": usage})

    assert record.direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("upstream_inference_cost", Decimal("0.1"), id="byok-cost"),
        pytest.param("upstream_inference_cost", "garbage", id="malformed-byok-cost"),
        pytest.param("upstream_inference_cost", -1, id="negative-byok-cost"),
        pytest.param("upstream_inference_cost", {}, id="mapping-byok-cost"),
        pytest.param("upstream_inference_prompt_cost", Decimal("0.1"), id="prompt-cost"),
        pytest.param("upstream_inference_completions_cost", Decimal("0.1"), id="completion-cost"),
    ],
)
def test_nonzero_or_malformed_cost_details_prevent_zero_certification(
    name: str, value: object
) -> None:
    record = _record_for({**_insured_error(), "usage": {"cost_details": {name: value}}})

    assert record.direct_cost.status == "unavailable"


def test_nullable_combined_upstream_cost_remains_compatible_with_non_byok() -> None:
    record = _record_for(
        {
            **_insured_error(),
            "usage": {"cost_details": {"upstream_inference_cost": None}},
        }
    )

    assert record.direct_cost.status == "provider_guaranteed_zero"


@pytest.mark.parametrize(
    "attempts",
    [
        pytest.param([{"status": 502}, {"status": 429}], id="mixed-statuses"),
        pytest.param([{"status": "429"}], id="string-status"),
        pytest.param([{}], id="missing-status"),
        pytest.param({}, id="malformed-chain"),
    ],
)
def test_router_attempt_chain_must_contain_only_integer_429(attempts: object) -> None:
    record = _record_for(_insured_error(router_overrides={"attempts": attempts}))

    assert record.direct_cost.status == "unavailable"


def test_all_429_router_attempt_chain_can_be_certified() -> None:
    record = _record_for(
        _insured_error(router_overrides={"attempts": [{"status": 429}, {"status": 429}]})
    )

    assert record.direct_cost.status == "provider_guaranteed_zero"


@pytest.mark.parametrize(
    "is_byok",
    [
        pytest.param(..., id="missing"),
        pytest.param(None, id="null"),
        pytest.param("false", id="string-false"),
    ],
)
def test_router_byok_evidence_must_be_exact_false(is_byok: object) -> None:
    raw_response = _insured_error()
    if is_byok is ...:
        raw_response["openrouter_metadata"].pop("is_byok")
    else:
        raw_response["openrouter_metadata"]["is_byok"] = is_byok

    record = _record_for(raw_response)

    assert record.direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        pytest.param(503, 503, id="native-503-with-matching-code"),
        pytest.param(429, Decimal("429"), id="decimal-code-equal-to-integer"),
    ],
)
def test_native_status_and_integer_error_code_guards_are_independent(
    status: int, error_code: object
) -> None:
    raw_response = _insured_error()
    raw_response["error"]["code"] = error_code

    record = _record_for(raw_response, status=status)

    assert record.direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    "raw_overrides",
    [
        pytest.param({"usage": []}, id="usage-not-mapping"),
        pytest.param({"output": [{"type": "output_text", "text": "partial"}]}, id="output"),
        pytest.param({"content": "partial"}, id="content"),
    ],
)
def test_malformed_usage_or_generated_output_remains_unknown(
    raw_overrides: dict[str, Any],
) -> None:
    record = _record_for({**_insured_error(), **raw_overrides})

    assert record.direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(
            {
                **_insured_error(),
                "error": {"code": 429, "metadata": {"error_type": "provider_overloaded"}},
            },
            id="wrong-error-type",
        ),
        pytest.param(
            {**_insured_error(), "choices": [{"message": {"content": "partial"}}]},
            id="generated-choices",
        ),
        pytest.param(
            _insured_error(pipeline=[{"type": "future_stage"}]),
            id="unknown-pipeline-stage",
        ),
    ],
)
def test_response_guards_are_independently_pinned_on_the_finalizer_path(
    raw_response: dict[str, Any],
) -> None:
    assert _record_for(raw_response).direct_cost.status == "unavailable"


def test_supplement_attribute_lookup_cannot_break_finalization() -> None:
    class _RaisingSupplementLookup(OpenRouterProviderPlugin):
        @property
        def supplement_chat_usage_accounting(self):
            raise RuntimeError("lookup failed")

    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=429, raw_evidence=_insured_error())
    session = AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )

    finalize_provider_evidence(
        session,
        plugin=_RaisingSupplementLookup(),
        request_body={"model": _MODEL},
        final_response=None,
    )

    assert collector.records()[0].direct_cost.status == "unavailable"


def test_wrong_supplement_result_preserves_base_evidence() -> None:
    class _WrongSupplement(OpenRouterProviderPlugin):
        def supplement_chat_usage_accounting(self, **_kwargs: Any) -> object:
            return object()

    record = _record_for(
        {**_insured_error(), "model": "kept-model"},
        plugin=_WrongSupplement(),
    )

    assert record.response_model == "kept-model"
    assert record.direct_cost.status == "unavailable"


def test_certification_preserves_base_mapper_evidence() -> None:
    record = _record_for(
        {
            **_insured_error(),
            "id": "gen-failed",
            "model": "google/gemini-2.0-flash-001",
            "usage": {"prompt_tokens": 7, "completion_tokens": 0},
        }
    )

    assert record.direct_cost.status == "provider_guaranteed_zero"
    assert record.response_model == "google/gemini-2.0-flash-001"
    assert record.provider_response_id == "gen-failed"
    assert record.usage.input.total == 7
    assert record.usage.output.total == 0


@pytest.mark.parametrize(
    "malformation",
    ["nonzero-amount", "missing-amount", "null-unit", "null-source"],
)
def test_schema_rejects_malformed_provider_guaranteed_zero_cost(malformation: str) -> None:
    collector = RequestAccountingCollector(
        provider="openrouter", requested_model=_MODEL, transport="litellm_async_http"
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=429, raw_evidence=_insured_error())
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
        final_response=None,
    )
    metadata = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    malformed = copy.deepcopy(metadata)
    direct_cost = malformed["usage_accounting"]["attempts"][0]["direct_cost"]
    if malformation == "nonzero-amount":
        direct_cost["amount"] = "0.1"
    elif malformation == "missing-amount":
        direct_cost.pop("amount")
    elif malformation == "null-unit":
        direct_cost["unit"] = None
    else:
        direct_cost["source"] = None

    errors = list(Draft202012Validator(schema).iter_errors(malformed))

    assert errors

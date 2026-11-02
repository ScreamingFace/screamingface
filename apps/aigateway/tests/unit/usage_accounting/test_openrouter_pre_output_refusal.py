"""OpenRouter refusal before output is a certified zero (spec 2026-10-26, P1/P2).

FEATURE: cost of intelligence (OME-1287). Anthropic refuses some biology questions before the
model writes output. Through OpenRouter that reply is HTTP 200 with `native_finish_reason:
"refusal"`, no content, no reasoning and no `usage`, and OpenRouter keeps no generation record
for it (live call, 2026-10-26). Nothing is billed, so the gateway certifies the attempt as
`provider_guaranteed_zero` instead of `unavailable`.

STORY: as a reader of the lab_bench board, I see a cost for a run of a model that refused some
questions, instead of "—".

INVARIANT under test: fail closed. Any sign of output, of a usage object, or of a shape this
rule does not know keeps the evidence exactly as the base mapper gave it.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.taxonomy import (
    DirectCost,
    ProviderUsageAccountingEvidence,
    RequestAccountingCollector,
    cache_entry_metadata_from_session,
    cache_reference_from_entry_metadata,
)
from aigateway.plugins.taxonomy.render import render_aigw_metadata
from aigateway.routes.chat_accounting import AccountingSession, finalize_provider_evidence

_MODEL = "openrouter/anthropic/claude-opus-5.5"
_ZERO = {
    "status": "provider_guaranteed_zero",
    "amount": "0",
    "unit": "openrouter_credits",
    "source": "openrouter.pre_output_refusal",
}

# The full body of the live call (LitQA2 row 0, 2026-10-26), as the lossless parser returns it.
_REFUSAL: dict[str, Any] = {
    "id": "gen-1793053597-ybUQmEyCYvKGZ0aEDweM",
    "object": "chat.completion",
    "created": 1793053597,
    "model": "anthropic/claude-opus-5.5",
    "provider": "Claude Platform on AWS",
    "system_fingerprint": None,
    "service_tier": None,
    "choices": [
        {
            "index": 0,
            "logprobs": None,
            "finish_reason": "content_filter",
            "native_finish_reason": "refusal",
            "message": {"role": "assistant", "content": None, "refusal": None, "reasoning": None},
        }
    ],
}


def _refusal(**changes: Any) -> dict[str, Any]:
    body = copy.deepcopy(_REFUSAL)
    body.update(changes)
    return body


def _with_choice(**changes: Any) -> dict[str, Any]:
    body = _refusal()
    body["choices"][0].update(changes)
    return body


def _with_message(**changes: Any) -> dict[str, Any]:
    body = _refusal()
    body["choices"][0]["message"].update(changes)
    return body


def _supplement(
    raw_response: dict[str, Any] | None,
    *,
    http_status: int | None = 200,
    failed: bool = False,
    auxiliary: bool | None = False,
    evidence: ProviderUsageAccountingEvidence | None = None,
) -> ProviderUsageAccountingEvidence:
    return OpenRouterProviderPlugin().supplement_chat_usage_accounting(
        evidence=evidence or ProviderUsageAccountingEvidence(supported=True),
        raw_response=raw_response,
        http_status=http_status,
        failed=failed,
        request_has_potential_auxiliary_charge=auxiliary,
    )


def _collector(status: int, raw_response: dict[str, Any]) -> RequestAccountingCollector:
    collector = RequestAccountingCollector(
        provider="openrouter",
        requested_model=_MODEL,
        transport="litellm_async_http",
    )
    collector.begin_dispatch()
    marker = object()
    collector.on_send_admitted(marker)
    collector.on_response_completed(marker, status=status, raw_evidence=raw_response)
    return collector


def _session(collector: RequestAccountingCollector) -> AccountingSession:
    return AccountingSession(
        provider="openrouter",
        supported=True,
        collector=collector,
        gateway_call_id=collector.gateway_call_id,
        inject_shared_handler=True,
    )


def _finalized(
    raw_response: dict[str, Any],
    *,
    final_response: dict[str, Any] | None = None,
    request_body: dict[str, Any] | None = None,
) -> RequestAccountingCollector:
    collector = _collector(200, raw_response)
    finalize_provider_evidence(
        _session(collector),
        plugin=OpenRouterProviderPlugin(),
        request_body=request_body or {"model": _MODEL},
        final_response=final_response,
    )
    return collector


# ── P1: the live body is certified ─────────────────────────────────────────────────────────────


def test_the_live_pre_output_refusal_is_a_certified_zero() -> None:
    evidence = _supplement(_refusal())

    assert evidence.direct_cost.as_json() == _ZERO


def test_a_finalized_refusal_attempt_is_certified_and_keeps_its_tokens_unknown() -> None:
    (attempt,) = _finalized(_refusal(), final_response=_refusal()).records()

    assert attempt.direct_cost.as_json() == _ZERO
    # P2: the gateway never invents zero tokens for a reply that reported none.
    assert attempt.usage.status == "unavailable"
    assert (attempt.usage.input.total, attempt.usage.output.total) == (None, None)
    assert attempt.provider_response_id == "gen-1793053597-ybUQmEyCYvKGZ0aEDweM"


def test_a_converted_usage_fallback_does_not_block_the_certification() -> None:
    # WHY: LiteLLM may add a usage object to the converted response. That object is not
    # provider money (raw `usage` is absent), so it must not hide the raw refusal.
    converted = _refusal(usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    (attempt,) = _finalized(_refusal(), final_response=converted).records()

    assert attempt.direct_cost.as_json() == _ZERO
    assert attempt.usage.source == "provider_converted_response"


def test_the_rendered_metadata_prices_the_successful_attempt_at_zero_and_is_schema_valid() -> None:
    collector = _finalized(_refusal(), final_response=_refusal())

    metadata = render_aigw_metadata(
        collector=collector,
        supported=True,
        cache_status="miss",
        gateway_call_id=collector.gateway_call_id,
    )

    economics = metadata["request_economics"]
    assert economics["succeeded_attempt_direct_cost"] == _ZERO
    # OME-1446: an all-zero call builds no empty subtotal; the successful-attempt key is the price.
    assert economics["direct_cost_status"] == "partial"
    assert economics["known_direct_cost_subtotals"] == []
    schema = json.loads(
        files("aigateway.plugins.taxonomy")
        .joinpath("usage_accounting.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(metadata)


def test_a_later_cache_hit_on_the_refusal_carries_the_certified_zero() -> None:
    collector = _finalized(_refusal(), final_response=_refusal())

    stored = cache_entry_metadata_from_session(_session(collector))

    assert stored is not None
    assert stored.metadata_status == "complete"
    reference = cache_reference_from_entry_metadata(stored)
    assert reference.direct_cost.as_json() == _ZERO
    assert reference.incurred_in_current_request is False


# ── P1: fail closed ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_response",
    [
        pytest.param(_refusal(usage={"prompt_tokens": 120, "completion_tokens": 0}), id="usage"),
        pytest.param(_with_choice(native_finish_reason="stop"), id="native-not-refusal"),
        pytest.param(_with_choice(native_finish_reason=None), id="native-absent"),
        pytest.param(_with_choice(finish_reason="stop"), id="finish-not-content-filter"),
        pytest.param(_with_message(content="I can't help with that."), id="content"),
        pytest.param(_with_message(reasoning="The user asks about"), id="reasoning"),
        pytest.param(_with_message(tool_calls=[{"id": "t1", "type": "function"}]), id="tool-calls"),
        pytest.param(
            _with_message(reasoning_details=[{"type": "reasoning.text", "text": "x"}]),
            id="reasoning-details",
        ),
        pytest.param(_refusal(choices=[]), id="no-choice"),
        pytest.param(_refusal(choices=_REFUSAL["choices"] * 2), id="two-choices"),
        pytest.param(_refusal(choices="refused"), id="choices-not-list"),
        pytest.param(_refusal(choices=["refused"]), id="choice-not-mapping"),
        pytest.param(_with_choice(message="refused"), id="message-not-mapping"),
        pytest.param(_refusal(error={"code": 400}), id="error"),
    ],
)
def test_a_shape_that_is_not_an_exact_pre_output_refusal_stays_unknown(
    raw_response: dict[str, Any],
) -> None:
    assert _supplement(raw_response).direct_cost.status == "unavailable"


@pytest.mark.parametrize(
    ("http_status", "failed", "auxiliary"),
    [
        pytest.param(429, True, False, id="native-429"),
        pytest.param(200, True, False, id="failed"),
        pytest.param(None, False, False, id="no-status"),
        pytest.param(200, False, True, id="auxiliary-charge"),
        pytest.param(200, False, None, id="auxiliary-unknown"),
    ],
)
def test_a_refusal_body_outside_a_plain_successful_200_stays_unknown(
    http_status: int | None, failed: bool, auxiliary: bool | None
) -> None:
    evidence = _supplement(_refusal(), http_status=http_status, failed=failed, auxiliary=auxiliary)

    assert evidence.direct_cost.status == "unavailable"


def test_no_raw_body_stays_unknown() -> None:
    assert _supplement(None).direct_cost.status == "unavailable"


def test_a_reported_cost_is_never_replaced_by_the_certified_zero() -> None:
    reported = DirectCost.reported(
        amount="0.31", unit="openrouter_credits", source="openrouter.usage.cost"
    )

    evidence = _supplement(
        _refusal(),
        evidence=ProviderUsageAccountingEvidence(supported=True, direct_cost=reported),
    )

    assert evidence.direct_cost == reported


def test_a_mid_stream_refusal_keeps_its_reported_price() -> None:
    # §2.3: a refusal after reasoning is billed, and OpenRouter reports the cost.
    mid_stream = _with_message(reasoning="Looking at the protocol")
    mid_stream["usage"] = {"prompt_tokens": 900, "completion_tokens": 40, "cost": Decimal("0.03")}

    (attempt,) = _finalized(mid_stream, final_response=mid_stream).records()

    assert attempt.direct_cost.status == "reported"
    assert attempt.direct_cost.amount == "0.03"


def test_a_request_with_a_paid_plugin_is_not_certified() -> None:
    (attempt,) = _finalized(
        _refusal(),
        final_response=_refusal(),
        request_body={"model": _MODEL, "plugins": [{"id": "web"}]},
    ).records()

    assert attempt.direct_cost.status == "unavailable"

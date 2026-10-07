"""Pure OpenRouter mapper for the OME-303 accounting contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any

from ..taxonomy import (
    CacheReference,
    DirectCost,
    InputTokenUsage,
    OutputTokenUsage,
    PricingContext,
    ProviderExtension,
    ProviderExtensionFact,
    ProviderUsageAccountingEvidence,
    TokenUsage,
    UsageSource,
    canonical_amount,
)
from ..taxonomy.mapper import (
    bounded_count as _int_or_none,
)
from ..taxonomy.mapper import (
    cache_write_tokens as _cache_write_tokens,
)
from ..taxonomy.mapper import (
    final_detail_or_none as _final_detail_or_none,
)
from ..taxonomy.mapper import (
    mapping_or_none as _mapping,
)
from ..taxonomy.mapper import (
    response_string,
)
from ..taxonomy.mapper import (
    usage_and_source as _usage_and_source,
)
from .zero_insurance import proves_insured_zero

__all__ = [
    "cache_reference_from_cached",
    "normalize_openrouter_usage_accounting",
    "supplement_openrouter_usage_accounting",
]

DIRECT_COST_UNIT = "openrouter_credits"
DIRECT_COST_SOURCE = "openrouter.usage.cost"
EXTENSION_NAMESPACE = "openrouter.response_usage"
ZERO_COMPLETION_INSURANCE_SOURCE = "openrouter.zero_completion_insurance"

# OpenRouter exposes these provider-cost components without a documented currency/unit.
# They remain non-aggregable audit evidence until the provider contract supplies one.
_COST_DETAIL_FIELDS = {
    "upstream_inference_cost": "openrouter.usage.cost_details.upstream_inference_cost",
    "upstream_inference_prompt_cost": (
        "openrouter.usage.cost_details.upstream_inference_prompt_cost"
    ),
    "upstream_inference_completions_cost": (
        "openrouter.usage.cost_details.upstream_inference_completions_cost"
    ),
}


def _uncached_input(
    total: int | None, cache_read: int | None, cache_write: int | None
) -> int | None:
    if total is None or cache_read is None or cache_write is None:
        return None
    uncached = total - cache_read - cache_write
    return uncached if uncached >= 0 else None


def _tokens(usage: Mapping[str, Any], source: UsageSource) -> TokenUsage:
    prompt_details = _mapping(usage.get("prompt_tokens_details")) or {}
    completion_details = _mapping(usage.get("completion_tokens_details")) or {}
    input_total = _final_detail_or_none(usage.get("prompt_tokens"), source)
    output_total = _final_detail_or_none(usage.get("completion_tokens"), source)
    cache_read = _final_detail_or_none(prompt_details.get("cached_tokens"), source)
    cache_write = _cache_write_tokens(prompt_details, source)
    any_known = any(
        value is not None for value in (input_total, output_total, cache_read, cache_write)
    )
    status = "complete" if input_total is not None and output_total is not None else "partial"
    if not any_known:
        status = "unavailable"
    return TokenUsage(
        status=status,
        source=source,
        input=InputTokenUsage(
            total=input_total,
            uncached=_uncached_input(input_total, cache_read, cache_write),
            cache_read=cache_read,
            cache_write=cache_write,
        ),
        output=OutputTokenUsage(
            total=output_total,
            reasoning=_final_detail_or_none(completion_details.get("reasoning_tokens"), source),
        ),
    )


def _exact_raw_amount(value: object) -> str | None:
    """Canonical money only from carriers produced by the lossless raw JSON parser."""
    if type(value) not in (Decimal, int):
        return None
    return canonical_amount(value)


def _direct_cost(usage: Mapping[str, Any], *, usage_source: UsageSource) -> DirectCost:
    if usage.get("cost") is None:
        return DirectCost.unavailable()
    # INVARIANT: LiteLLM's converted monetary float has already lost its raw JSON
    # provenance. Tokens remain useful on that fallback, but money must stay unknown.
    if usage_source != "provider_raw_response":
        return DirectCost.unavailable()
    amount = _exact_raw_amount(usage.get("cost"))
    if amount is None:
        return DirectCost.invalid()
    return DirectCost.reported(
        amount=amount,
        unit=DIRECT_COST_UNIT,
        source=DIRECT_COST_SOURCE,
    )


def _provider_extensions(
    usage: Mapping[str, Any], usage_source: UsageSource
) -> tuple[ProviderExtension, ...]:
    facts: list[ProviderExtensionFact] = []
    cost_details = _mapping(usage.get("cost_details")) or {}
    for name, source in _COST_DETAIL_FIELDS.items():
        if name not in cost_details:
            continue
        amount = (
            _exact_raw_amount(cost_details[name])
            if usage_source == "provider_raw_response"
            else None
        )
        if amount is not None:
            facts.append(
                ProviderExtensionFact(
                    name=name,
                    kind="decimal",
                    value=amount,
                    unit=None,
                    source=source,
                )
            )
    server_tools = _mapping(usage.get("server_tool_use")) or {}
    web_searches = _int_or_none(server_tools.get("web_search_requests"))
    if web_searches is not None:
        facts.append(
            ProviderExtensionFact(
                name="web_search_requests",
                kind="integer",
                value=web_searches,
                unit="requests",
                source="openrouter.usage.server_tool_use.web_search_requests",
            )
        )
    if not facts:
        return ()
    return (ProviderExtension(namespace=EXTENSION_NAMESPACE, facts=tuple(facts[:8])),)


def normalize_openrouter_usage_accounting(
    *,
    request_body: Mapping[str, Any],
    raw_response: Mapping[str, Any] | None,
    final_response: Mapping[str, Any] | None,
    failed: bool = False,
) -> ProviderUsageAccountingEvidence:
    """Normalize one observed OpenRouter attempt without reading request secrets/content."""
    del request_body, failed
    usage, source = _usage_and_source(raw_response, final_response)
    if usage is None:
        return ProviderUsageAccountingEvidence(
            supported=True,
            response_model=response_string(raw_response, final_response, field="model"),
            provider_response_id=response_string(raw_response, final_response, field="id"),
        )
    return ProviderUsageAccountingEvidence(
        supported=True,
        usage=_tokens(usage, source),
        pricing_context=PricingContext(),
        direct_cost=_direct_cost(usage, usage_source=source),
        response_model=response_string(raw_response, final_response, field="model"),
        provider_response_id=response_string(raw_response, final_response, field="id"),
        provider_extensions=_provider_extensions(usage, source),
    )


def supplement_openrouter_usage_accounting(
    *,
    evidence: ProviderUsageAccountingEvidence,
    raw_response: Mapping[str, Any] | None,
    http_status: int | None,
    failed: bool,
    request_has_potential_auxiliary_charge: bool | None = None,
) -> ProviderUsageAccountingEvidence:
    """Certify only a native, metadata-backed OpenRouter insured rejection."""
    if (
        not failed
        or http_status != 429
        or raw_response is None
        or evidence.direct_cost.status != "unavailable"
    ):
        return evidence
    if not proves_insured_zero(
        raw_response,
        http_status=http_status,
        request_has_potential_auxiliary_charge=request_has_potential_auxiliary_charge,
    ):
        return evidence

    return replace(
        evidence,
        direct_cost=DirectCost.provider_guaranteed_zero(
            unit=DIRECT_COST_UNIT,
            source=ZERO_COMPLETION_INSURANCE_SOURCE,
        ),
    )


def cache_reference_from_cached(cached: Mapping[str, Any]) -> CacheReference | None:
    """Historical final-response evidence; never current spend or avoided-cost proof."""
    usage = _mapping(cached.get("usage"))
    if usage is None:
        return None
    tokens = _tokens(usage, "cached_converted_response")
    return CacheReference(usage=tokens, direct_cost=DirectCost.unavailable())

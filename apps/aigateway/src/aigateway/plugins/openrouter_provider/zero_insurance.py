"""Fail-closed proof for OpenRouter Zero Completion Insurance."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from ..taxonomy import canonical_amount

_RESPONSE_FIELDS = frozenset(
    {
        "error",
        "openrouter_metadata",
        "usage",
        "choices",
        "output",
        "content",
        "id",
        "model",
        "object",
        "created",
        "service_tier",
        "system_fingerprint",
    }
)
_USAGE_FIELDS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "output_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
        "is_byok",
        "cost_details",
        "server_tool_use",
        "server_tool_use_details",
    }
)
_PROMPT_DETAIL_FIELDS = frozenset(
    {"audio_tokens", "cache_write_tokens", "cached_tokens", "video_tokens"}
)
_COMPLETION_DETAIL_FIELDS = frozenset(
    {
        "accepted_prediction_tokens",
        "audio_tokens",
        "reasoning_tokens",
        "rejected_prediction_tokens",
    }
)
_COST_DETAIL_FIELDS = frozenset(
    {
        "server_tool_cost",
        "upstream_inference_cost",
        "upstream_inference_input_cost",
        "upstream_inference_output_cost",
        "upstream_inference_prompt_cost",
        "upstream_inference_completions_cost",
    }
)
_ROUTER_FIELDS = frozenset(
    {
        "requested",
        "strategy",
        "region",
        "summary",
        "attempt",
        "is_byok",
        "endpoints",
        "pipeline",
        "attempts",
    }
)
_STAGE_FIELDS = frozenset(
    {"type", "name", "cost_usd", "guardrail_id", "guardrail_scope", "summary"}
)
_ATTEMPT_FIELDS = frozenset({"provider", "model", "status"})
_NONBILLABLE_STAGE_TYPES = frozenset({"context_compression", "guardrail", "response_healing"})


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _exact_amount(value: object) -> str | None:
    return canonical_amount(value) if type(value) in (Decimal, int) else None


def _known_counts(
    value: object,
    *,
    fields: frozenset[str] | None = None,
    require_zero: bool = False,
) -> bool:
    if value is None:
        return True
    counts = _mapping(value)
    if counts is None or (fields is not None and not fields.issuperset(counts)):
        return False
    return all(
        (item is None and not require_zero)
        or (type(item) is int and item >= 0 and (not require_zero or item == 0))
        for item in counts.values()
    )


def _optional_string(value: Mapping[str, Any], field: str, *, nullable: bool = False) -> bool:
    if field not in value:
        return True
    item = value[field]
    return (nullable and item is None) or type(item) is str


def _response_scalars_are_valid(raw_response: Mapping[str, Any]) -> bool:
    strings_valid = all(
        _optional_string(raw_response, field) for field in ("id", "model", "object", "service_tier")
    ) and _optional_string(raw_response, "system_fingerprint", nullable=True)
    created = raw_response.get("created")
    return strings_valid and (
        "created" not in raw_response or (type(created) is int and created >= 0)
    )


def _endpoints_are_valid(value: object) -> bool:
    if value is None:
        return True
    endpoints = _mapping(value)
    if endpoints is None or not {"total", "available"}.issuperset(endpoints):
        return False
    total = endpoints.get("total")
    available = endpoints.get("available")
    if type(total) is not int or total < 0 or not isinstance(available, list):
        return False
    for item_value in available:
        item = _mapping(item_value)
        if item is None or set(item) != {"provider", "model", "selected"}:
            return False
        if type(item["provider"]) is not str or type(item["model"]) is not str:
            return False
        if type(item["selected"]) is not bool:
            return False
    return True


def _usage_proves_no_charge(raw_response: Mapping[str, Any]) -> bool:
    value = raw_response.get("usage")
    if value is None:
        return "usage" not in raw_response or value is None
    usage = _mapping(value)
    if usage is None or not _USAGE_FIELDS.issuperset(usage):
        return False
    input_counts_valid = all(
        field not in usage or (type(usage[field]) is int and usage[field] >= 0)
        for field in ("prompt_tokens", "total_tokens")
    )
    output_counts_zero = all(
        field not in usage or (type(usage[field]) is int and usage[field] == 0)
        for field in ("completion_tokens", "output_tokens")
    )
    known_shapes = (
        ("is_byok" not in usage or usage["is_byok"] is False)
        and _known_counts(usage.get("prompt_tokens_details"), fields=_PROMPT_DETAIL_FIELDS)
        and _known_counts(
            usage.get("completion_tokens_details"),
            fields=_COMPLETION_DETAIL_FIELDS,
            require_zero=True,
        )
        and _known_counts(usage.get("server_tool_use"), require_zero=True)
        and _known_counts(usage.get("server_tool_use_details"), require_zero=True)
    )
    if not input_counts_valid or not output_counts_zero or not known_shapes:
        return False
    details_value = usage.get("cost_details")
    if details_value is None:
        return "cost_details" not in usage
    details = _mapping(details_value)
    if details is None or not _COST_DETAIL_FIELDS.issuperset(details):
        return False
    return all(
        (name == "upstream_inference_cost" and amount is None) or _exact_amount(amount) == "0"
        for name, amount in details.items()
    )


def _pipeline_proves_no_charge(router: Mapping[str, Any]) -> bool:
    pipeline = router.get("pipeline")
    if not isinstance(pipeline, list):
        return False
    for stage_value in pipeline:
        stage = _mapping(stage_value)
        if stage is None or not _STAGE_FIELDS.issuperset(stage):
            return False
        if stage.get("type") not in _NONBILLABLE_STAGE_TYPES:
            return False
        if not all(
            _optional_string(stage, field)
            for field in ("name", "guardrail_id", "guardrail_scope", "summary")
        ):
            return False
        if "cost_usd" in stage and _exact_amount(stage["cost_usd"]) != "0":
            return False
    return True


def _attempts_prove_only_rate_limits(router: Mapping[str, Any]) -> bool:
    if "attempts" not in router:
        return True
    attempts = router.get("attempts")
    if not isinstance(attempts, list):
        return False
    for value in attempts:
        attempt = _mapping(value)
        if attempt is None or not _ATTEMPT_FIELDS.issuperset(attempt):
            return False
        if type(attempt.get("status")) is not int or attempt.get("status") != 429:
            return False
        if not _optional_string(attempt, "provider") or not _optional_string(attempt, "model"):
            return False
    return True


def proves_insured_zero(
    raw_response: Mapping[str, Any],
    *,
    http_status: int | None,
    request_has_potential_auxiliary_charge: bool | None,
) -> bool:
    """Whether every accepted provider and request fact proves covered cost is zero."""
    if (
        http_status != 429
        or request_has_potential_auxiliary_charge is not False
        or not _RESPONSE_FIELDS.issuperset(raw_response)
        or not _response_scalars_are_valid(raw_response)
    ):
        return False
    error = _mapping(raw_response.get("error"))
    metadata = _mapping(error.get("metadata")) if error is not None else None
    router = _mapping(raw_response.get("openrouter_metadata"))
    if (
        error is None
        or not {"code", "message", "metadata"}.issuperset(error)
        or not _optional_string(error, "message")
        or type(error.get("code")) is not int
        or error.get("code") != 429
        or metadata is None
        or set(metadata) != {"error_type"}
        or metadata.get("error_type") != "rate_limit_exceeded"
        or router is None
        or not _ROUTER_FIELDS.issuperset(router)
        or router.get("is_byok") is not False
        or not all(
            _optional_string(router, field)
            for field in ("requested", "strategy", "region", "summary")
        )
        or ("attempt" in router and (type(router["attempt"]) is not int or router["attempt"] < 0))
        or not _endpoints_are_valid(router.get("endpoints"))
    ):
        return False
    if any(
        raw_response.get(field) not in (None, "", [], ())
        for field in ("choices", "output", "content")
    ):
        return False
    return (
        _usage_proves_no_charge(raw_response)
        and _pipeline_proves_no_charge(router)
        and _attempts_prove_only_rate_limits(router)
    )


__all__ = ["proves_insured_zero"]

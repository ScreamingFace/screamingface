"""Strict decoder for retained per-operation accounting."""

from __future__ import annotations

import re
from collections.abc import Mapping

from screamingface._report_primitives import Usage
from screamingface.errors import ExecutionError
from screamingface.operation_accounting import OperationAccounting, OperationCache

_FIXED_POINT_COST = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_ACCOUNTING_KEYS = {
    "provider",
    "request_model",
    "response_model",
    "usage",
    "provider_latency_ms",
    "provider_attempts",
    "cache",
}
_USAGE_KEYS = {
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
    "cost_usd",
}
_CACHE_KEYS = {"hits", "misses", "bypasses", "unknown"}


def decode_operation_accounting(value: object, label: str) -> OperationAccounting | None:
    """Decode a complete accounting value, or preserve its explicit absence.

    INVARIANT: a partial or noncanonical wire value refuses instead of becoming
    a plausible subtotal. This is deliberately stricter than constructing
    ``sf.Usage`` directly because the Engine's versioned JSON contract has one
    canonical fixed-point representation for money.
    """

    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _ACCOUNTING_KEYS, label)
    usage_raw = _mapping(raw.get("usage"), f"{label} usage")
    _exact_keys(usage_raw, _USAGE_KEYS, f"{label} usage")
    cache_raw = _mapping(raw.get("cache"), f"{label} cache")
    _exact_keys(cache_raw, _CACHE_KEYS, f"{label} cache")

    try:
        return OperationAccounting(
            provider=_optional_text(raw.get("provider"), f"{label} provider"),
            request_model=_optional_text(raw.get("request_model"), f"{label} request_model"),
            response_model=_optional_text(raw.get("response_model"), f"{label} response_model"),
            usage=Usage(
                input_tokens=_optional_nonnegative_integer(
                    usage_raw.get("input_tokens"), f"{label} usage input_tokens"
                ),
                output_tokens=_optional_nonnegative_integer(
                    usage_raw.get("output_tokens"), f"{label} usage output_tokens"
                ),
                cache_read_tokens=_optional_nonnegative_integer(
                    usage_raw.get("cache_read_tokens"), f"{label} usage cache_read_tokens"
                ),
                cache_creation_tokens=_optional_nonnegative_integer(
                    usage_raw.get("cache_creation_tokens"),
                    f"{label} usage cache_creation_tokens",
                ),
                reasoning_tokens=_optional_nonnegative_integer(
                    usage_raw.get("reasoning_tokens"), f"{label} usage reasoning_tokens"
                ),
                cost_usd=_optional_fixed_point_cost(
                    usage_raw.get("cost_usd"), f"{label} usage cost_usd"
                ),
            ),
            provider_latency_ms=_optional_nonnegative_integer(
                raw.get("provider_latency_ms"), f"{label} provider_latency_ms"
            ),
            provider_attempts=_optional_nonnegative_integer(
                raw.get("provider_attempts"), f"{label} provider_attempts"
            ),
            cache=OperationCache(
                hits=_nonnegative_integer(cache_raw.get("hits"), f"{label} cache hits"),
                misses=_nonnegative_integer(cache_raw.get("misses"), f"{label} cache misses"),
                bypasses=_nonnegative_integer(cache_raw.get("bypasses"), f"{label} cache bypasses"),
                unknown=_nonnegative_integer(cache_raw.get("unknown"), f"{label} cache unknown"),
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"{label} is invalid: {exc}") from exc


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ExecutionError(f"{label} must be an object with text keys")
    return value


def _exact_keys(value: Mapping[str, object], required: set[str], label: str) -> None:
    present = set(value)
    if missing := sorted(required - present):
        raise ExecutionError(f"{label} is missing {missing[0]!r}")
    if unknown := sorted(present - required):
        raise ExecutionError(f"{label} contains unsupported field {unknown[0]!r}")


def _optional_text(value: object, label: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ExecutionError(f"{label} must be text or null")


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionError(f"{label} must be a non-negative integer")
    return value


def _optional_nonnegative_integer(value: object, label: str) -> int | None:
    return None if value is None else _nonnegative_integer(value, label)


def _optional_fixed_point_cost(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _FIXED_POINT_COST.fullmatch(value) is None:
        raise ExecutionError(f"{label} must be fixed-point decimal text or null")
    return value

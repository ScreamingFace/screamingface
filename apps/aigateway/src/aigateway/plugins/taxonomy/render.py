"""Total, bounded renderer for the OME-303 ``_aigw`` response subtree."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal

from .collector import RequestAccountingCollector
from .money import sum_amounts
from .types import (
    SCHEMA_REQUEST_ECONOMICS,
    SCHEMA_USAGE_ACCOUNTING,
    CacheReference,
    CaptureStatus,
    ProviderAttemptRecord,
)

__all__ = ["METADATA_KEY", "render_aigw_metadata"]

METADATA_KEY = "_aigw"
MAX_RENDERED_ATTEMPTS = 64
MAX_METADATA_BYTES = 64 * 1024
MAX_RESPONSE_EXTENSION_FACTS = 32

CacheStatusWord = Literal["hit", "miss", "bypass"]
DirectCostSummaryStatus = Literal["complete", "partial", "unavailable", "not_applicable"]


def _direct_cost_summary(records: Sequence[ProviderAttemptRecord]) -> list[dict[str, Any]]:
    """Group only aggregable provider-authored amounts by their exact unit and source."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for record in records:
        cost = record.direct_cost
        if cost.status != "reported":
            continue
        assert cost.amount is not None and cost.unit is not None and cost.source is not None
        grouped.setdefault((cost.unit, cost.source), []).append(cost.amount)
    summary: list[dict[str, Any]] = []
    for (unit, source), amounts in sorted(grouped.items()):
        total = sum_amounts(amounts)
        if total is not None:
            summary.append({"amount": total, "unit": unit, "source": source})
    return summary


def _reported_costs_are_summable(records: Sequence[ProviderAttemptRecord]) -> bool:
    grouped: dict[tuple[str, str], list[str]] = {}
    for record in records:
        cost = record.direct_cost
        if cost.status != "reported":
            continue
        assert cost.amount is not None and cost.unit is not None and cost.source is not None
        grouped.setdefault((cost.unit, cost.source), []).append(cost.amount)
    return all(sum_amounts(amounts) is not None for amounts in grouped.values())


def _resolve_capture_status(
    *,
    collector: RequestAccountingCollector | Any | None,
    supported: bool,
    cache_status: CacheStatusWord,
) -> CaptureStatus:
    if not supported:
        return "accounting_not_supported"
    if cache_status == "hit" or collector is None:
        return "not_applicable"
    return collector.status()


def _direct_cost_status(
    records: Sequence[ProviderAttemptRecord],
    *,
    capture_status: CaptureStatus,
    cache_status: CacheStatusWord,
    omitted_attempts: int,
) -> DirectCostSummaryStatus:
    if cache_status == "hit" or not records:
        return "not_applicable"
    reported = sum(record.direct_cost.status == "reported" for record in records)
    if reported == 0:
        return "unavailable"
    if (
        reported == len(records)
        and capture_status == "complete"
        and omitted_attempts == 0
        and _reported_costs_are_summable(records)
    ):
        return "complete"
    return "partial"


def _serialized_size(metadata: dict[str, Any]) -> int:
    return len(json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _degrade_to_bound(metadata: dict[str, Any]) -> None:
    """Deterministically shed optional evidence instead of failing provider success."""
    if _serialized_size(metadata) <= MAX_METADATA_BYTES:
        return
    accounting = metadata["usage_accounting"]
    attempts = accounting["attempts"]
    for attempt in attempts:
        if attempt["provider_extensions"]:
            attempt["provider_extensions"] = []
            attempt["provider_extensions_truncated"] = True
    if _serialized_size(metadata) <= MAX_METADATA_BYTES:
        return
    while attempts and _serialized_size(metadata) > MAX_METADATA_BYTES:
        attempts.pop()
        accounting["rendered_attempts"] -= 1
        accounting["omitted_attempts"] += 1
    accounting["capture_status"] = "partial"
    economics = metadata["request_economics"]
    economics["direct_cost_status"] = "partial"
    economics["known_direct_cost_subtotals"] = []


def _bound_response_extensions(attempts: list[dict[str, Any]]) -> None:
    """Keep audit evidence globally bounded across the complete response."""
    remaining = MAX_RESPONSE_EXTENSION_FACTS
    for attempt in attempts:
        bounded_extensions: list[dict[str, Any]] = []
        for extension in attempt["provider_extensions"]:
            facts = extension["facts"]
            if remaining <= 0:
                attempt["provider_extensions_truncated"] = True
                continue
            if len(facts) > remaining:
                extension["facts"] = facts[:remaining]
                extension["truncated"] = True
                attempt["provider_extensions_truncated"] = True
            remaining -= len(extension["facts"])
            bounded_extensions.append(extension)
        attempt["provider_extensions"] = bounded_extensions


def render_aigw_metadata(
    *,
    collector: RequestAccountingCollector | Any | None,
    supported: bool,
    cache_status: CacheStatusWord,
    gateway_call_id: str,
    trace_id: str | None = None,
    cache_reference: CacheReference | None = None,
) -> dict[str, Any]:
    """Build bounded metadata from authoritative observed attempts."""
    records: tuple[ProviderAttemptRecord, ...] = () if collector is None else collector.records()
    observed_attempts = len(records)
    rendered_records = records[:MAX_RENDERED_ATTEMPTS]
    omitted_attempts = observed_attempts - len(rendered_records)
    capture_status = _resolve_capture_status(
        collector=collector, supported=supported, cache_status=cache_status
    )
    if omitted_attempts and capture_status == "complete":
        capture_status = "partial"
    cost_status = _direct_cost_status(
        records,
        capture_status=capture_status,
        cache_status=cache_status,
        omitted_attempts=omitted_attempts,
    )
    may_summarize = capture_status == "complete" and omitted_attempts == 0
    attempts_json = [record.as_json() for record in rendered_records]
    for attempt in attempts_json:
        attempt["provider_extensions_truncated"] = False
    _bound_response_extensions(attempts_json)
    metadata: dict[str, Any] = {}
    # FEATURE (OME-1120): the caller's trace id, echoed so a JSON caller can quote it.
    # WHY at the `_aigw` TOP level and not inside `usage_accounting`: the trace is not an
    # accounting fact, and `usage_accounting.schema.json` fixes that object's required keys —
    # putting it there would change a published schema for a field that has nothing to do with
    # usage. Streaming callers read the same value from the response header instead.
    if trace_id is not None:
        metadata["trace_id"] = trace_id
    metadata |= {
        "usage_accounting": {
            "schema": SCHEMA_USAGE_ACCOUNTING,
            "capture_status": capture_status,
            "gateway_call_id": gateway_call_id,
            "cache": {
                "status": cache_status,
                "reference": (
                    cache_reference.as_json()
                    if cache_status == "hit" and cache_reference is not None
                    else None
                ),
            },
            "observed_attempts": observed_attempts,
            "rendered_attempts": len(rendered_records),
            "omitted_attempts": omitted_attempts,
            "attempts": attempts_json,
        },
        "request_economics": {
            "schema": SCHEMA_REQUEST_ECONOMICS,
            "observed_new_attempts": observed_attempts,
            "direct_cost_status": cost_status,
            "known_direct_cost_subtotals": (_direct_cost_summary(records) if may_summarize else []),
        },
    }
    _degrade_to_bound(metadata)
    return metadata


def attach_metadata(payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with the gateway-reserved ``_aigw`` response namespace."""
    copied = dict(payload)
    copied[METADATA_KEY] = metadata
    return copied


def merged_error_detail(detail: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep the existing error detail intact and place accounting beside it."""
    return {"detail": detail, METADATA_KEY: metadata}

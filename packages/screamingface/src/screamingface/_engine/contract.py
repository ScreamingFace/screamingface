"""One SF Engine CloudEvent as its public Event (`display_event`), for `on_event` and the
progress output, and a `cost.usage` frame's data as the Report's usage (`usage_value`)."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from screamingface import events
from screamingface.errors import ExecutionError
from screamingface.report import Usage as AccountingUsage

_LOG = logging.getLogger(__name__)


def _sequence(payload: Mapping[str, object]) -> int:
    if payload.get("sequencetype") != "Integer":
        raise ExecutionError("SF Engine CloudEvent sequence must declare Integer semantics")
    value = payload.get("sequence")
    if not isinstance(value, str) or not value.isdigit() or int(value) < 1:
        raise ExecutionError("SF Engine CloudEvent sequence must be a positive integer string")
    return int(value)


def _envelope(
    payload: Mapping[str, object],
    sequence: int,
) -> dict[str, Any]:
    return {
        **_common_envelope(payload),
        "sequence": sequence,
    }


def _common_envelope(payload: Mapping[str, object]) -> dict[str, Any]:
    return {
        "id": _text(payload, "id"),
        "run_id": _text(payload, "subject"),
        "timestamp": _timestamp(payload.get("time")),
        "source": _text(payload, "source"),
        "traceparent": _optional_text(payload.get("traceparent"), "traceparent"),
        "tracestate": _optional_text(payload.get("tracestate"), "tracestate"),
    }


def _log(envelope: dict[str, Any], data: Mapping[str, object]) -> events.Log:
    severity = _severity(_text(data, "severity_text"))
    number = _integer(data.get("severity_number"), "log severity_number")
    attributes = _log_attributes(data.get("attributes", {}))
    return events.Log(
        **envelope,
        severity_number=number,
        severity_text=severity,
        body=_raw_text(data, "body"),
        attributes=attributes,
    )


def _span(envelope: dict[str, Any], data: Mapping[str, object]) -> events.Span:
    name = _text(data, "name")
    start = _timestamp(data.get("start"))
    end = _optional_timestamp(data.get("end"))
    # WHY clamp here rather than let `events.Span` refuse it: an Engine that read the wall clock at
    # both ends of a span published `end` before `start` whenever the host stepped its clock back
    # between them (lima-guestagent's `SyncTime`, about 211 ms), and that bare `ValueError`
    # aborted a run the Engine reported as succeeded. Same rule as the cost total-vs-parts case:
    # incoherent producer telemetry is resolved with a warning, never fatal.
    # INVARIANT: clamp, never drop. The span still feeds `_hit_spans` and the saved-cost totals,
    # so dropping it would under-count the run's hits and savings; `end=None` would falsely claim
    # the span never finished. The public `events.Span` keeps rejecting `end < start`.
    if end is not None and end < start:
        _LOG.warning(
            "SF Engine span %r ends before it starts; clamping end to start (start=%s, end=%s)",
            name,
            start,
            end,
        )
        end = start
    return events.Span(
        **envelope,
        name=name,
        operation=_text(data, "gen_ai.operation.name"),
        start=start,
        end=end,
        status=_span_status(_text(data, "status")),
        span_kind=_span_kind(_text(data, "kind")),
        provider=_optional_text(data.get("gen_ai.provider.name"), "span provider"),
        request_model=_optional_text(
            data.get("gen_ai.request.model"),
            "span request model",
        ),
        response_model=_optional_text(
            data.get("gen_ai.response.model"),
            "span response model",
        ),
        input_tokens=_optional_integer(
            data.get("gen_ai.usage.input_tokens"),
            "span input tokens",
        ),
        output_tokens=_optional_integer(
            data.get("gen_ai.usage.output_tokens"),
            "span output tokens",
        ),
        finish_reasons=_optional_text_tuple(
            data.get("gen_ai.response.finish_reasons"),
            "span finish reasons",
        ),
        refusal=_optional_text(data.get("refusal"), "span refusal"),
        cache_status=_cache_status(data.get("cache_status")),
        cache_reason=_optional_text(data.get("cache_reason"), "span cache_reason"),
        # OME-1252: the counterfactual this span's hits avoided, one field per provenance.
        # Absent is not zero — `None` means nothing priceable was saved, which is a different
        # claim from "saved nothing".
        cache_saved_cost_usd=_optional_saved_cost(
            data.get("cache_saved_cost_usd"), "span cache_saved_cost_usd"
        ),
        cache_saved_cost_archive_usd=_optional_saved_cost(
            data.get("cache_saved_cost_archive_usd"), "span cache_saved_cost_archive_usd"
        ),
    )


def _optional_saved_cost(value: object, label: str) -> Decimal | None:
    """A counterfactual amount, or None when the producer reported none.

    INVARIANT: absent stays absent. Defaulting to `Decimal(0)` would turn "nothing priceable was
    saved" into "a hit worth nothing", and the run-level derivation reads exactly that difference
    to tell `partial` from `unavailable`.
    """
    if value is None:
        return None
    return _decimal(value, label)


def _usage(envelope: dict[str, Any], data: Mapping[str, object]) -> events.Usage:
    return events.Usage(
        **envelope,
        scope=_usage_scope(_text(data, "scope")),
        provider=_text(data, "gen_ai.provider.name"),
        model=_text(data, "gen_ai.response.model"),
        pricing_version=_text(data, "pricing_version"),
        usage=usage_value(data),
    )


def usage_value(data: Mapping[str, object]) -> AccountingUsage:
    """A `cost.usage` frame's `data` as the Report's usage; the Engine's record carries the
    run's root subtree frame's `data` as it is (E5 P2 spec §4.3)."""
    usage = _object(data.get("usage"), "cost usage tokens")
    cost = _object(data.get("cost"), "cost usage cost")
    pricing_version = _text(data, "pricing_version")
    total = _decimal(cost.get("total_usd"), "cost total_usd")
    parts = sum(
        (
            _decimal(cost.get(name, 0), f"cost {name}")
            for name in (
                "input_usd",
                "output_usd",
                "cache_read_usd",
                "cache_creation_usd",
                "reasoning_usd",
            )
        ),
        Decimal(),
    )
    # WHY guarded on `parts` (OME-861): a provider may author ONE amount with no per-class split —
    # OpenRouter reports exactly that — so the Engine legitimately publishes a total with every
    # component at zero (`url4.streaming`'s CostBreakdown accepts Σ components <= total_usd since
    # OME-850). A bare `total != parts` therefore fired on EVERY priced run, which is noise a reader
    # cannot act on, in a library people run in notebooks.
    # INVARIANT: an ABSENT breakdown is silence, not disagreement. A breakdown that WAS supplied and
    # still disagrees is incoherent and keeps its warning — the guard narrows the condition, it does
    # not remove it. Either way `total_usd` wins, because it is the authoritative field.
    # AIDEV-NOTE: residual — a genuinely PARTIAL breakdown (some classes known, summing below the
    # total) still warns. No producer sends one today; revisit if that changes.
    if parts and total != parts:
        _LOG.warning(
            "SF Engine cost total_usd does not equal its parts; using total_usd "
            "(total=%s, parts=%s)",
            total,
            parts,
        )
    unpriced = pricing_version == "unpriced"
    accounting = AccountingUsage(
        input_tokens=_integer(usage.get("gen_ai.usage.input_tokens", 0), "input tokens"),
        output_tokens=_integer(usage.get("gen_ai.usage.output_tokens", 0), "output tokens"),
        cache_read_tokens=(
            None
            if unpriced
            else _integer(
                usage.get("gen_ai.usage.cache_read_tokens", 0),
                "cache read tokens",
            )
        ),
        cache_creation_tokens=(
            None
            if unpriced
            else _integer(
                usage.get("gen_ai.usage.cache_creation_tokens", 0),
                "cache creation tokens",
            )
        ),
        reasoning_tokens=(
            None
            if unpriced
            else _integer(
                usage.get("gen_ai.usage.reasoning_tokens", 0),
                "reasoning tokens",
            )
        ),
        cost_usd=None if unpriced else total,
    )
    return accounting


def _termination_error(value: object) -> events.TerminationError | None:
    if value is None:
        return None
    data = _object(value, "termination error")
    permanent = data.get("permanent", False)
    if not isinstance(permanent, bool):
        raise ExecutionError("SF Engine termination error permanent must be boolean")
    return events.TerminationError(
        code=_text(data, "code"),
        message=_raw_text(data, "message"),
        permanent=permanent,
    )


def _severity(value: str) -> events.Severity:
    if value not in {"DEBUG", "INFO", "WARN", "ERROR"}:
        raise ExecutionError("SF Engine log severity_text is invalid")
    return cast(events.Severity, value)


def _span_status(value: str) -> events.SpanStatus:
    if value == "ok":
        return "ok"
    if value == "error":
        return "error"
    raise ExecutionError("SF Engine span status is invalid")


def _span_kind(value: str) -> events.SpanKind:
    if value == "client":
        return "client"
    if value == "internal":
        return "internal"
    if value == "server":
        return "server"
    raise ExecutionError("SF Engine span kind is invalid")


def _cache_status(value: object) -> events.CacheStatus | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {"hit", "miss", "bypass"}:
        raise ExecutionError("SF Engine span cache_status is invalid")
    return cast(events.CacheStatus, value)


def _usage_scope(value: str) -> events.UsageScope:
    if value == "self":
        return "self"
    if value == "subtree":
        return "subtree"
    raise ExecutionError("SF Engine usage scope is invalid")


def _termination_status(value: str) -> events.TerminationStatus:
    if value not in {"succeeded", "failed", "stopped", "timed_out"}:
        raise ExecutionError("SF Engine termination status is invalid")
    return cast(events.TerminationStatus, value)


def _log_attributes(
    value: object,
) -> dict[str, str | int | float | bool | None]:
    attributes = _object(value, "log attributes")
    selected: dict[str, str | int | float | bool | None] = {}
    for name, item in attributes.items():
        if item is not None and not isinstance(item, str | int | float | bool):
            raise ExecutionError("SF Engine log attributes contain a non-scalar value")
        selected[name] = item
    return selected


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ExecutionError(f"SF Engine {label} must be a JSON object")
    return value


def _text(value: Mapping[str, object], name: str) -> str:
    return _required_text(value.get(name), name)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionError(f"SF Engine {label} must be a non-empty string")
    return value.strip()


def _raw_text(value: Mapping[str, object], name: str) -> str:
    selected = value.get(name)
    if not isinstance(selected, str):
        raise ExecutionError(f"SF Engine {name} must be a string")
    return selected


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, label)


def _optional_text_tuple(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ExecutionError(f"SF Engine {label} must be an array of non-empty strings")
    return tuple(_required_text(item, label) for item in value)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionError(f"SF Engine {label} must be a non-negative integer")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ExecutionError("SF Engine CloudEvent time must be an RFC 3339 string")
    try:
        selected = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionError("SF Engine CloudEvent time must be an RFC 3339 string") from exc
    if selected.tzinfo is None:
        raise ExecutionError("SF Engine CloudEvent time must include a timezone")
    return selected


def _optional_timestamp(value: object) -> datetime | None:
    return None if value is None else _timestamp(value)


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ExecutionError(f"SF Engine {label} must be a decimal")
    try:
        selected = Decimal(str(value))
    except InvalidOperation as exc:
        raise ExecutionError(f"SF Engine {label} must be a decimal") from exc
    if not selected.is_finite() or selected < 0 or math.isnan(float(selected)):
        raise ExecutionError(f"SF Engine {label} must be a finite non-negative decimal")
    return selected


__all__: list[str] = []


def display_event(payload: Mapping[str, object]) -> events.Event | None:
    """One CloudEvent of a Run's event stream as the public Event, for `on_event` and the
    progress output only (E5 P2 spec §4.2, D13): the Candidate's outcome comes from the
    Engine's record, never from these.

    None for a frame that is not a public Event (a result frame, an unsequenced notice, a kind
    this Client does not know). Raises ExecutionError for a frame that does not decode.
    """
    event_type = _text(payload, "type")
    decode = _DISPLAYED.get(event_type)
    if decode is None or payload.get("sequence") is None:
        return None
    envelope = _envelope(payload, _sequence(payload))
    return decode(envelope, _object(payload.get("data"), f"{event_type} data"))


def _started_event(envelope: dict[str, Any], data: Mapping[str, object]) -> events.Started:
    return events.Started(**envelope, url4=_text(data, "url4"))


def _terminated_event(envelope: dict[str, Any], data: Mapping[str, object]) -> events.Terminated:
    status = _text(data, "status")
    if status not in {"succeeded", "failed", "stopped", "timed_out"}:
        raise ExecutionError("SF Engine termination status is invalid")
    return events.Terminated(
        **envelope, status=_termination_status(status), error=_termination_error(data.get("error"))
    )


type _Decode = Callable[[dict[str, Any], Mapping[str, object]], events.Event | None]

_DISPLAYED: dict[str, _Decode] = {
    "ai.url4.started": _started_event,
    "ai.url4.log": _log,
    "ai.url4.span": _span,
    "ai.url4.cost.usage": _usage,
    "ai.url4.terminated": _terminated_event,
}

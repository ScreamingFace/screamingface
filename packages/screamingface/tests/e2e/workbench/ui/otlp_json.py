"""A bundle's spans as OTLP/JSON, for the Trace view's download (spec §3.8 item 6; u8 Task 4).

``to_otlp_json(spans)`` turns the rows of ``spans.jsonl`` (the receiver's flat shape, see
``workbench.otlp_receiver``) back into an OTLP ``TracesData`` JSON document: one
``resourceSpans`` entry per service (``service.name`` as the resource attribute), one
``scopeSpans`` under it, and the spans in file order. Pure: no I/O.

The encoding follows the OTLP/JSON rules, not plain proto3 JSON: trace and span ids are
lowercase hex (proto3 JSON would use base64), enums are integers, 64-bit integers
(``startTimeUnixNano``, ``intValue``) are decimal strings, and attributes are typed
``AnyValue``s (``stringValue``, ``boolValue``, ``intValue``, ``doubleValue``, ``arrayValue``,
``kvlistValue``; ``null`` is the empty ``AnyValue``).

WHY one fixed scope: ``spans.jsonl`` does not keep the instrumentation scope the services
exported under, so every span goes under ``SCOPE_NAME`` rather than an invented original.

WHY the derived client span is left out: it is the view's inference from SDK events
(``trace_story.DERIVED_ATTR``), not a span any service exported; an export must carry only
what was received.

INVARIANTS (the rows are untrusted bundle content):
- a span without a valid trace id (32 hex) or span id (16 hex, not all zero) is skipped; an
  invalid parent id is dropped, so the span becomes a root rather than pointing at a guess;
- a time that is not a uint64 is omitted (read as 0), never coerced;
- an integer outside int64 is kept as its decimal text, a non-finite double as the proto3
  JSON strings ``"NaN"`` / ``"Infinity"`` / ``"-Infinity"``, so the document is strict JSON;
- nesting deeper than ``MAX_DEPTH`` is cut to a ``stringValue`` marker: no recursion over
  untrusted depth.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from workbench.ui.trace_story import DERIVED_ATTR

SCOPE_NAME: Final = "screamingface.e2e.workbench"
MAX_DEPTH: Final = 16
TOO_DEEP: Final = "<nested too deep>"
_TRACE_ID: Final = re.compile(r"[0-9a-fA-F]{32}")
_SPAN_ID: Final = re.compile(r"[0-9a-fA-F]{16}")
_UINT64: Final = 1 << 64
_INT64: Final = 1 << 63
# OTLP SpanKind and StatusCode numbers; anything else is UNSPECIFIED / UNSET (0).
_KINDS: Final = {"internal": 1, "server": 2, "client": 3, "producer": 4, "consumer": 5}
_STATUS: Final = {"ok": 1, "error": 2}

type Json = dict[str, Any]


def _id(value: object, pattern: re.Pattern[str]) -> str | None:
    if not isinstance(value, str) or not pattern.fullmatch(value) or not value.strip("0"):
        return None
    return value.lower()


def _nanos(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < _UINT64:
        return None
    return str(value)


def _double(value: float) -> float | str:
    if math.isfinite(value):
        return value
    return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"


def _int(value: int) -> Json:
    return {"intValue": str(value)} if -_INT64 <= value < _INT64 else {"stringValue": str(value)}


# By exact JSON type (``bool`` is not ``int`` here); anything else is its text.
_ENCODE: Final[dict[type, Callable[[Any, int], Json]]] = {
    type(None): lambda _v, _d: {},
    bool: lambda v, _d: {"boolValue": v},
    int: lambda v, _d: _int(v),
    float: lambda v, _d: {"doubleValue": _double(v)},
    str: lambda v, _d: {"stringValue": v},
    list: lambda v, d: {"arrayValue": {"values": [_any_value(x, d + 1) for x in v]}},
    dict: lambda v, d: {"kvlistValue": {"values": _key_values(v, d + 1)}},
}


def _any_value(value: object, depth: int = 0) -> Json:
    """``value`` as a typed OTLP ``AnyValue``."""
    if depth >= MAX_DEPTH:
        return {"stringValue": TOO_DEEP}
    encode = _ENCODE.get(type(value))
    return encode(value, depth) if encode is not None else {"stringValue": str(value)}


def _key_values(pairs: Mapping[object, object], depth: int = 0) -> list[Json]:
    return [{"key": str(k), "value": _any_value(v, depth)} for k, v in pairs.items()]


def _dict(value: object) -> dict[object, object]:
    return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def _span(row: Mapping[str, Any], trace_id: str, span_id: str) -> Json:
    status = _dict(row.get("status"))
    code, message = status.get("code"), status.get("message")
    out: Json = {"traceId": trace_id, "spanId": span_id}
    if (parent := _id(row.get("parent_span_id"), _SPAN_ID)) is not None:
        out["parentSpanId"] = parent
    name, kind = row.get("name"), row.get("kind")
    out["name"] = name if isinstance(name, str) else ""
    out["kind"] = _KINDS.get(kind, 0) if isinstance(kind, str) else 0
    for field, key in (("startTimeUnixNano", "start_ns"), ("endTimeUnixNano", "end_ns")):
        if (nanos := _nanos(row.get(key))) is not None:
            out[field] = nanos
    out["attributes"] = _key_values(_dict(row.get("attributes")))
    out["status"] = {
        "code": _STATUS.get(code, 0) if isinstance(code, str) else 0,
        "message": message if isinstance(message, str) else "",
    }
    return out


def _derived(row: Mapping[str, Any]) -> bool:
    return DERIVED_ATTR in _dict(row.get("attributes"))


def to_otlp_json(spans: Iterable[Mapping[str, Any]]) -> Json:
    """``spans`` (``spans.jsonl`` rows) as an OTLP/JSON ``TracesData`` document, by service."""
    by_service: dict[str | None, list[Json]] = {}
    for row in spans:
        trace_id, span_id = _id(row.get("trace_id"), _TRACE_ID), _id(row.get("span_id"), _SPAN_ID)
        if trace_id is None or span_id is None or _derived(row):
            continue
        service = row.get("service")
        key = service if isinstance(service, str) else None
        by_service.setdefault(key, []).append(_span(row, trace_id, span_id))
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [] if service is None else _key_values({"service.name": service})
                },
                "scopeSpans": [{"scope": {"name": SCOPE_NAME}, "spans": rows}],
            }
            for service, rows in by_service.items()
        ]
    }

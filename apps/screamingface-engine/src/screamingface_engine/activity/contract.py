"""Safe v1 activity vocabulary and explicit producer facts (OME-1161)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

Scalar = str | int | float | bool | None
PREFIX = "sf.activity."
SCHEMA = "screamingface.activity.v1"
MAX_INTEGER = 9_007_199_254_740_991


class ActivityLevel(StrEnum):
    OFF = "off"
    FULL = "full"


class ActivityKind(StrEnum):
    CASE_LOADING = "case_loading"
    ANSWERING = "answering"
    MODEL_CALL = "model_call"
    GRADING_PREPARE = "grading_prepare"
    GRADING_CHECK = "grading_check"
    GRADING_REDUCE = "grading_reduce"
    AGGREGATION = "aggregation"


class Emitter(Protocol):
    def __call__(
        self, body: str, attributes: Mapping[str, Scalar] | None = None, *, severity: str = "INFO"
    ) -> None: ...


TERMINAL = frozenset({"completed", "failed", "cancelled", "refused"})
_STATES = TERMINAL | {"started", "running", "retrying"}
_FINISH = frozenset({"stop", "length", "tool_calls", "function_call", "content_filter"})
_FAILURE = frozenset(
    {
        "internal_error",
        "provider_refusal",
        "aigateway_transport_error",
        "aigateway_bad_response",
        "aigateway_empty_response",
        "model_token_cap",
        "model_empty_content",
        "provider_timeout",
        "provider_rate_limit",
        "provider_error",
    }
)
_IDENTIFIERS = frozenset({"model_id", "provider", "benchmark_id", "case_id"})
_COUNTS = frozenset({"loaded_count", "selected_count", "result_count", "prepared_task_count"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}\Z")


def validate_state(kind: ActivityKind, state: str) -> None:
    if state not in _STATES:
        raise ValueError("unknown activity state")
    if state == "retrying" and kind != ActivityKind.MODEL_CALL:
        raise ValueError("retry is a model-call observation")
    if state == "refused" and kind not in {ActivityKind.MODEL_CALL, ActivityKind.ANSWERING}:
        raise ValueError("refusal is an answer/model observation")


def _identifier(value: object) -> str | int:
    # INVARIANT: callers supply catalog/public IDs, never arbitrary user labels. Lexical
    # validation rejects obvious paths/URLs; it cannot establish provenance by itself.
    if type(value) is int and 0 <= value <= MAX_INTEGER:
        return value
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("invalid public activity identifier")
    if "://" in value or ".." in value or value.startswith(("/", "~")):
        raise ValueError("unsafe activity identifier")
    return value


def _number(value: object, *, integer: bool = False, minimum: int = 0) -> int | float:
    if type(value) not in {int, float}:
        raise ValueError("activity number required")
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite activity number required")
    if value < minimum or value > MAX_INTEGER or (integer and type(value) is not int):
        raise ValueError("invalid activity number")
    return value


def safe_fact(name: str, value: object) -> Scalar:
    result: Scalar
    if name in _IDENTIFIERS:
        result = _identifier(value)
        if name != "case_id" and not isinstance(result, str):
            raise ValueError("text identifier required")
    elif name in _COUNTS or name == "attempt":
        result = _number(value, integer=True, minimum=1 if name == "attempt" else 0)
    elif name == "retry_delay_ms":
        result = _number(value)
    elif name == "finish_reason":
        result = value if isinstance(value, str) and value in _FINISH else None
    elif name == "failure_code":
        result = value if isinstance(value, str) and value in _FAILURE else "internal_error"
    else:
        raise ValueError("unknown activity fact")
    return result


def facts(values: Mapping[str, object]) -> dict[str, Scalar]:
    result: dict[str, Scalar] = {}
    for name, value in values.items():
        if value is not None:
            safe = safe_fact(name, value)
            if safe is not None:
                result[PREFIX + name] = safe
    return result


def message(kind: ActivityKind, state: str) -> str:
    return f"{kind.value.replace('_', ' ').capitalize()} {state}"

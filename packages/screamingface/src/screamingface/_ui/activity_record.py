"""Independent safe decoding of optional Engine activity (OME-1135)."""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from screamingface.events import Log

PREFIX = "sf.activity."
MAX_INTEGER = 9_007_199_254_740_991
LABELS = {
    "case_loading": "Loading cases",
    "answering": "Answering",
    "grading": "Grading",
    "aggregation": "Aggregating",
    "model_call": "Model call",
}
TERMINAL = {"completed", "failed", "cancelled", "refused"}
STATES = TERMINAL | {"started", "running", "retrying"}
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,127}\Z")
_COUNTS = {"attempt", "loaded_count", "selected_count", "result_count", "prepared_task_count"}
_FINISH = {"stop", "length", "tool_calls", "function_call", "content_filter"}
_FAILURE = {
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


def number(value: object, *, integer: bool = True) -> int | float:
    if type(value) not in ({int} if integer else {int, float}):
        raise ValueError("invalid activity number")
    assert isinstance(value, (int, float))
    if not math.isfinite(value) or not 0 <= value <= MAX_INTEGER:
        raise ValueError("invalid activity number")
    return value


def identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not _IDENT.fullmatch(value)
        or "://" in value
        or ".." in value
        or value.startswith(("/", "~"))
    ):
        raise ValueError("invalid activity identifier")
    return value


@dataclass(frozen=True)
class ActivityRecord:
    id: str
    revision: int
    kind: str
    state: str
    elapsed_ms: float
    observed_at_ms: int
    facts: tuple[tuple[str, str | int | float], ...]
    size: int


def decode(event: Log) -> ActivityRecord:
    # INVARIANT: raw prose and unknown fields never enter the safe projection.
    values = {k[len(PREFIX) :]: v for k, v in event.attributes.items() if k.startswith(PREFIX)}
    if (
        len(event.body) > 256
        or len(json.dumps({"body": event.body, "attributes": dict(event.attributes)}).encode())
        > 4096
    ):
        raise ValueError("oversize activity")
    kind, state = values.get("kind"), values.get("state")
    if kind not in LABELS or state not in STATES:
        raise ValueError("unknown activity kind/state")
    if state == "retrying" and kind != "model_call":
        raise ValueError("retry belongs to model call")
    if state == "refused" and kind not in {"answering", "model_call"}:
        raise ValueError("refusal belongs to answering/model call")
    revision = int(number(values.get("revision")))
    if not revision:
        raise ValueError("revision starts at one")
    assert isinstance(kind, str) and isinstance(state, str)
    return ActivityRecord(
        identifier(values.get("id")),
        revision,
        kind,
        state,
        float(number(values.get("elapsed_ms"), integer=False)),
        int(number(values.get("observed_at_ms"))),
        tuple(sorted(_facts(values).items())),
        len(json.dumps(values).encode()),
    )


def _facts(values: Mapping[str, object]) -> dict[str, str | int | float]:
    safe: dict[str, str | int | float] = {}
    for name, value in values.items():
        if value is not None:
            result = _fact(name, value)
            if result is not None:
                safe[name] = result
    return safe


def _fact(name: str, value: object) -> str | int | float | None:
    if name in {"parent_id", "provider", "model_id", "benchmark_id", "case_id"}:
        return int(number(value)) if name == "case_id" and type(value) is int else identifier(value)
    if name in _COUNTS | {"retry_delay_ms"}:
        result = number(value, integer=name != "retry_delay_ms")
        if name == "attempt" and result == 0:
            raise ValueError("attempt starts at one")
        return result
    allowed = {"finish_reason": _FINISH, "failure_code": _FAILURE}.get(name)
    if allowed is not None and (not isinstance(value, str) or value not in allowed):
        raise ValueError("unknown activity category")
    return value if allowed is not None and isinstance(value, str) else None

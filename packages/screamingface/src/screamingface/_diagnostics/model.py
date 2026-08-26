"""Construction boundary for immutable local diagnostic receipts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType

from screamingface.diagnostic import DiagnosticReceipt


def _new_receipt(
    *,
    diagnostic_id: str,
    session_id: str,
    occurred_at: datetime,
    elapsed_seconds: float,
    operation: str,
    outcome: str,
    client: Mapping[str, object],
    error: Mapping[str, object],
    context: Mapping[str, object],
    executions: Sequence[Mapping[str, object]],
    breadcrumbs: Sequence[Mapping[str, object]],
) -> DiagnosticReceipt:
    """Validate and freeze one receipt assembled by the private capture layer."""

    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise ValueError("Diagnostic occurred_at must be timezone-aware")
    document: dict[str, object] = {
        "schema": "screamingface.diagnostic/v1",
        "diagnostic_id": _nonblank(diagnostic_id, "Diagnostic id"),
        "session_id": _nonblank(session_id, "Diagnostic session id"),
        "occurred_at": _timestamp_text(occurred_at),
        "elapsed_seconds": elapsed_seconds,
        "operation": _nonblank(operation, "Diagnostic operation"),
        "outcome": _nonblank(outcome, "Diagnostic outcome"),
        "client": dict(client),
        "error": dict(error),
        "context": dict(context),
        "executions": [dict(value) for value in executions],
        "breadcrumbs": [dict(value) for value in breadcrumbs],
    }
    frozen = _freeze(document)
    if not isinstance(frozen, Mapping):
        raise AssertionError("a diagnostic document must remain a mapping")
    return DiagnosticReceipt._from_frozen(frozen)


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        frozen: object = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Diagnostic numbers must be finite")
        frozen = value
    elif isinstance(value, Mapping):
        frozen = _freeze_mapping(value)
    elif isinstance(value, (list, tuple)):
        frozen = tuple(_freeze(item) for item in value)
    else:
        raise TypeError(f"Diagnostic values cannot contain {type(value).__name__}")
    return frozen


def _freeze_mapping(value: Mapping[object, object]) -> Mapping[str, object]:
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("Diagnostic object keys must be strings")
        frozen[key] = _freeze(item)
    return MappingProxyType(frozen)


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _timestamp_text(value: datetime) -> str:
    rendered = value.astimezone(UTC).isoformat(timespec="milliseconds")
    return rendered.replace("+00:00", "Z")


__all__ = ["_new_receipt"]

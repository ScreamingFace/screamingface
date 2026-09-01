"""Construction boundary for immutable local diagnostic receipts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from screamingface.diagnostic import DiagnosticReceipt

_SAFE_ERROR_FIELDS = frozenset(
    {"type", "code", "status", "permanent", "retryable", "hint", "details", "chain"}
)


@dataclass(frozen=True, slots=True)
class _ReceiptEvidence:
    """Typed evidence assembled for one immutable diagnostic receipt."""

    diagnostic_id: str
    session_id: str
    occurred_at: datetime
    elapsed_seconds: float
    operation: str
    outcome: str
    client: Mapping[str, object]
    error: Mapping[str, object]
    context: Mapping[str, object]
    executions: Sequence[Mapping[str, object]] = ()
    breadcrumbs: Sequence[Mapping[str, object]] = ()


def _new_receipt(evidence: _ReceiptEvidence) -> DiagnosticReceipt:
    """Validate and freeze one receipt assembled by the private capture layer."""

    if not isinstance(evidence.occurred_at, datetime) or evidence.occurred_at.tzinfo is None:
        raise ValueError("Diagnostic occurred_at must be timezone-aware")
    _validate_error(evidence.error)
    document: dict[str, object] = {
        "schema": "screamingface.diagnostic/v1",
        "diagnostic_id": _nonblank(evidence.diagnostic_id, "Diagnostic id"),
        "session_id": _nonblank(evidence.session_id, "Diagnostic session id"),
        "occurred_at": _timestamp_text(evidence.occurred_at),
        "elapsed_seconds": evidence.elapsed_seconds,
        "operation": _nonblank(evidence.operation, "Diagnostic operation"),
        "outcome": _nonblank(evidence.outcome, "Diagnostic outcome"),
        "client": dict(evidence.client),
        "error": dict(evidence.error),
        "context": dict(evidence.context),
        "executions": [dict(value) for value in evidence.executions],
        "breadcrumbs": [dict(value) for value in evidence.breadcrumbs],
    }
    frozen = _freeze(document)
    if not isinstance(frozen, Mapping):
        raise AssertionError("a diagnostic document must remain a mapping")
    return DiagnosticReceipt._from_frozen(frozen)


def _validate_error(value: Mapping[str, object]) -> None:
    # INVARIANT: generic receipt assembly may freeze safe evidence, never widen capture policy.
    unsafe = sorted(set(value) - _SAFE_ERROR_FIELDS)
    if unsafe:
        raise ValueError(f"Diagnostic contains unsafe error fields: {', '.join(unsafe)}")
    _nonblank(value.get("type"), "Diagnostic error type")


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


__all__ = ["_new_receipt", "_ReceiptEvidence"]

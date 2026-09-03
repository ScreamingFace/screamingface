"""Construction boundary for immutable local diagnostic receipts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from screamingface._immutable_json import freeze_mapping
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
    frozen = freeze_mapping(document, "Diagnostic")
    return DiagnosticReceipt._from_frozen(frozen)


def _validate_error(value: Mapping[str, object]) -> None:
    # INVARIANT: generic receipt assembly may freeze safe evidence, never widen capture policy.
    unsafe = sorted(set(value) - _SAFE_ERROR_FIELDS)
    if unsafe:
        raise ValueError(f"Diagnostic contains unsafe error fields: {', '.join(unsafe)}")
    _nonblank(value.get("type"), "Diagnostic error type")


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _timestamp_text(value: datetime) -> str:
    rendered = value.astimezone(UTC).isoformat(timespec="milliseconds")
    return rendered.replace("+00:00", "Z")


__all__ = ["_new_receipt", "_ReceiptEvidence"]

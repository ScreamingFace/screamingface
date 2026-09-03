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
_SAFE_CLIENT_FIELDS = frozenset(
    {"name", "version", "host", "platform", "architecture", "runtime", "dependencies"}
)
_SAFE_RUNTIME_FIELDS = frozenset({"name", "version"})
_SAFE_DEPENDENCY_FIELDS = frozenset({"httpx", "websockets", "pydantic", "ipywidgets"})
_SAFE_CONTEXT_FIELDS = frozenset({"engine", "benchmark", "mode", "candidates"})
_SAFE_ENGINE_FIELDS = frozenset({"host", "mode"})
_SAFE_BENCHMARK_FIELDS = frozenset({"id", "revision", "case_count"})
_SAFE_CANDIDATE_FIELDS = frozenset({"name", "kind", "models", "operations", "parameters"})
_SAFE_OPERATION_FIELDS = frozenset({"id", "kind", "depends_on"})
_SAFE_PARAMETER_FIELDS = frozenset({"operation_id", "model", "values"})
_SAFE_EXECUTION_FIELDS = frozenset({"candidate", "status", "trace_id", "gateway_call_id"})
_SAFE_BREADCRUMB_FIELDS = frozenset(
    {"candidate", "stage", "event", "sequence", "outcome", "operation"}
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
    # INVARIANT: evidence containers are closed; widening one requires an explicit privacy review.
    # Parameter values remain open by design because preflight already validated that typed map.
    _validate_client(evidence.client)
    _validate_error(evidence.error)
    _validate_context(evidence.context)
    _reject_forbidden_field(evidence.executions, "run_id")
    _reject_forbidden_field(evidence.breadcrumbs, "run_id")
    _validate_objects(evidence.executions, _SAFE_EXECUTION_FIELDS, "execution")
    _validate_objects(evidence.breadcrumbs, _SAFE_BREADCRUMB_FIELDS, "breadcrumb")
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


def _validate_client(value: Mapping[str, object]) -> None:
    _validate_fields(value, _SAFE_CLIENT_FIELDS, "client")
    _validate_nested_fields(value, "runtime", _SAFE_RUNTIME_FIELDS, "client runtime")
    _validate_nested_fields(
        value,
        "dependencies",
        _SAFE_DEPENDENCY_FIELDS,
        "client dependency",
    )


def _validate_context(value: Mapping[str, object]) -> None:
    _validate_fields(value, _SAFE_CONTEXT_FIELDS, "context")
    _validate_nested_fields(value, "engine", _SAFE_ENGINE_FIELDS, "engine")
    _validate_nested_fields(value, "benchmark", _SAFE_BENCHMARK_FIELDS, "benchmark")
    candidates = value.get("candidates")
    if candidates is None:
        return
    _validate_objects(candidates, _SAFE_CANDIDATE_FIELDS, "candidate")
    assert isinstance(candidates, Sequence) and not isinstance(candidates, str | bytes)
    for candidate in candidates:
        assert isinstance(candidate, Mapping)
        operations = candidate.get("operations")
        if operations is not None:
            _validate_objects(operations, _SAFE_OPERATION_FIELDS, "operation")
        parameters = candidate.get("parameters")
        if parameters is not None:
            _validate_objects(parameters, _SAFE_PARAMETER_FIELDS, "parameter")


def _validate_nested_fields(
    parent: Mapping[str, object],
    field: str,
    allowed: frozenset[str],
    label: str,
) -> None:
    value = parent.get(field)
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise TypeError(f"Diagnostic {label} must be an object")
    _validate_fields(value, allowed, label)


def _validate_objects(value: object, allowed: frozenset[str], label: str) -> None:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TypeError(f"Diagnostic {label} values must be an ordered sequence")
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"Diagnostic {label} values must contain objects")
        _validate_fields(item, allowed, label)


def _validate_fields(value: Mapping[str, object], allowed: frozenset[str], label: str) -> None:
    unsafe = sorted(set(value) - allowed)
    if unsafe:
        raise ValueError(f"Diagnostic contains unsafe {label} fields: {', '.join(unsafe)}")


def _reject_forbidden_field(value: object, field: str) -> None:
    # INVARIANT: Event.run_id is an internal stream topic, never a receipt identity at any depth.
    if isinstance(value, Mapping):
        if field in value:
            raise ValueError(f"Diagnostic contains forbidden field: {field}")
        for item in value.values():
            _reject_forbidden_field(item, field)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            _reject_forbidden_field(item, field)


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _timestamp_text(value: datetime) -> str:
    rendered = value.astimezone(UTC).isoformat(timespec="milliseconds")
    return rendered.replace("+00:00", "Z")


__all__ = ["_new_receipt", "_ReceiptEvidence"]

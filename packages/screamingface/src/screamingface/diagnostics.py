"""Public lookup for process-local diagnostic receipts."""

from __future__ import annotations

from screamingface._diagnostics.store import _STORE
from screamingface.diagnostic import DiagnosticReceipt


def get(diagnostic_id: str) -> DiagnosticReceipt | None:
    """Return one retained local diagnostic receipt, if it has not been evicted."""

    if not isinstance(diagnostic_id, str) or not diagnostic_id.strip():
        raise ValueError("diagnostic_id must be a non-empty string")
    return _STORE.get(diagnostic_id.strip())


def last() -> DiagnosticReceipt | None:
    """Return the newest retained local diagnostic receipt, if any."""

    return _STORE.last()


__all__ = ["get", "last"]

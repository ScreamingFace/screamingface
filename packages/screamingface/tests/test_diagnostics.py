from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import screamingface as sf
from screamingface._diagnostics.model import _new_receipt, _ReceiptEvidence
from screamingface._diagnostics.store import _DiagnosticStore


def _receipt(
    diagnostic_id: str = "diag_first",
    *,
    error_message: str = "The Engine disconnected.",
) -> sf.DiagnosticReceipt:
    return _new_receipt(
        _ReceiptEvidence(
            diagnostic_id=diagnostic_id,
            session_id="session_test",
            occurred_at=datetime(2026, 8, 26, 14, 3, 11, 204000, tzinfo=UTC),
            elapsed_seconds=0.5,
            operation="evaluate",
            outcome="failed",
            client={"name": "screamingface-python", "version": "0.1.1.post5"},
            error={
                "type": "ExecutionError",
                "code": "websocket_disconnected",
                "hint": error_message,
            },
            context={"benchmark": {"id": "draco", "revision": "rev-1"}},
            executions=(
                {
                    "candidate": "candidate-a",
                    "trace_id": "0123456789abcdef0123456789abcdef",
                },
            ),
            breadcrumbs=({"sequence": 1, "stage": "execution", "event": "started"},),
        )
    )


def test_receipt_serialization_is_deterministic_and_versioned() -> None:
    receipt = _receipt()

    assert receipt.diagnostic_id == "diag_first"
    assert receipt.session_id == "session_test"
    assert receipt.outcome == "failed"
    assert receipt.to_dict() == {
        "schema": "screamingface.diagnostic/v1",
        "diagnostic_id": "diag_first",
        "session_id": "session_test",
        "occurred_at": "2026-08-26T14:03:11.204Z",
        "elapsed_seconds": 0.5,
        "operation": "evaluate",
        "outcome": "failed",
        "client": {"name": "screamingface-python", "version": "0.1.1.post5"},
        "error": {
            "type": "ExecutionError",
            "code": "websocket_disconnected",
            "hint": "The Engine disconnected.",
        },
        "context": {"benchmark": {"id": "draco", "revision": "rev-1"}},
        "executions": [
            {
                "candidate": "candidate-a",
                "trace_id": "0123456789abcdef0123456789abcdef",
            }
        ],
        "breadcrumbs": [{"sequence": 1, "stage": "execution", "event": "started"}],
    }
    assert json.loads(receipt.to_json()) == receipt.to_dict()
    assert '": ' not in receipt.to_json()
    assert '", ' not in receipt.to_json()


def test_receipt_construction_rejects_unsafe_error_fields() -> None:
    with pytest.raises(ValueError, match="unsafe error fields: message"):
        _new_receipt(
            _ReceiptEvidence(
                diagnostic_id="diag_unsafe",
                session_id="session_test",
                occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
                elapsed_seconds=0.5,
                operation="evaluate",
                outcome="failed",
                client={"name": "screamingface-python"},
                error={"type": "ExecutionError", "message": "private server response"},
                context={},
            )
        )


def test_receipt_to_dict_returns_an_independent_tree() -> None:
    receipt = _receipt()

    first = receipt.to_dict()
    client = first["client"]
    executions = first["executions"]
    assert isinstance(client, dict)
    assert isinstance(executions, list)
    assert isinstance(executions[0], dict)
    client["version"] = "changed"
    executions[0]["candidate"] = "changed"

    assert receipt.to_dict()["client"] == {
        "name": "screamingface-python",
        "version": "0.1.1.post5",
    }
    assert receipt.to_dict()["executions"] == [
        {
            "candidate": "candidate-a",
            "trace_id": "0123456789abcdef0123456789abcdef",
        }
    ]


def test_receipt_cannot_be_mutated_after_creation() -> None:
    receipt = _receipt()

    with pytest.raises(AttributeError):
        setattr(receipt, "_document", {})


def test_receipt_export_matches_to_json_bytes(tmp_path) -> None:
    receipt = _receipt()
    selected = tmp_path / "nested" / "diagnostic.json"

    assert receipt.export(selected) == selected
    assert selected.read_text(encoding="utf-8") == receipt.to_json()
    with pytest.raises(ValueError, match="must be a .json file"):
        receipt.export(tmp_path / "diagnostic.txt")


def test_store_evicts_oldest_receipt_at_count_limit() -> None:
    store = _DiagnosticStore(max_count=2, max_bytes=100_000)
    first = _receipt("diag_first")
    second = _receipt("diag_second")
    third = _receipt("diag_third")

    assert store.add(first) is True
    assert store.add(second) is True
    assert store.add(third) is True

    assert store.get("diag_first") is None
    assert store.get("diag_second") is second
    assert store.last() is third


def test_store_evicts_oldest_receipt_at_byte_limit() -> None:
    first = _receipt("diag_first", error_message="a")
    second = _receipt("diag_second", error_message="b")
    budget = len(first.to_json().encode("utf-8")) + len(second.to_json().encode("utf-8")) - 1
    store = _DiagnosticStore(max_count=10, max_bytes=budget)

    assert store.add(first) is True
    assert store.add(second) is True

    assert store.get("diag_first") is None
    assert store.get("diag_second") is second


def test_store_declines_oversize_receipt_without_evicting_existing() -> None:
    existing = _receipt("diag_existing", error_message="ok")
    oversize = _receipt("diag_oversize", error_message="x" * 2_000)
    budget = len(existing.to_json().encode("utf-8"))
    store = _DiagnosticStore(max_count=10, max_bytes=budget)
    assert store.add(existing) is True

    assert store.add(oversize) is False

    assert store.last() is existing
    assert store.get("diag_oversize") is None


def test_store_rejects_duplicate_diagnostic_identity() -> None:
    store = _DiagnosticStore(max_count=10, max_bytes=100_000)
    assert store.add(_receipt("diag_same")) is True

    with pytest.raises(ValueError, match="already exists"):
        store.add(_receipt("diag_same", error_message="another failure"))

"""Payload hashing occurs only while the payload-free grading ledger is active."""

from __future__ import annotations

import pytest

from screamingface_engine.operation_calls import (
    capture_request_accounting,
    operation_call_identity,
    record_operation_call,
    suspend_request_accounting,
)


def test_suspended_candidate_call_does_not_compute_a_complete_request_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_fingerprint(**_fields: object) -> None:
        raise AssertionError("Candidate payload was fingerprinted")

    monkeypatch.setattr(
        "screamingface_engine.operation_calls.model_request_key",
        unexpected_fingerprint,
    )

    with capture_request_accounting() as captured:
        with suspend_request_accounting():
            with operation_call_identity(
                "/provider/model",
                {"temperature": "0"},
                context="private candidate prompt",
                intent="private candidate instruction",
            ):
                record_operation_call("answer", "stop")

    assert captured == []

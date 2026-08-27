"""Exact grading-request ownership over the shared operation-call recorder."""

from __future__ import annotations

import logging

from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    capture_grading_requests,
    register_grading_request,
)
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.operation_calls import (
    capture_operation_calls,
    operation_call_identity,
    record_operation_call,
)


def _owner(*, check_id: str = "rubric-1") -> GradingEvidenceOwner:
    return GradingEvidenceOwner(
        benchmark_id="healthbench",
        case_id=7,
        check_id=check_id,
        sequence=1,
    )


def _accounting(cost: str) -> OperationAccounting:
    return OperationAccounting(
        provider="openrouter",
        request_model="judge",
        response_model="judge-served",
        usage=OperationUsage(
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            reasoning_tokens=1,
            cost_usd=cost,
        ),
        provider_latency_ms=20,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def _register(owner: GradingEvidenceOwner) -> None:
    register_grading_request(
        owner,
        path="/judge",
        params={"temperature": "0.2"},
        context="private grader prompt",
        intent="",
    )


def _record(cost: str) -> None:
    with operation_call_identity(
        "/judge",
        {"temperature": "0.2"},
        context="private grader prompt",
        intent="",
    ):
        record_operation_call("verdict", "stop", _accounting(cost))


def test_unique_owner_receives_the_matching_call_accounting() -> None:
    owner = _owner()
    with capture_operation_calls():
        with capture_grading_requests():
            _register(owner)
            _record("0.1")

            accounting = accounting_for_grading_evidence(owner)

    assert accounting is not None
    assert accounting.usage.cost_usd == "0.1"


def test_redraws_for_one_owner_are_strictly_aggregated() -> None:
    owner = _owner()
    with capture_operation_calls():
        with capture_grading_requests():
            _register(owner)
            _record("0.1")
            _record("0.2")

            accounting = accounting_for_grading_evidence(owner)

    assert accounting is not None
    assert accounting.usage.cost_usd == "0.3"
    assert accounting.cache.misses == 2


def test_duplicate_request_owners_disable_attribution_without_payload_logging(
    caplog,
) -> None:
    first = _owner(check_id="rubric-1")
    second = _owner(check_id="rubric-2")
    with caplog.at_level(logging.WARNING):
        with capture_operation_calls():
            with capture_grading_requests():
                _register(first)
                _register(second)
                _record("0.1")

                assert accounting_for_grading_evidence(first) is None
                assert accounting_for_grading_evidence(second) is None

    assert "private grader prompt" not in caplog.text
    assert caplog.text.count("multiple owners") == 1


def test_missing_scope_or_call_never_invents_accounting() -> None:
    owner = _owner()
    _register(owner)
    assert accounting_for_grading_evidence(owner) is None

    with capture_operation_calls():
        with capture_grading_requests():
            _register(owner)
            assert accounting_for_grading_evidence(owner) is None


def test_candidate_isolated_recorder_does_not_enter_the_run_grading_ledger() -> None:
    owner = _owner()
    with capture_operation_calls():
        with capture_grading_requests():
            _register(owner)
            with capture_operation_calls(isolated=True):
                _record("0.1")

            assert accounting_for_grading_evidence(owner) is None

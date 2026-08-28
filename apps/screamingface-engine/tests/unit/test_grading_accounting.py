"""Exact grading-request ownership over the shared operation-call recorder."""

from __future__ import annotations

import logging

import pytest

from screamingface_engine.benchmarks.contract import (
    CandidateResult,
    CaseGrade,
    CaseResult,
    Check,
    Evidence,
    EvidenceProducer,
)
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    capture_grading_requests,
    reconcile_candidate_grading_accounting,
    register_grading_request,
)
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    OperationCache,
    OperationUsage,
)
from screamingface_engine.operation_calls import (
    RequestAccounting,
    capture_request_accounting,
    operation_call_identity,
    record_operation_call,
    suspend_request_accounting,
)
from screamingface_engine.request_identity import model_request_key


class _CountingCalls(list[RequestAccounting]):
    def __init__(self, calls: list[RequestAccounting]) -> None:
        super().__init__(calls)
        self.full_iterations = 0

    def __iter__(self):
        self.full_iterations += 1
        return super().__iter__()


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
        provider_attempts=1,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def _candidate_result_with_evidence(
    first: GradingEvidenceOwner,
    second: GradingEvidenceOwner,
) -> CandidateResult:
    producer = EvidenceProducer(type="model", id="judge")
    checks = [
        Check(
            type="rubric",
            id=owner.check_id,
            label=owner.check_id,
            outcome="MET",
            score=1.0,
            evidence=[
                Evidence(
                    sequence=owner.sequence,
                    producer=producer,
                    valid=True,
                    outcome="MET",
                    explanation="ok",
                    raw_output="verdict",
                    metadata={},
                    accounting=None,
                )
            ],
            metadata={},
        )
        for owner in (first, second)
    ]
    case = CaseResult(
        status="scored",
        case_id=first.case_id,
        input="question",
        output="answer",
        finish_reason="stop",
        refusal=None,
        grade=CaseGrade(method="rubric", score=1.0, metrics={}, checks=checks),
        failures=[],
        metadata={},
    )
    return CandidateResult(
        benchmark_id=first.benchmark_id,
        benchmark_revision="revision",
        case_count=1,
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=[case],
        failures=[],
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
    with capture_request_accounting():
        with capture_grading_requests():
            _register(owner)
            _record("0.1")

            accounting = accounting_for_grading_evidence(owner)

    assert accounting is not None
    assert accounting.usage.cost_usd == "0.1"


def test_redraws_for_one_owner_are_strictly_aggregated() -> None:
    owner = _owner()
    with capture_request_accounting():
        with capture_grading_requests():
            _register(owner)
            _record("0.1")
            _record("0.2")

            accounting = accounting_for_grading_evidence(owner)

    assert accounting is not None
    assert accounting.usage.cost_usd == "0.3"
    assert accounting.cache.misses == 2


def test_revised_requests_for_one_owner_are_strictly_aggregated() -> None:
    owner = _owner()
    with capture_request_accounting():
        with capture_grading_requests():
            register_grading_request(
                owner,
                path="/judge",
                params={"temperature": "0.2"},
                context="first answer",
                intent="",
            )
            with operation_call_identity(
                "/judge", {"temperature": "0.2"}, context="first answer", intent=""
            ):
                record_operation_call("first verdict", "stop", _accounting("0.1"))
            register_grading_request(
                owner,
                path="/judge",
                params={"temperature": "0.2"},
                context="revised answer",
                intent="",
            )
            with operation_call_identity(
                "/judge", {"temperature": "0.2"}, context="revised answer", intent=""
            ):
                record_operation_call("revised verdict", "stop", _accounting("0.2"))

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
        with capture_request_accounting():
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

    with capture_request_accounting():
        with capture_grading_requests():
            _register(owner)
            assert accounting_for_grading_evidence(owner) is None


def test_suspended_candidate_work_does_not_enter_the_run_grading_ledger() -> None:
    owner = _owner()
    with capture_request_accounting():
        with capture_grading_requests():
            _register(owner)
            with suspend_request_accounting():
                _record("0.1")

            assert accounting_for_grading_evidence(owner) is None


def test_repeated_verdict_lookups_do_not_rescan_the_full_run_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _owner(check_id="rubric-1")
    second = _owner(check_id="rubric-2")
    first_key = model_request_key(
        path="/judge", params={"temperature": "0.2"}, context="first", intent=""
    )
    second_key = model_request_key(
        path="/judge", params={"temperature": "0.2"}, context="second", intent=""
    )
    calls = _CountingCalls(
        [
            RequestAccounting(
                request_key=first_key if index < 50 else second_key,
                accounting=_accounting("0.1"),
            )
            for index in range(100)
        ]
    )
    monkeypatch.setattr(
        "screamingface_engine.grading_accounting.current_request_accounting", lambda: calls
    )

    with capture_grading_requests():
        register_grading_request(
            first,
            path="/judge",
            params={"temperature": "0.2"},
            context="first",
            intent="",
        )
        register_grading_request(
            second,
            path="/judge",
            params={"temperature": "0.2"},
            context="second",
            intent="",
        )

        assert accounting_for_grading_evidence(first) is not None
        assert accounting_for_grading_evidence(second) is not None

    assert calls.full_iterations <= 1


def test_lookup_indexes_calls_appended_after_an_earlier_verdict() -> None:
    first = _owner(check_id="rubric-1")
    second = _owner(check_id="rubric-2")

    with capture_request_accounting():
        with capture_grading_requests():
            register_grading_request(
                first,
                path="/judge",
                params={"temperature": "0.2"},
                context="first",
                intent="",
            )
            with operation_call_identity(
                "/judge", {"temperature": "0.2"}, context="first", intent=""
            ):
                record_operation_call("first verdict", "stop", _accounting("0.1"))
            assert accounting_for_grading_evidence(first) is not None

            register_grading_request(
                second,
                path="/judge",
                params={"temperature": "0.2"},
                context="second",
                intent="",
            )
            with operation_call_identity(
                "/judge", {"temperature": "0.2"}, context="second", intent=""
            ):
                record_operation_call("second verdict", "stop", _accounting("0.2"))
            accounting = accounting_for_grading_evidence(second)

    assert accounting is not None
    assert accounting.usage.cost_usd == "0.2"


def test_final_reconciliation_revokes_accounting_after_a_late_owner_collision() -> None:
    first = _owner(check_id="rubric-1")
    second = _owner(check_id="rubric-2")
    candidate = _candidate_result_with_evidence(first, second)
    grade = candidate.cases[0].grade
    assert grade is not None

    with capture_request_accounting():
        with capture_grading_requests():
            _register(first)
            _record("0.1")
            provisional = accounting_for_grading_evidence(first)
            assert provisional is not None
            grade.checks[0].evidence[0].accounting = provisional

            _register(second)
            reconcile_candidate_grading_accounting(candidate)

    evidence = grade.checks
    assert evidence[0].evidence[0].accounting is None
    assert evidence[1].evidence[0].accounting is None

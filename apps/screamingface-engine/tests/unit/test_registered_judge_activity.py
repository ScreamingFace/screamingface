"""Reuse explicit authored request ownership without guessing from model names."""

from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    capture_grading_requests,
    register_grading_request,
)
from screamingface_engine.grading_call_scope import current_grading_case
from screamingface_engine.observations import RunObservations
from screamingface_engine.operation_calls import capture_request_accounting, operation_call_identity


def _register(case):
    register_grading_request(
        GradingEvidenceOwner("board", case, "criterion", 1),
        path="/judge",
        params={},
        context="prompt",
        intent="grade",
    )


def test_explicit_request_owner_is_available_only_inside_its_run_and_call():
    run = RunObservations(())
    with run.bind(), capture_request_accounting(), capture_grading_requests():
        _register(42)
        assert current_grading_case() is None
        with operation_call_identity("/judge", {}, context="prompt", intent="grade"):
            assert current_grading_case() == 42
            with candidate_invocation_scope():
                assert current_grading_case() is None
            with RunObservations(()).bind():
                assert current_grading_case() is None
        assert current_grading_case() is None


def test_ambiguous_or_different_request_never_borrows_case_identity():
    with capture_request_accounting(), capture_grading_requests():
        _register(42)
        with operation_call_identity("/judge", {}, context="different", intent="grade"):
            assert current_grading_case() is None
        _register(43)
        with operation_call_identity("/judge", {}, context="prompt", intent="grade"):
            assert current_grading_case() is None

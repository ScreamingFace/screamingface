"""OME-1775 blocking review: unknown failures and absent stored proof stay partial."""

from __future__ import annotations

import httpx
import pytest
from test_benchmark_aggregation import _failed, _selected

from screamingface_engine.benchmarks.aggregation import CandidateScore, finalize_candidate_result
from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES, Failure
from screamingface_engine.benchmarks.failure_classes import TIME_BASED_CODES
from screamingface_engine.benchmarks.shared_grading.attempt_fold import fold_case_attempts
from screamingface_engine.capture_outcomes import CaptureOutcome, CaptureTally, capture_outcomes
from screamingface_engine.world.capture_proof import replay_failure_code
from url4.core.errors import ErrorCode


@pytest.mark.parametrize(
    ("code", "retryable", "metadata", "may_score"),
    [
        ("model_token_cap", False, {}, False),
        ("model_token_cap", True, {}, True),
        ("case_error", False, {"source_error": {"code": "model_token_cap"}}, False),
        (
            "case_error",
            True,
            {"source_error": {"code": "resolution_failed", "retryable": True}},
            True,
        ),
        ("case_error", False, {"source_error": {"code": "resolution_failed"}}, True),
        ("upstream_error", False, {"source_code": "new_failure"}, True),
        ("model_token_cap", False, {"source_code": "resolution_failed"}, True),
        (
            "case_error",
            False,
            {"source_error": {"code": "model_token_cap", "retryable": True}},
            True,
        ),
        (
            "model_token_cap",
            False,
            {"source_error": {"code": "model_token_cap", "source_code": "timeout"}},
            True,
        ),
    ],
)
def test_finalizer_requires_positive_deterministic_failure(
    code: str, retryable: bool, metadata: dict, may_score: bool
) -> None:
    failure = Failure(
        stage="candidate", code=code, message="m", retryable=retryable, case_id=1, metadata=metadata
    )
    with capture_outcomes() as tally:
        finalize_candidate_result(
            benchmark_id="benchmark",
            benchmark_revision="r",
            selected_cases=_selected(1),
            cases=[_failed(1).model_copy(update={"failures": [failure]})],
            scorer=lambda _: CandidateScore(score=0.0, metrics={}),
            failure_policy="withhold",
        )
    assert tally.case_results == {"1": may_score}


@pytest.mark.parametrize("second_code", ["candidate_failed", "case_result_missing"])
def test_an_unknown_later_attempt_prevents_forgiveness(second_code: str) -> None:
    def case(code: str):
        failure = Failure(
            stage="candidate", code=code, message="m", retryable=False, case_id=1, metadata={}
        )
        return _failed(1).model_copy(update={"failures": [failure]})

    folded = fold_case_attempts([case("model_token_cap"), case(second_code)])
    with capture_outcomes() as tally:
        finalize_candidate_result(
            benchmark_id="benchmark",
            benchmark_revision="r",
            selected_cases=_selected(1),
            cases=[folded],
            scorer=lambda _: CandidateScore(score=0.0, metrics={}),
            failure_policy="withhold",
        )
    assert tally.case_results == {"1": True}


@pytest.mark.parametrize(
    ("proof", "expected"),
    [
        (None, "partial"),
        (CaptureOutcome("chat", "stored", "cause", "1", "k", 0), "partial"),
        (
            CaptureOutcome(
                "chat", "failed", "cause", "1", "k", 0, replay_failure="model_token_cap"
            ),
            "partial",
        ),
        (
            CaptureOutcome(
                "chat", "stored", "cause", "2", "k", 0, replay_failure="model_token_cap"
            ),
            "partial",
        ),
        (
            CaptureOutcome(
                "chat", "stored", "cause", "1", "other-attempt", 0, replay_failure="model_token_cap"
            ),
            "partial",
        ),
        (
            CaptureOutcome(
                "chat", "stored", "cause", "1", "k", 0, replay_failure="model_token_cap"
            ),
            "complete",
        ),
    ],
)
def test_stored_failure_must_match_the_cancelled_calls_case_and_attempt(
    proof: CaptureOutcome | None, expected: str
) -> None:
    tally = CaptureTally(mode="capture", sealed=True, case_results={"1": False})
    tally.outcomes.append(CaptureOutcome("chat", "error", "cancelled", "1", "k", 0, False))
    if proof is not None:
        tally.outcomes.append(proof)
    assert tally.status() == expected


@pytest.mark.parametrize(
    ("message", "finish", "expected"),
    [
        ({"content": None}, "length", "model_token_cap"),
        ({"content": ""}, "length", "model_token_cap"),
        ({"content": "answer"}, "length", None),
        ({"content": None, "tool_calls": [{"id": "t"}]}, "length", None),
        ({"content": None, "refusal": "no"}, "length", None),
        ({"content": None}, "stop", None),
        ("malformed", "length", None),
    ],
)
def test_only_a_classified_token_cap_is_replay_proof(message, finish, expected) -> None:
    response = httpx.Response(
        200, json={"choices": [{"message": message, "finish_reason": finish}]}
    )
    assert replay_failure_code(response) == expected


def test_malformed_json_is_not_replay_proof() -> None:
    assert replay_failure_code(httpx.Response(200, content=b"broken")) is None


def test_timeout_guard_uses_declared_codes() -> None:
    assert TIME_BASED_CODES <= DECLARED_FAILURE_CODES | {code.value for code in ErrorCode}

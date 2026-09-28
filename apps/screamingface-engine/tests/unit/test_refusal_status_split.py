"""The case-status space carries one meaning per value (OME-1037).

INVARIANT defended: `refused` is no longer a case status — the word meant "provider
declined" in most benchmarks and "correct answer" in DRACO (refusing a deceptive
prompt is graded as success). A refusal the benchmark graded is an ordinary `scored`
case carrying `refusal` text; a refusal the benchmark could not grade is a `failed`
case carrying a `provider_refusal` failure plus the grading failures. The invocation
layer's `refused` (`CandidateInvocationStatus`) is untouched — there it unambiguously
means "the candidate did not answer".
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from screamingface_engine.benchmarks.aggregation import (
    SelectedCase,
    refusal_case_result,
)
from screamingface_engine.benchmarks.contract import CaseResult


def _grade(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "method": "rubric",
        "score": 1.0,
        "metrics": {"judged": 3},
        "checks": [],
    }
    values.update(overrides)
    return values


def _case(**overrides: Any) -> CaseResult:
    values: dict[str, Any] = {
        "status": "scored",
        "case_id": 7,
        "input": "A deceptive prompt.",
        "output": None,
        "finish_reason": "stop",
        "refusal": "I will not help with that.",
        "grade": _grade(),
        "failures": [],
        "metadata": {},
    }
    values.update(overrides)
    return CaseResult.model_validate(values)


def _grading_failure(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "stage": "grading",
        "code": "incomplete_verdicts",
        "message": "the Judge did not return a usable verdict",
        "retryable": True,
        "case_id": 7,
        "metadata": {},
    }
    values.update(overrides)
    return values


def _selected_case() -> SelectedCase:
    return SelectedCase(case_id=7, input="A deceptive prompt.", metadata={"axis": "deception"})


def test_refused_is_no_longer_a_case_status() -> None:
    # WHY: the one word carried two opposite meanings across benchmarks; after
    # OME-1037 the wire vocabulary has no `refused` case status at all.
    with pytest.raises(ValidationError):
        _case(status="refused")


def test_a_graded_refusal_is_an_ordinary_scored_case_carrying_refusal_text() -> None:
    # STORY: DRACO grades a model's decline of a deceptive prompt as success — a
    # graded refusal is a normal scored outcome, not failure vocabulary.
    case = _case()

    assert case.status == "scored"
    assert case.output is None
    assert case.refusal == "I will not help with that."
    assert case.grade is not None and case.grade.score == 1.0


@pytest.mark.parametrize(
    ("output", "refusal"),
    [
        pytest.param("An answer.", "I refuse.", id="both-answer-and-refusal"),
        pytest.param(None, None, id="neither-answer-nor-refusal"),
    ],
)
def test_a_scored_case_carries_exactly_one_of_output_and_refusal(
    output: str | None, refusal: str | None
) -> None:
    # INVARIANT: a scored case is either an answer that was graded or a refusal
    # that was graded — never both, never neither.
    with pytest.raises(ValidationError, match="exactly one"):
        _case(output=output, refusal=refusal)


def test_an_ungradeable_refusal_is_a_failed_case_with_a_provider_refusal_failure() -> None:
    case = _case(
        status="failed",
        grade=_grade(score=None, metrics={}),
        failures=[
            _grading_failure(
                stage="candidate", code="provider_refusal", message="provider refused the request"
            ),
            _grading_failure(),
        ],
    )

    assert case.status == "failed"
    assert case.refusal == "I will not help with that."


def test_a_failed_case_carries_refusal_text_only_as_provider_refusal_evidence() -> None:
    # INVARIANT: refusal text on a failed case is evidence for a provider_refusal
    # failure; any other failed case stays refusal-free.
    with pytest.raises(ValidationError, match="provider_refusal"):
        _case(status="failed", grade=_grade(score=None, metrics={}), failures=[_grading_failure()])


def test_builder_classifies_a_graded_refusal_as_scored() -> None:
    case = refusal_case_result(
        selected_case=_selected_case(),
        refusal="I will not help with that.",
        finish_reason="stop",
        grade=_grade(score=0.8),
    )

    assert case.status == "scored"
    assert case.refusal == "I will not help with that."
    assert case.output is None
    assert case.grade is not None and case.grade.score == 0.8
    assert case.failures == []


def test_builder_classifies_an_ungraded_refusal_as_failed_with_provider_refusal() -> None:
    case = refusal_case_result(
        selected_case=_selected_case(),
        refusal="I will not help with that.",
        finish_reason="stop",
        grade=_grade(score=None, metrics={}),
        failures=[_grading_failure()],
    )

    assert case.status == "failed"
    # WHY the ordering: the provider refusal explains WHY grading failed, so it
    # leads; the grading failures follow as the downstream evidence.
    assert [failure.code for failure in case.failures] == [
        "provider_refusal",
        "incomplete_verdicts",
    ]
    assert case.refusal == "I will not help with that."
    assert case.grade is not None and case.grade.score is None


def test_builder_demotes_a_textless_provider_decline_even_when_a_score_came_back() -> None:
    # WHY: a textless refusal is exactly a content_filter provider decline
    # (`raise_if_unusable` fires on content_filter OR non-null refusal, and
    # content_filter turns normally carry null text). The model never answered, so
    # a judge score over the empty answer would be an infrastructure failure
    # published as a plausible grade — the score is dropped, the checks stay as
    # audit evidence, and the case is a visible provider failure.
    case = refusal_case_result(
        selected_case=_selected_case(),
        refusal=None,
        finish_reason="content_filter",
        grade=_grade(score=0.0, metrics={"judged": 3}),
    )

    assert case.status == "failed"
    assert case.refusal is None
    assert [failure.code for failure in case.failures] == ["provider_refusal"]
    assert case.grade is not None and case.grade.score is None
    assert case.grade.metrics == {"judged": 3}


def test_builder_keeps_selected_case_metadata_and_finish_reason() -> None:
    case = refusal_case_result(
        selected_case=_selected_case(),
        refusal="I will not help with that.",
        finish_reason="content_filter",
        grade=_grade(score=1.0),
    )

    assert case.metadata == {"axis": "deception"}
    assert case.finish_reason == "content_filter"
    assert case.case_id == 7

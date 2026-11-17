"""A Candidate Result body is written as JSON text one piece at a time (OME-1835, memory fix 3).

FEATURE: ``write_result_body`` writes the head of the payload, then one compact JSON fragment
per Case. The bytes are the bytes of ``compact_json(result.as_payload())``.
INVARIANT defended: byte identity with the whole dump, for every fixture, including the keys
that come after ``cases`` (``inverted_grade``, ``scores``), NaN, non-ASCII text and an empty
selection.
"""

from __future__ import annotations

import pytest
from test_candidate_result_contract import _candidate, _failure, _grade, _scored_case
from test_e4c_gate_attribution import _decision

from screamingface_engine.benchmarks.contract import CandidateResult, CaseAttempt, OperationOutput
from screamingface_engine.benchmarks.grading_endpoints import compact_json
from screamingface_engine.benchmarks.result_body import (
    HeldResultBody,
    encode_result_body,
    write_result_body,
)
from screamingface_engine.budget import CallCharge


def _fixtures() -> dict[str, CandidateResult]:
    return {
        "baseline": _candidate(),
        "non_ascii_and_emoji": _candidate().model_copy(
            update={
                "case_count": 2,
                "cases": [
                    _scored_case(7).model_copy(update={"output": "naïve → “quoted” 😀"}),
                    _scored_case(8).model_copy(
                        update={"input": "¿Qué? 日本語", "metadata": {"tags": ["é", 1, None, True]}}
                    ),
                ],
            }
        ),
        "failed_and_missing": _candidate().model_copy(
            update={
                "case_count": 2,
                "cases": [
                    _scored_case(7),
                    _scored_case(8).model_copy(
                        update={
                            "status": "failed",
                            "output": None,
                            "finish_reason": None,
                            "grade": None,
                            "failures": [
                                _failure(code="case_result_missing", case_id=8, retryable=False)
                            ],
                        }
                    ),
                ],
                "failures": [_failure(case_id=None)],
            }
        ),
        "attempts": _candidate().model_copy(
            update={
                "cases": [
                    _scored_case(7).model_copy(
                        update={
                            "attempts": [
                                CaseAttempt.model_construct(
                                    attempt=1,
                                    status="scored",
                                    output="A",
                                    finish_reason="stop",
                                    refusal=None,
                                    grade=_grade(),
                                    failures=[],
                                    operations=None,
                                ),
                                CaseAttempt.model_construct(
                                    attempt=2,
                                    status="scored",
                                    output="B",
                                    finish_reason="stop",
                                    refusal=None,
                                    grade=_grade().model_copy(update={"score": 0.0}),
                                    failures=[],
                                    operations=None,
                                ),
                            ]
                        }
                    )
                ]
            }
        ),
        "operations_with_decision_and_charges": _candidate().model_copy(
            update={
                "cases": [
                    _scored_case(7).model_copy(
                        update={
                            "operations": [
                                OperationOutput.model_construct(
                                    operation_id="model_1",
                                    output="x → y",
                                    finish_reason="stop",
                                    accounting=None,
                                    combine=None,
                                    decision=_decision(1, "then", result=None),
                                    charges=[CallCharge(usd=0.002, tokens=150.0)],
                                ),
                                OperationOutput.model_construct(
                                    operation_id="model_2",
                                    output=None,
                                    finish_reason=None,
                                    accounting=None,
                                    combine=None,
                                    decision=None,
                                    charges=None,
                                ),
                            ]
                        }
                    )
                ]
            }
        ),
        "abstained": _candidate().model_copy(
            update={
                "cases": [
                    _scored_case(9).model_copy(
                        update={
                            "abstained": True,
                            "output": "",
                            "grade": _grade().model_copy(update={"score": 0.0}),
                        }
                    )
                ]
            }
        ),
        "inverted_grade_and_scores": _candidate().model_copy(
            update={"inverted_grade": True, "scores": {"headline": 1.0, "other": None}}
        ),
        "empty_selection": _candidate().model_copy(
            update={"case_count": 0, "cases": [], "score": None, "coverage": 0.0, "metrics": {}}
        ),
        "nan_metric": _candidate().model_copy(
            update={"metrics": {"pass_rate": float("nan"), "n": 1}}
        ),
    }


@pytest.mark.parametrize("name", sorted(_fixtures()))
def test_the_streamed_body_is_byte_identical_to_the_whole_dump(name):
    result = _fixtures()[name]

    assert encode_result_body(HeldResultBody(result)) == compact_json(result.as_payload())


def test_the_head_keeps_wire_key_order_with_empty_cases():
    result = _fixtures()["inverted_grade_and_scores"]

    head = HeldResultBody(result).head()

    assert list(head) == list(result.as_payload())
    assert head["cases"] == []
    assert result.cases


def test_inverted_grade_and_scores_are_written_after_cases():
    text = encode_result_body(HeldResultBody(_fixtures()["inverted_grade_and_scores"]))

    assert text.index('"cases":') < text.index('"inverted_grade":true') < text.index('"scores":')


def test_an_empty_selection_writes_an_empty_cases_array():
    assert '"cases":[]' in encode_result_body(HeldResultBody(_fixtures()["empty_selection"]))


def test_nan_is_written_as_nan():
    assert '"pass_rate":NaN' in encode_result_body(HeldResultBody(_fixtures()["nan_metric"]))


def test_non_ascii_is_not_escaped():
    text = encode_result_body(HeldResultBody(_fixtures()["non_ascii_and_emoji"]))

    assert "😀" in text
    assert "\\ud83d" not in text


def test_each_case_is_written_as_its_own_piece():
    result = _fixtures()["non_ascii_and_emoji"]
    pieces: list[str] = []

    write_result_body(HeldResultBody(result), pieces.append)

    for case in result.cases:
        assert compact_json(case.model_dump(by_alias=True)) in pieces
    assert compact_json(result.as_payload()) not in pieces

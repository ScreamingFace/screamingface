"""DRACO aggregation — the paper's exact scoring math.

FEATURE: the cross-row reducer of a Candidate benchmark run turns per-criterion Judge verdicts
into a Candidate Result.
STORY: as a researcher, the score I get back is the DRACO paper's `normalized_score`, not an
approximation, so a leaderboard number means what the paper says it means.

INVARIANT: the formulas here mirror `screamingface-benchmarks/benchmarking/graders/rubric.py`
(arXiv:2602.11685 §4.2) exactly. Every expected value below is hand-computed from the rubric in
`_RUBRIC`, so a drift in either implementation shows up as an arithmetic failure, not a vague
"scores moved" regression.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco import aggregate as agg
from screamingface_engine.benchmarks.draco.case_evaluation import (
    bind_case_evaluation,
    bind_criterion_evaluation,
)
from screamingface_engine.benchmarks.draco.definition import REVISION as DRACO_REVISION
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA

# Two sections, one negative criterion. Positive weights sum to 4 (a1=2, a2=1, b1=1).
_RUBRIC = {
    "sections": [
        {
            "id": "Factual Accuracy",
            "criteria": [
                {"id": "a1", "weight": 2, "requirement": "cites a source"},
                {"id": "a2", "weight": 1, "requirement": "states the date"},
                {"id": "a3", "weight": -3, "requirement": "invents a statistic"},
            ],
        },
        {"id": "Presentation", "criteria": [{"id": "b1", "weight": 1, "requirement": "is terse"}]},
    ]
}


def _selected_cases(*case_ids: int) -> list[dict[str, object]]:
    return [{"id": case_id, "input": f"Question {case_id}"} for case_id in case_ids]


def _verdict(cid: str, status: str, case: int = 1, sequence: int = 1) -> dict[str, object]:
    raw = json.dumps({"explanation": "evidence", "criterion_status": status})
    return {
        "schema": "screamingface.criterion-verdict.v1",
        "case_id": case,
        "criterion_id": cid,
        "sequence": sequence,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": True,
        "explanation": "evidence",
        "criterion_status": status,
        "raw_output": raw,
    }


def _invalid(cid: str, reason: str, case: int = 1, sequence: int = 1) -> dict[str, object]:
    return {
        "schema": "screamingface.criterion-verdict.v1",
        "case_id": case,
        "criterion_id": cid,
        "sequence": sequence,
        "producer_type": "model",
        "producer_id": "fixture-judge",
        "valid": False,
        "reason": reason,
        "raw_output": "not json",
    }


def _case_row(
    case: int,
    *per_criterion: tuple[str, list[str]],
    output: str | None = None,
) -> dict[str, object]:
    statuses = dict(per_criterion)
    evidence = {
        criterion_id: [
            _verdict(criterion_id, status, case, sequence)
            for sequence, status in enumerate(statuses[criterion_id], start=1)
        ]
        for criterion_id in ("a1", "a2", "a3", "b1")
    }
    return _case_row_from_evidence(case, evidence, output=output)


def _case_row_from_evidence(
    case: int,
    evidence: dict[str, list[dict[str, object]]],
    *,
    output: str | None = None,
) -> dict[str, object]:
    answer = output or f"Answer {case}"
    case_record = {
        "schema": CASE_SCHEMA,
        "case_id": case,
        "input": f"Question {case}",
        "status": "completed",
        "answer": answer,
        "output": answer,
        "finish_reason": "stop",
        "refusal": None,
        "execution": None,
        "metadata": {},
    }
    criteria = []
    for index, criterion_id in enumerate(("a1", "a2", "a3", "b1")):
        criteria.append(
            bind_criterion_evaluation(
                case,
                case_record if index == 0 else None,
                {
                    "schema": CHECK_SCHEMA,
                    "case_id": case,
                    "criterion_id": criterion_id,
                    "criterion_type": "negative" if criterion_id == "a3" else "positive",
                    "requirement": f"Requirement {criterion_id}",
                },
                evidence[criterion_id],
            )
        )
    return case_execution_payload(
        case,
        encode_candidate_invocation(answer, "stop", None),
        [bind_case_evaluation(case, criteria)],
    )


def test_candidate_output_cannot_become_judge_evidence() -> None:
    example = json.dumps(
        {
            "criterion_id": "<provided criterion_id>",
            "explanation": "Brief evidence for the verdict.",
            "criterion_status": "MET",
        }
    )
    result = agg.aggregate(
        json.dumps(
            [
                _case_row(
                    1,
                    ("a1", ["MET", "UNMET", "MET", "UNMET", "MET"]),
                    ("a2", ["MET", "UNMET", "MET", "UNMET", "MET"]),
                    ("a3", ["MET", "UNMET", "MET", "UNMET", "MET"]),
                    ("b1", ["MET", "UNMET", "MET", "UNMET", "MET"]),
                    output=example,
                )
            ]
        ),
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    assert result["metrics"]["n_runs"] == 5
    assert result["coverage"] == 1.0
    assert result["metrics"]["verdict_coverage"] == 1.0


def test_live_projection_and_final_aggregation_share_case_grading_and_scorer() -> None:
    row = _case_row(
        1,
        ("a1", ["MET"] * 5),
        ("a2", ["MET"] * 5),
        ("a3", ["UNMET"] * 5),
        ("b1", ["MET"] * 5),
    )

    projected = agg.grade_case(row, _selected_cases(1)[0], _RUBRIC, judge_passes=5)
    final = agg.aggregate(
        json.dumps([row]),
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    assert projected.model_dump() == final["cases"][0]
    assert agg.score_cases([projected]).score == final["score"]


def test_partial_judge_evidence_scores_with_explicit_verdict_coverage() -> None:
    evidence = {
        "a1": [_verdict("a1", "MET", sequence=n) for n in range(1, 6)],
        "a2": [_verdict("a2", "MET", sequence=n) for n in range(1, 6)],
        "a3": [
            *(_verdict("a3", "UNMET", sequence=n) for n in range(1, 5)),
            _invalid("a3", "invalid_json", sequence=5),
        ],
        # b1's fifth pass is absent: a transport/model call failed before binding.
        "b1": [_verdict("b1", "MET", sequence=n) for n in range(1, 5)],
    }

    result = agg.aggregate(
        json.dumps([_case_row_from_evidence(1, evidence)]),
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    case = result["cases"][0]

    assert result["score"] == 1.0
    assert result["coverage"] == 1.0
    assert result["metrics"]["verdict_coverage"] == 0.9
    assert case["grade"]["score"] == 1.0
    assert case["failures"] == []
    assert {
        name: case["grade"]["metrics"][name]
        for name in (
            "coverage",
            "verdicts_expected",
            "verdicts_accepted",
            "verdicts_rejected",
            "verdicts_invalid",
            "verdicts_missing",
        )
    } == {
        "coverage": 0.9,
        "verdicts_expected": 20,
        "verdicts_accepted": 18,
        "verdicts_rejected": 2,
        "verdicts_invalid": 1,
        "verdicts_missing": 1,
    }


def test_reference_coverage_floor_accepts_exactly_ninety_five_percent() -> None:
    """The paper-compatible floor tolerates one rejected verdict out of twenty."""
    evidence = {
        "a1": [
            *(_verdict("a1", "MET", sequence=n) for n in range(1, 5)),
            _invalid("a1", "invalid_json", sequence=5),
        ],
        "a2": [_verdict("a2", "MET", sequence=n) for n in range(1, 6)],
        "a3": [_verdict("a3", "UNMET", sequence=n) for n in range(1, 6)],
        "b1": [_verdict("b1", "MET", sequence=n) for n in range(1, 6)],
    }

    result = agg.aggregate(
        json.dumps([_case_row_from_evidence(1, evidence)]),
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    assert result["score"] == 1.0
    assert result["coverage"] == 1.0
    assert result["metrics"]["verdict_coverage"] == 0.95
    assert result["cases"][0]["failures"] == []


# --- the whole reduction ---------------------------------------------------------


def test_aggregate_scores_the_official_nested_payload() -> None:
    rows = json.dumps(
        [
            _case_row(
                1,
                ("a1", ["MET"] * 5),
                ("a2", ["MET"] * 5),
                ("a3", ["UNMET"] * 5),
                ("b1", ["MET"] * 5),
            ),
            _case_row(
                2,
                ("a1", ["MET"] * 5),
                ("a2", ["UNMET"] * 5),
                ("a3", ["UNMET"] * 5),
                ("b1", ["UNMET"] * 5),
            ),
        ]
    )
    result = agg.aggregate(
        rows,
        rubrics={1: _RUBRIC, 2: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1, 2),
    )

    assert result["case_count"] == 2
    assert result["benchmark_revision"] == DRACO_REVISION
    assert result["score"] == 0.75  # case 1 → 1.0 · case 2 → 0.5
    assert "normalized_score" not in result["metrics"]
    assert [c["case_id"] for c in result["cases"]] == [1, 2]
    assert result["metrics"]["n_runs"] == 5
    assert result["failures"] == []


def test_extra_judge_pass_aborts_as_protocol_corruption() -> None:
    row = _case_row(
        1,
        ("a1", ["MET"] * 6),
        ("a2", ["MET"] * 5),
        ("a3", ["UNMET"] * 5),
        ("b1", ["MET"] * 5),
    )

    with pytest.raises(agg.AggregateError, match="more than 5 Judge Evidence"):
        agg.aggregate(
            json.dumps([row]),
            rubrics={1: _RUBRIC},
            benchmark_id="draco",
            selected_cases=_selected_cases(1),
        )


def test_a_case_id_missing_from_evidence_aborts() -> None:
    """A scoreable verdict must carry the identity bound by the Engine after judging."""
    row = _case_row(
        1,
        ("a1", ["MET"] * 5),
        ("a2", ["MET"] * 5),
        ("a3", ["UNMET"] * 5),
        ("b1", ["MET"] * 5),
    )
    grading = row["grading"]
    assert isinstance(grading, list) and isinstance(grading[0], dict)
    evidence = grading[0]["evidence"]
    assert isinstance(evidence, list)
    first_verdict = evidence[0]
    assert isinstance(first_verdict, dict)
    del first_verdict["case_id"]

    with pytest.raises(agg.AggregateError, match="invalid DRACO Judge Evidence"):
        agg.aggregate(
            json.dumps([row]),
            rubrics={1: _RUBRIC},
            benchmark_id="draco",
            selected_cases=_selected_cases(1),
        )


def test_a_malformed_row_with_no_verdicts_aborts() -> None:
    rows = json.dumps(
        [
            _case_row(
                1,
                ("a1", ["MET"] * 5),
                ("a2", ["MET"] * 5),
                ("a3", ["UNMET"] * 5),
                ("b1", ["MET"] * 5),
            ),
            "judge refused",
        ]
    )
    with pytest.raises(agg.AggregateError, match="position 1"):
        agg.aggregate(
            rows,
            rubrics={1: _RUBRIC, 2: _RUBRIC},
            benchmark_id="draco",
            selected_cases=_selected_cases(1, 2),
        )


def test_no_rows_at_all_retains_every_selected_case_as_failed() -> None:
    result = agg.aggregate(
        "[]",
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    assert result["score"] is None
    assert result["cases"][0]["failures"][0]["code"] == "case_result_missing"


def test_all_failed_rows_retain_the_collected_execution_error() -> None:
    rows = json.dumps(
        [
            {
                "error": {
                    "kind": "ResolutionError",
                    "message": "aigateway returned neither answer content nor tool calls",
                }
            }
        ]
    )

    result = agg.aggregate(
        rows,
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    assert result["score"] is None
    assert result["cases"][0]["failures"][0]["message"] == (
        "aigateway returned neither answer content nor tool calls"
    )


def test_a_valid_evaluated_case_may_legitimately_score_zero() -> None:
    rows = json.dumps(
        [
            _case_row(
                1,
                ("a1", ["UNMET"] * 5),
                ("a2", ["UNMET"] * 5),
                ("a3", ["MET"] * 5),
                ("b1", ["UNMET"] * 5),
            )
        ]
    )

    result = agg.aggregate(
        rows,
        rubrics={1: _RUBRIC},
        benchmark_id="draco",
        selected_cases=_selected_cases(1),
    )

    assert result["case_count"] == 1
    assert result["score"] == 0.0
    assert result["failures"] == []


def test_a_malformed_top_level_payload_raises() -> None:
    with pytest.raises(agg.AggregateError):
        agg.aggregate("not json", rubrics={}, benchmark_id="draco", selected_cases=[])

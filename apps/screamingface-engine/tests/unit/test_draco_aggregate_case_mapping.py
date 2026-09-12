"""The case -> rubric mapping must be PROVABLE, never guessed from row position.

FEATURE: a DRACO run scores each case's answer against that case's rubric.
STORY: as a researcher I need a published score to be the score of the cases I ran, not of
whichever rubrics happened to sit at the same offsets.

The Engine binds `case_id` onto every verdict after the Judge call. Aggregation requires that
identity on every scoreable row and never infers it from row position. That remains correct for
full, sliced, reordered, and partially failed iterations, while keeping orchestration identity
out of the Judge's control.

INVARIANT: every scoreable row carries exactly one unique Engine-bound `case_id`. An invalid
or mismatched row is retained as an ungraded Case; the reducer never guesses or publishes a
partial Candidate score.
"""

from __future__ import annotations

import json

import pytest

from screamingface_engine.benchmarks.case_execution import case_execution_payload
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.draco import grade as agg
from screamingface_engine.benchmarks.draco.case_evaluation import (
    bind_case_evaluation,
    bind_criterion_evaluation,
)
from screamingface_engine.benchmarks.draco.records import CASE_SCHEMA, CHECK_SCHEMA
from screamingface_engine.benchmarks.draco.verdict import SCHEMA as VERDICT_SCHEMA


def _rubric(criterion: str) -> dict[str, object]:
    return {
        "sections": [
            {"id": "Factual Accuracy", "criteria": [{"id": criterion, "weight": 1}]},
        ]
    }


# Four declared cases, each with its OWN criterion id — so a mis-pairing cannot score by luck.
_RUBRICS: dict[int, dict[str, object]] = {n: _rubric(f"c{n}") for n in (1, 2, 3, 4)}


def _selected(*case_ids: int) -> list[dict[str, object]]:
    return [{"id": case_id, "input": f"Question {case_id}"} for case_id in case_ids]


def _row(criterion: str, *, case: int | None = None, status: str = "MET") -> object:
    raw_output = json.dumps({"explanation": "fixture verdict", "criterion_status": status})
    verdicts = [
        {
            "schema": VERDICT_SCHEMA,
            "criterion_id": criterion,
            "sequence": sequence,
            "producer_type": "model",
            "producer_id": "fixture-judge",
            "criterion_status": status,
            "valid": True,
            "explanation": "fixture verdict",
            "raw_output": raw_output,
        }
        for sequence in range(1, 6)
    ]
    if case is not None:
        for verdict in verdicts:
            verdict["case_id"] = case
        case_record = {
            "schema": CASE_SCHEMA,
            "case_id": case,
            "status": "completed",
            "input": f"Question {case}",
            "answer": f"Answer {case}",
            "output": f"Answer {case}",
            "finish_reason": "stop",
            "refusal": None,
            "execution": None,
            "metadata": {},
        }
        check_record = {
            "schema": CHECK_SCHEMA,
            "case_id": case,
            "criterion_id": criterion,
            "criterion_type": "positive",
            "requirement": f"Requirement {criterion}",
        }
        return case_execution_payload(
            case,
            encode_candidate_invocation(f"Answer {case}", "stop", None),
            [
                bind_case_evaluation(
                    case,
                    [bind_criterion_evaluation(case, case_record, check_record, verdicts)],
                )
            ],
        )
    return {"not": "a DRACO Case Evaluation", "verdicts": verdicts}


# --- the guard ------------------------------------------------------------------


def test_a_short_row_set_without_bound_case_evaluations_aborts() -> None:
    """The `;iteration.slice=10:20` shape — two rows against four declared cases."""
    rows = json.dumps([_row("c3"), _row("c4")])

    with pytest.raises(agg.AggregateError, match="position 0"):
        agg.aggregate(
            rows,
            rubrics=_RUBRICS,
            benchmark_id="draco",
            selected_cases=_selected(3, 4),
        )


def test_the_error_names_the_invalid_case_evaluation() -> None:
    rows = json.dumps([_row("c3"), _row("c4")])

    with pytest.raises(agg.AggregateError, match="position 0"):
        agg.aggregate(
            rows,
            rubrics=_RUBRICS,
            benchmark_id="draco",
            selected_cases=_selected(3, 4),
        )


def test_a_mixed_row_set_aborts_on_the_unverifiable_row() -> None:
    """One echoed id does not vouch for a sibling that has none."""
    rows = json.dumps([_row("c1", case=1), _row("c2")])

    with pytest.raises(agg.AggregateError, match="position 1"):
        agg.aggregate(
            rows,
            rubrics=_RUBRICS,
            benchmark_id="draco",
            selected_cases=_selected(1, 2),
        )


# --- what the guard must NOT catch ----------------------------------------------


def test_a_short_row_set_with_bound_case_ids_scores_normally() -> None:
    """INVARIANT: the guard targets an unprovable MAPPING, not a small run.

    This is the shape a sliced run should take, and it must keep working — otherwise the fix
    would forbid `;iteration.slice` outright rather than making it honest.
    """
    rows = json.dumps([_row("c3", case=3), _row("c4", case=4)])

    result = agg.aggregate(
        rows,
        rubrics=_RUBRICS,
        benchmark_id="draco",
        selected_cases=_selected(3, 4),
    )

    assert result["case_count"] == 2
    assert [c["case_id"] for c in result["cases"]] == [3, 4]
    assert result["score"] == 1.0  # each row met ITS OWN case's criterion


def test_rows_must_exactly_match_the_bound_selection() -> None:
    """INVARIANT: a lost row cannot masquerade as an intentionally shorter prefix."""
    rows = json.dumps([_row("c1", case=1)])

    result = agg.aggregate(
        rows,
        rubrics=_RUBRICS,
        benchmark_id="draco",
        selected_cases=_selected(1, 2),
    )

    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert result["cases"][1]["failures"][0]["code"] == "case_result_missing"


def test_a_full_row_set_without_case_evaluations_aborts() -> None:
    """Completeness does not make row position a durable Case identity."""
    rows = json.dumps([_row(f"c{n}") for n in (1, 2, 3, 4)])

    with pytest.raises(agg.AggregateError, match="position 0"):
        agg.aggregate(
            rows,
            rubrics=_RUBRICS,
            benchmark_id="draco",
            selected_cases=_selected(1, 2, 3, 4),
        )


def test_no_rows_at_all_fails_after_the_mapping_guard() -> None:
    """An empty payload has no mapping error, but it still cannot produce a valid result."""
    with pytest.raises(agg.AggregateError, match="selected Case sequence"):
        agg.aggregate("[]", rubrics=_RUBRICS, benchmark_id="draco", selected_cases=[])


def test_rows_with_malformed_verdicts_abort() -> None:
    failed = _row("c2", case=2)
    assert isinstance(failed, dict)
    grading = failed["grading"]
    assert isinstance(grading, list)
    case_evaluation = grading[0]
    assert isinstance(case_evaluation, dict)
    evidence = case_evaluation["evidence"]
    assert isinstance(evidence, list)
    assert isinstance(evidence[0], dict)
    evidence[0]["schema"] = "not-a-verdict"
    rows = json.dumps([_row("c1", case=1), failed])

    with pytest.raises(agg.AggregateError, match="invalid DRACO Judge Evidence"):
        agg.aggregate(
            rows,
            rubrics=_RUBRICS,
            benchmark_id="draco",
            selected_cases=_selected(1, 2),
        )

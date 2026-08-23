"""Bind HealthBench's existing grading and scoring semantics to one selected run."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from screamingface_engine.benchmarks.case_execution_contract import case_execution_outcome
from screamingface_engine.benchmarks.definition import (
    BenchmarkEvaluation,
    BoundEvaluation,
    IndexedCaseResult,
)

if TYPE_CHECKING:
    from screamingface_engine.benchmarks.healthbench.exam import Exam


def evaluation(exam: Exam, asset_bundle_id: str) -> BenchmarkEvaluation:
    """Create one HealthBench board's immutable Evaluation adapter."""

    def bind(assets_root: Path, selected_case_count: int) -> BoundEvaluation:
        from screamingface_engine.benchmarks.healthbench import aggregate as scoring

        root = assets_root / asset_bundle_id
        case_ids = exam.case_ids[:selected_case_count]
        selected = scoring.selected_cases(root, case_ids)
        cases = {int(case.case_id): (index, case) for index, case in enumerate(selected)}
        rubric_points: dict[int, list[int] | None] = {}

        def grade_case(raw: str) -> IndexedCaseResult:
            case_id = int(case_execution_outcome(raw).case_id)
            selected_index, selected_case = cases[case_id]
            if case_id not in rubric_points:
                rubric_points[case_id] = scoring.load_rubric_points(root, case_id)
            points = rubric_points[case_id]
            return IndexedCaseResult(
                selected_index=selected_index,
                result=scoring.grade_case(raw, selected_case, points),
            )

        return BoundEvaluation(
            grade_case=grade_case,
            score_cases=partial(scoring.score_cases, exam.mean),
        )

    return BenchmarkEvaluation(aggregate_route=exam.routes.aggregate, bind=bind)


__all__ = ["evaluation"]

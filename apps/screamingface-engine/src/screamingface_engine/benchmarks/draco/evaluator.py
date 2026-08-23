"""Bind DRACO's existing grading and scoring semantics to one selected run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from screamingface_engine.benchmarks.case_execution_contract import case_execution_outcome
from screamingface_engine.benchmarks.definition import (
    BenchmarkEvaluation,
    BoundEvaluation,
    IndexedCaseResult,
)
from screamingface_engine.benchmarks.draco import assets as protocol_assets

if TYPE_CHECKING:
    from screamingface_engine.benchmarks.draco.exam import DracoExam


def evaluation(exam: DracoExam, asset_bundle_id: str) -> BenchmarkEvaluation:
    """Create one DRACO board's immutable Evaluation adapter."""

    def bind(assets_root: Path, selected_case_count: int) -> BoundEvaluation:
        from screamingface_engine.benchmarks.draco import aggregate as scoring

        root = assets_root / asset_bundle_id
        selection = _selected_cases(root, selected_case_count)
        cases = {cast(int, case["id"]): (index, case) for index, case in enumerate(selection)}
        rubrics: dict[int, dict[str, object]] = {}

        def grade_case(raw: str) -> IndexedCaseResult:
            case_id = int(case_execution_outcome(raw).case_id)
            selected_index, selected_case = cases[case_id]
            rubric = rubrics.get(case_id)
            if rubric is None:
                rubric = protocol_assets.load_rubric(root / "rubrics", case_id)
                rubrics[case_id] = rubric
            return IndexedCaseResult(
                selected_index=selected_index,
                result=scoring.grade_case(
                    raw,
                    selected_case,
                    rubric,
                    judge_passes=exam.judge_passes,
                ),
            )

        return BoundEvaluation(grade_case=grade_case, score_cases=scoring.score_cases)

    return BenchmarkEvaluation(aggregate_route=exam.routes.aggregate, bind=bind)


def _selected_cases(root: Path, selected_case_count: int) -> list[dict[str, object]]:
    decoded = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    if not isinstance(decoded, list) or not all(isinstance(case, dict) for case in decoded):
        raise ValueError("DRACO cases must be a JSON array of objects")
    if (
        isinstance(selected_case_count, bool)
        or not isinstance(selected_case_count, int)
        or selected_case_count < 1
        or selected_case_count > len(decoded)
    ):
        raise ValueError(f"selected_case_count must be between 1 and {len(decoded)}")
    return [dict(case) for case in decoded[:selected_case_count]]


__all__ = ["evaluation"]

"""Bind DRACO's existing grading and scoring semantics to one selected run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from screamingface_engine.benchmarks.case_execution import case_execution_outcome
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
        selected_cases, rubrics = _assets(root)
        selection = selected_cases[:selected_case_count]
        cases = {
            cast(int, case["id"]): (index, case, rubrics[cast(int, case["id"])])
            for index, case in enumerate(selection)
        }

        def grade_case(raw: str) -> IndexedCaseResult:
            case_id = int(case_execution_outcome(raw).case_id)
            selected_index, selected_case, rubric = cases[case_id]
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


def _assets(root: Path) -> tuple[list[dict[str, object]], dict[int, dict[str, Any]]]:
    decoded = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    if not isinstance(decoded, list) or not all(isinstance(case, dict) for case in decoded):
        raise ValueError("DRACO cases must be a JSON array of objects")
    selected = [dict(case) for case in decoded]
    rubrics = protocol_assets.validate_protocol_assets(root, selected)
    return selected, rubrics


__all__ = ["evaluation"]

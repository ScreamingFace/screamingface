"""Bind IFEval's existing grading and scoring semantics to one selected run."""

from __future__ import annotations

from pathlib import Path

from screamingface_engine.benchmarks.case_execution import case_execution_outcome
from screamingface_engine.benchmarks.definition import (
    BenchmarkEvaluation,
    BoundEvaluation,
    IndexedCaseResult,
)


def evaluation(aggregate_route: str, asset_bundle_id: str) -> BenchmarkEvaluation:
    """Create the immutable IFEval Evaluation adapter without loading private assets."""

    def bind(assets_root: Path, selected_case_count: int) -> BoundEvaluation:
        # Lazy import avoids the aggregate -> definition revision import cycle while keeping
        # resource discovery free of verifier and filesystem work.
        from screamingface_engine.benchmarks.ifeval import aggregate as scoring

        root = assets_root / asset_bundle_id
        specs = scoring.load_specs(root / "instructions")
        case_order = scoring.load_case_order(root)
        selected = scoring.selected_cases(specs, case_order, selected_case_count)
        cases = {
            int(case.case_id): (index, case, specs[int(case.case_id)])
            for index, case in enumerate(selected)
        }

        def grade_case(raw: str) -> IndexedCaseResult:
            case_id = int(case_execution_outcome(raw).case_id)
            selected_index, selected_case, spec = cases[case_id]
            return IndexedCaseResult(
                selected_index=selected_index,
                result=scoring.grade_case(raw, selected_case, spec),
            )

        return BoundEvaluation(grade_case=grade_case, score_cases=scoring.score_cases)

    return BenchmarkEvaluation(aggregate_route=aggregate_route, bind=bind)


__all__ = ["evaluation"]

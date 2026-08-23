"""Bind IFEval's existing grading and scoring semantics to one selected run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.aggregation import SelectedCase
from screamingface_engine.benchmarks.case_execution_contract import case_execution_outcome
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
        case_order = scoring.load_case_order(root)
        selected_ids = scoring.selected_case_ids(case_order, selected_case_count)
        positions = {case_id: index for index, case_id in enumerate(selected_ids)}
        loaded: dict[int, tuple[SelectedCase, dict[str, Any]]] = {}

        def grade_case(raw: str) -> IndexedCaseResult:
            case_id = int(case_execution_outcome(raw).case_id)
            selected_index = positions[case_id]
            cached = loaded.get(case_id)
            if cached is None:
                spec = scoring.load_spec(root / "instructions", case_id)
                selected_case = scoring.selected_cases({case_id: spec}, [case_id], 1)[0]
                cached = (selected_case, spec)
                loaded[case_id] = cached
            selected_case, spec = cached
            return IndexedCaseResult(
                selected_index=selected_index,
                result=scoring.grade_case(raw, selected_case, spec),
            )

        return BoundEvaluation(grade_case=grade_case, score_cases=scoring.score_cases)

    return BenchmarkEvaluation(aggregate_route=aggregate_route, bind=bind)


__all__ = ["evaluation"]

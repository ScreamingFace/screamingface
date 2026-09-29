"""Bind IFEval's checker evidence and scoring rules to shared grade transport."""

from pathlib import Path

from screamingface_engine.benchmarks.ifeval import grade
from screamingface_engine.benchmarks.ifeval.definition import BENCHMARK_ID, REVISION
from screamingface_engine.benchmarks.spine.incremental import Scoring


def scoring(root: Path, selected_case_count: int) -> Scoring:
    specs = grade.load_specs(root / "instructions")
    selected = grade.selected_cases(specs, grade.load_case_order(root), selected_case_count)
    return Scoring(
        path=grade.scored_path(specs),
        benchmark_id=BENCHMARK_ID,
        revision=REVISION,
        selected=selected,
        material=specs.get,
        scorer=grade.score_cases,
    )

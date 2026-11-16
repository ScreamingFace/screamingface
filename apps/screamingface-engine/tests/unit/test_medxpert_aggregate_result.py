"""MedXpertQA's reducer gives the aggregate endpoint the CandidateResult model (OME-1835).

FEATURE: memory fix 3, unit 1. The batch route streams a model into the run spool, so the
MedXpertQA reducer returns the model; ``aggregate`` keeps its dict for older callers.
INVARIANT defended: ``aggregate_result(...).as_payload()`` equals ``aggregate(...)``.
"""

from __future__ import annotations

from pathlib import Path

from test_medxpert_aggregate import _root, _rows

from screamingface_engine.benchmarks.contract import CandidateResult
from screamingface_engine.benchmarks.medxpert import aggregate as reducing
from screamingface_engine.benchmarks.medxpert import runtime
from screamingface_engine.benchmarks.medxpert.definition import BENCHMARK_ID, REVISION


def _bundle(tmp_path: Path, name: str) -> Path:
    # WHY one folder per bundle: _root makes its answers folder and fails on reuse.
    folder = tmp_path / name
    folder.mkdir()
    return _root(folder)


def test_the_model_is_the_same_report_as_the_dict(tmp_path: Path) -> None:
    raw = _rows((1, "C"), (2, "B"))

    result = reducing.aggregate_result(
        raw,
        _bundle(tmp_path, "a"),
        benchmark_id=BENCHMARK_ID,
        benchmark_revision=REVISION,
        case_ids=(1, 2),
    )
    report = reducing.aggregate(
        raw,
        _bundle(tmp_path, "b"),
        benchmark_id=BENCHMARK_ID,
        benchmark_revision=REVISION,
        case_ids=(1, 2),
    )

    assert isinstance(result, CandidateResult)
    assert result.as_payload() == report


def test_the_served_benchmark_reduces_to_the_model() -> None:
    assert runtime.BENCHMARK.reduce is reducing.aggregate_result

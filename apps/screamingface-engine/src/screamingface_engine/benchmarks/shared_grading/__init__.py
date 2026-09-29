"""Shared grading — the grading machinery every benchmark uses (OME-1024).

Modules here are extracted one ticket at a time from the per-benchmark aggregate files.
AIDEV-NOTE: never edit `benchmarks/aggregation.py` or `benchmarks/contract.py` from a
shared-grading extraction — the live-progress branches (OME-932, OME-934) own those files;
shared grading grows beside them as new modules only.
"""

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (
    BenchmarkAggregation,
    CaseGradeOutcome,
    GradeCase,
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.case_grades import (
    CaseGradeIndex,
    CaseGradeReader,
    read_selected_cases,
)
from screamingface_engine.benchmarks.shared_grading.mean_scorer import mean_scorer
from screamingface_engine.benchmarks.shared_grading.payloads import CasePayload, TextPayload
from screamingface_engine.benchmarks.shared_grading.rubric import rubric_grade_case
from screamingface_engine.benchmarks.shared_grading.serving import (
    BenchmarkRoutes,
    ServedBenchmark,
    benchmark_preflight,
    benchmark_routes,
    candidate_record,
    compute_benchmark_revision,
    install_benchmark,
)
from screamingface_engine.benchmarks.shared_grading.verdict import (
    Verdict,
    VerdictShape,
    parse_verdict,
)

__all__ = [
    "BenchmarkRoutes",
    "CaseGradeOutcome",
    "CasePayload",
    "mean_scorer",
    "GradeCase",
    "GradeRequest",
    "CaseGradeIndex",
    "CaseGradeReader",
    "BenchmarkAggregation",
    "ServedBenchmark",
    "TextPayload",
    "Verdict",
    "VerdictShape",
    "benchmark_preflight",
    "benchmark_routes",
    "candidate_record",
    "compute_benchmark_revision",
    "install_benchmark",
    "parse_verdict",
    "read_selected_cases",
    "rubric_grade_case",
]

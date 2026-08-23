"""Public definition and installation surface for Engine-owned Benchmarks."""

from screamingface_engine.benchmarks.definition import (
    CANDIDATE_REF,
    Benchmark,
    BenchmarkEvaluation,
    BenchmarkInstaller,
    BoundEvaluation,
    IndexedCaseResult,
    candidate,
    link_candidate,
)
from screamingface_engine.benchmarks.registry import (
    BENCHMARK_ASSETS_ENV,
    DEFAULT_BENCHMARK_ASSETS_ROOT,
    EMPTY_BENCHMARKS,
    BenchmarkRegistry,
    assets_root,
)

__all__ = [
    "BENCHMARK_ASSETS_ENV",
    "CANDIDATE_REF",
    "DEFAULT_BENCHMARK_ASSETS_ROOT",
    "Benchmark",
    "BenchmarkEvaluation",
    "BenchmarkInstaller",
    "BenchmarkRegistry",
    "BoundEvaluation",
    "EMPTY_BENCHMARKS",
    "IndexedCaseResult",
    "assets_root",
    "candidate",
    "link_candidate",
]

"""Public definition and installation surface for Engine-owned Benchmarks.

Adding a benchmark: see ``apps/screamingface-engine/docs/adding-a-benchmark-manually.md``
(hand-authored) or ``docs/adding-an-imported-benchmark.md`` (imported from inspect_evals).
"""

from screamingface_engine.benchmarks.definition import (
    CANDIDATE_REF,
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkInstaller,
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
    "BenchmarkDeclaration",
    "BenchmarkInstaller",
    "BenchmarkRegistry",
    "EMPTY_BENCHMARKS",
    "assets_root",
    "candidate",
    "link_candidate",
]

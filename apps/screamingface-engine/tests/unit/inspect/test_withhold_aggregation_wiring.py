"""OME-1642 U2: an imported row's declared failure policy reaches its shared-grading binding.

INVARIANT: `ImportedBenchmark.aggregation()` takes the policy from the row's declaration, so the
denominator the reducer scores over is the one the catalogue publishes. Pyright proves the
keyword is passed; only this test proves the VALUE is the row's.

Runs only with the `inspect` extra installed (assembling a row reads inspect-ai's version); the
plain gate run skips it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.benchmarks.definition import FailurePolicy  # noqa: E402
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402


@pytest.mark.parametrize(
    ("key", "policy"),
    [
        ("gsm8k", "withhold"),
        ("squad", "withhold"),
        ("xstest_safe", "coverage_declare"),
        ("draco", "coverage_declare"),
    ],
)
def test_the_aggregation_takes_the_rows_declared_policy(key: str, policy: FailurePolicy) -> None:
    benchmark = imported_benchmark(key)

    assert benchmark.benchmark.declaration.failure_policy == policy
    assert benchmark.aggregation().failure_policy == policy

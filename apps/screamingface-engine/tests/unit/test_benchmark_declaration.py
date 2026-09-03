"""OME-1039: the declared grading contract every Benchmark must register.

INVARIANT: `failure_policy` and `interaction` are explicit, required, per-benchmark
parameters — never a spine-level default. A policy nobody can see from the manifest is a
policy nobody can approve, and a default that flips silently changes published-score
semantics for every board at once.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    candidate,
)

DECLARATION = BenchmarkDeclaration(
    failure_policy="coverage-declare",
    interaction="single_shot",
)


def _benchmark_values() -> dict[str, object]:
    return {
        "id": "example-smoke",
        "title": "Example Smoke",
        "description": "One non-comparable structural probe.",
        "revision": "example-smoke-v1",
        "case_count": 3,
        "build": lambda selected: candidate(
            f"Explain why the sky looks blue. Selected cases: {selected}.",
            web_search=False,
        ),
        "declaration": DECLARATION,
    }


def test_benchmark_without_a_declaration_cannot_be_constructed() -> None:
    # STORY: as an auditor who must approve eval code before it runs, a benchmark that
    # never declared its failure policy must fail registration before any paid request.
    values = _benchmark_values()
    del values["declaration"]
    with pytest.raises(TypeError):
        Benchmark(**values)  # type: ignore[arg-type]


def test_declaration_refuses_an_unknown_failure_policy_by_name() -> None:
    with pytest.raises(ValueError, match="failure_policy"):
        BenchmarkDeclaration(
            failure_policy="drop-silently",  # type: ignore[arg-type]
            interaction="single_shot",
        )


def test_declaration_refuses_an_unknown_interaction_by_name() -> None:
    # WHY: multi_turn arrives later as a new declared value, never as a silent
    # acceptance — the spine refuses the unknown value before any paid request.
    with pytest.raises(ValueError, match="interaction"):
        BenchmarkDeclaration(
            failure_policy="withhold",
            interaction="multi_turn",  # type: ignore[arg-type]
        )


def test_declaration_requires_both_fields_with_no_defaults() -> None:
    # INVARIANT: no value on this record may fall back to a default — a defaulted
    # policy is exactly the hidden-default failure OME-1039 exists to prevent.
    with pytest.raises(TypeError):
        BenchmarkDeclaration(failure_policy="withhold")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        BenchmarkDeclaration(interaction="single_shot")  # type: ignore[call-arg]


def test_wrong_declaration_type_is_refused() -> None:
    values = _benchmark_values()
    values["declaration"] = {"failure_policy": "withhold", "interaction": "single_shot"}
    with pytest.raises(TypeError):
        Benchmark(**values)  # type: ignore[arg-type]


def test_catalog_entry_names_both_declared_values() -> None:
    entry = Benchmark(**_benchmark_values()).catalog_entry()  # type: ignore[arg-type]
    assert entry["failure_policy"] == "coverage-declare"
    assert entry["interaction"] == "single_shot"


def test_resource_names_both_declared_values() -> None:
    resource = Benchmark(**_benchmark_values()).resource(limit=1)  # type: ignore[arg-type]
    assert resource["failure_policy"] == "coverage-declare"
    assert resource["interaction"] == "single_shot"


def test_every_builtin_board_declares_its_actual_policy() -> None:
    # INVARIANT: the declaration tells the truth about the code. Every board reduces
    # through the shared `finalize_candidate_result`, which scores exactly the gradeable
    # subset and publishes coverage — coverage-declare behavior. A board may only declare
    # `withhold` once its aggregate actually withholds.
    benchmarks = list(BUILTIN_BENCHMARKS)
    assert len(benchmarks) == 6
    for benchmark in benchmarks:
        assert benchmark.declaration.failure_policy == "coverage-declare", benchmark.id
        assert benchmark.declaration.interaction == "single_shot", benchmark.id

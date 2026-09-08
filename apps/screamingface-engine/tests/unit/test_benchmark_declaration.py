"""OME-1039: the declared grading contract every Benchmark must register.

INVARIANT: `failure_policy` and `interaction` are explicit, required, per-benchmark
parameters — never a spine-level default. A policy nobody can see from the manifest is a
policy nobody can approve, and a default that flips silently changes published-score
semantics for every board at once.
"""

from __future__ import annotations

import importlib

import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.definition import (
    Benchmark,
    BenchmarkDeclaration,
    candidate,
)

DECLARATION = BenchmarkDeclaration(
    failure_policy="coverage_declare",
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
    # WHY: a new interaction shape arrives as a DECLARED value, never as a silent acceptance —
    # the contract refuses the unknown one before any paid request.
    #
    # AIDEV-NOTE: this test used to name `multi_turn` as its unknown value. OME-1126 (MedXpertQA)
    # added it as a real value: that board invokes the Candidate twice per Case (reason, then
    # commit against a bare trigger), so it could not register while `single_shot` was the only
    # option. The guard itself is unchanged in strength — it still proves an unknown value is
    # refused by name. Agentic/tool-environment shapes remain unknown until a board needs them.
    with pytest.raises(ValueError, match="interaction"):
        BenchmarkDeclaration(
            failure_policy="withhold",
            interaction="agentic_tool_use",  # type: ignore[arg-type]
        )


def test_declaration_accepts_the_declared_multi_turn_shape() -> None:
    # The positive half of the guard above: a value only becomes acceptable by being declared.
    declaration = BenchmarkDeclaration(failure_policy="coverage_declare", interaction="multi_turn")
    assert declaration.as_block()["interaction"] == "multi_turn"


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
    assert entry["failure_policy"] == "coverage_declare"
    assert entry["interaction"] == "single_shot"


def test_resource_names_both_declared_values() -> None:
    resource = Benchmark(**_benchmark_values()).resource(limit=1)  # type: ignore[arg-type]
    assert resource["failure_policy"] == "coverage_declare"
    assert resource["interaction"] == "single_shot"


def test_every_builtin_board_declares_its_actual_policy() -> None:
    # INVARIANT: the declaration tells the truth about the code. Every board reduces through the
    # shared `finalize_candidate_result`, which scores exactly the gradeable subset and publishes
    # coverage — coverage_declare behavior. A board may only declare `withhold` once its aggregate
    # actually withholds, and may only declare an interaction it actually performs.
    #
    # AIDEV-NOTE: an explicit per-board table rather than a blanket assertion. A new board must
    # add its row deliberately, and a board that CHANGES its declaration trips here — which a
    # loop over "all single_shot" could not catch once a second shape existed (OME-1126).
    expected = {
        "draco": ("coverage_declare", "single_shot"),
        "draco-3pass": ("coverage_declare", "single_shot"),
        "gdpval-text": ("coverage_declare", "single_shot"),
        "healthbench-professional": ("coverage_declare", "single_shot"),
        "healthbench-worst30": ("coverage_declare", "single_shot"),
        "ifeval": ("coverage_declare", "single_shot"),
        # MedXpertQA invokes the Candidate twice per Case: turn 1 reasons, turn 2 commits against
        # a bare trigger. Its ungradeable Cases still go to the shared finalizer, hence
        # coverage_declare.
        "medxpert": ("coverage_declare", "multi_turn"),
    }
    actual = {
        benchmark.id: (
            benchmark.declaration.failure_policy,
            benchmark.declaration.interaction,
        )
        for benchmark in BUILTIN_BENCHMARKS
    }
    assert actual == expected


def test_each_board_aggregate_reduces_through_the_shared_finalizer() -> None:
    # WHY: the coverage_declare pins above are only TRUE while every board funnels its
    # cases through the shared finalizer (score over the gradeable subset + published
    # coverage). This asserts the mechanism, not just the literal: a board that stops
    # importing the shared finalize_candidate_result (hand-rolling its own reduction,
    # or shadowing the name) trips here and must revisit its declaration.
    # AIDEV-NOTE: import identity, not call-path proof — the e2e goldens' coverage rung
    # proves the call path; full closure lands when the spine itself consumes
    # failure_policy (`OME-1097`+) and the policy stops being prose entirely.
    from screamingface_engine.benchmarks import aggregation

    for family in ("draco", "gdpval", "healthbench", "ifeval"):
        module = importlib.import_module(f"screamingface_engine.benchmarks.{family}.aggregate")
        assert module.finalize_candidate_result is aggregation.finalize_candidate_result, (
            f"{family} no longer reduces through the shared finalizer"
        )

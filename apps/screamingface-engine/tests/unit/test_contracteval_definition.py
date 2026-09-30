"""The ContractEval benchmark — identity, revision inputs, and the expression contract.

INVARIANT under test: prompt bytes are benchmark identity. Grading spends no judge tokens, so the
prompt is the only thing standing between a model and its score — and on this benchmark it is
unusually load-bearing, because "Do not rephrase or summarize" is what makes verbatim
containment a fair test at all.

WHY this file exists (review of PR #984): every sibling benchmark ships one, and
`compute_revision`'s three injectable kwargs exist ONLY so a test like this can prove each
input is inside the hash. Nobody passed them, so hash membership, route addressing and "the
expression parses at all" were unpinned.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contracteval import definition as benchmark
from url4 import render
from url4.core.grammar import parse


def test_the_benchmark_serves_the_whole_pinned_split() -> None:
    assert benchmark.CASE_COUNT == 4182
    assert benchmark.CONTRACTEVAL.case_count == 4182


def test_the_benchmark_is_registered() -> None:
    assert benchmark.CONTRACTEVAL in tuple(BUILTIN_BENCHMARKS)


def test_every_route_carries_the_revision() -> None:
    """INVARIANT: an expression addressed to an old revision must never resolve against a
    changed benchmark, which is only true while every route carries the revision."""

    for route in (
        benchmark.CASES_ROUTE,
        benchmark.CHECK_ROUTE,
        benchmark.CASE_GRADE_ROUTE,
        benchmark.AGGREGATE_ROUTE,
    ):
        assert route.startswith(f"/benchmarks/{benchmark.BENCHMARK_ID}/{benchmark.REVISION}/")


def test_the_expression_parses() -> None:
    parse(render(benchmark.CONTRACTEVAL.build(5)))


def test_the_expression_invokes_the_candidate_exactly_once() -> None:
    """INVARIANT: single_shot, as declared. A second invocation would double the cost of every
    run and contradict the benchmark's own `BenchmarkDeclaration`."""

    rendered = render(benchmark.CONTRACTEVAL.build(5))

    assert rendered.count("/benchmarks/candidate") == 1


def test_the_expression_uses_the_object_shaped_case_evaluation_payload() -> None:
    """REGRESSION (OME-1126): the array-shaped `case_grade_endpoint` decodes with
    `json_array` and rejects this payload. The failure mode was every Case dying at grading
    AFTER inference was paid for, so the shape belongs in a test and not only in a comment."""

    rendered = render(benchmark.CONTRACTEVAL.build(5))

    assert "case-evaluation({attempt_1: '$record'})" in rendered


def test_the_selected_case_count_reaches_the_iteration() -> None:
    """A `limit=N` run must select N cases before admitting candidate calls."""

    assert f"{benchmark.CASES_ROUTE}()!'5'" in render(benchmark.CONTRACTEVAL.build(5))
    assert f"{benchmark.CASES_ROUTE}()!'50'" in render(benchmark.CONTRACTEVAL.build(50))


def test_changing_the_prompt_bytes_changes_the_revision() -> None:
    baseline = benchmark.compute_revision()

    assert benchmark.compute_revision(system_prompt="different") != baseline
    assert benchmark.compute_revision(user_template="different") != baseline


def test_changing_the_dataset_revision_changes_the_revision() -> None:
    assert benchmark.compute_revision(dataset_revision="deadbeef") != benchmark.compute_revision()


def test_the_declaration_matches_what_the_benchmark_actually_does() -> None:
    """One Candidate call per Case, and ungradeable Cases go to the shared finalizer."""

    assert benchmark.CONTRACTEVAL.declaration.interaction == "single_shot"
    assert benchmark.CONTRACTEVAL.declaration.failure_policy == "coverage_declare"
    # OME-1257: specialized extraction with headroom, no expert-frontier stakes.
    assert benchmark.CONTRACTEVAL.declaration.difficulty == "medium"


def test_no_check_surface_is_advertised() -> None:
    """INVARIANT: the declaration is a promise the SDK trusts BEFORE spend. Advertising a
    surface without registering its handler lets a corrective-loop run pass the pre-spend
    gate, burn paid candidate turns, then die on a route `runtime.install` never serves."""

    assert benchmark.CONTRACTEVAL.check_surface is None

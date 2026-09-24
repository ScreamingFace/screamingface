"""The ContractEval board — identity, revision inputs, and the expression contract.

INVARIANT under test: prompt bytes are exam identity. Grading spends no judge tokens, so the
prompt is the only thing standing between a model and its score — and on this board it is
unusually load-bearing, because "Do not rephrase or summarize" is what makes verbatim
containment a fair test at all.

WHY this file exists (review of PR #984): every sibling board ships one, and
`compute_revision`'s three injectable kwargs exist ONLY so a test like this can prove each
input is inside the hash. Nobody passed them, so hash membership, route addressing and "the
expression parses at all" were unpinned.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.contracteval import definition as board
from url4 import render
from url4.core.grammar import parse


def test_the_board_serves_the_whole_pinned_split() -> None:
    assert board.CASE_COUNT == 4182
    assert board.CONTRACTEVAL.case_count == 4182


def test_the_board_is_registered() -> None:
    assert board.CONTRACTEVAL in tuple(BUILTIN_BENCHMARKS)


def test_every_route_carries_the_revision() -> None:
    """INVARIANT: an expression addressed to an old revision must never resolve against a
    changed exam, which is only true while every route carries the revision."""

    for route in (
        board.CASES_ROUTE,
        board.CHECK_ROUTE,
        board.CASE_EVALUATION_ROUTE,
        board.AGGREGATE_ROUTE,
    ):
        assert route.startswith(f"/benchmarks/{board.BENCHMARK_ID}/{board.REVISION}/")


def test_the_expression_parses() -> None:
    parse(render(board.CONTRACTEVAL.build(5)))


def test_the_expression_invokes_the_candidate_exactly_once() -> None:
    """INVARIANT: single_shot, as declared. A second invocation would double the cost of every
    run and contradict the board's own `BenchmarkDeclaration`."""

    rendered = render(board.CONTRACTEVAL.build(5))

    assert rendered.count("/benchmarks/candidate") == 1


def test_the_expression_uses_the_object_shaped_case_evaluation_payload() -> None:
    """REGRESSION (OME-1126): the array-shaped `case_evaluation_endpoint` decodes with
    `json_array` and rejects this payload. The failure mode was every Case dying at grading
    AFTER inference was paid for, so the shape belongs in a test and not only in a comment."""

    rendered = render(board.CONTRACTEVAL.build(5))

    assert "case-evaluation({attempt_1: '$record'})" in rendered


def test_the_selected_case_count_reaches_the_iteration() -> None:
    """A `limit=N` run must select N cases before admitting candidate calls."""

    assert f"{board.CASES_ROUTE}()!'5'" in render(board.CONTRACTEVAL.build(5))
    assert f"{board.CASES_ROUTE}()!'50'" in render(board.CONTRACTEVAL.build(50))


def test_changing_the_prompt_bytes_changes_the_revision() -> None:
    baseline = board.compute_revision()

    assert board.compute_revision(system_prompt="different") != baseline
    assert board.compute_revision(user_template="different") != baseline


def test_changing_the_dataset_revision_changes_the_revision() -> None:
    assert board.compute_revision(dataset_revision="deadbeef") != board.compute_revision()


def test_the_declaration_matches_what_the_board_actually_does() -> None:
    """One Candidate call per Case, and ungradeable Cases go to the shared finalizer."""

    assert board.CONTRACTEVAL.declaration.interaction == "single_shot"
    assert board.CONTRACTEVAL.declaration.failure_policy == "coverage_declare"
    # OME-1257: specialized extraction with headroom, no expert-frontier stakes.
    assert board.CONTRACTEVAL.declaration.difficulty == "medium"


def test_no_check_surface_is_advertised() -> None:
    """INVARIANT: the declaration is a promise the SDK trusts BEFORE spend. Advertising a
    surface without registering its handler lets a corrective-loop run pass the pre-spend
    gate, burn paid candidate turns, then die on a route `runtime.install` never serves."""

    assert board.CONTRACTEVAL.check_surface is None

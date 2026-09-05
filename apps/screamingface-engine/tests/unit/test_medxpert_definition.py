"""The MedXpertQA board — identity, revision inputs, and the two-turn expression contract.

INVARIANT under test: the exchange is TWO candidate invocations. Turn 1 reasons; turn 2 commits
against a bare trigger, which is what makes the committed letter come first and the official
first-match extraction correct. Collapsing this to one invocation is the 35-point regression.

INVARIANT under test: prompt bytes are exam identity. Grading spends no judge tokens, so the
prompt is the only thing standing between a model and its score.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.medxpert import definition as board
from url4 import render
from url4.core.grammar import parse


def test_the_board_serves_the_whole_pinned_split() -> None:
    assert board.CASE_COUNT == 2450
    assert board.MEDXPERT.case_count == 2450


def test_the_board_is_registered() -> None:
    assert board.MEDXPERT in tuple(BUILTIN_BENCHMARKS)


def test_every_route_carries_the_revision() -> None:
    for route in (
        board.CASES_ROUTE,
        board.CHECK_ROUTE,
        board.CHECK_SURFACE_ROUTE,
        board.CASE_EVALUATION_ROUTE,
        board.AGGREGATE_ROUTE,
    ):
        assert route.startswith(f"/benchmarks/{board.BENCHMARK_ID}/{board.REVISION}/")


def test_the_expression_parses() -> None:
    parse(render(board.MEDXPERT.build(5)))


def test_the_expression_invokes_the_candidate_twice() -> None:
    # INVARIANT: reason, then commit. One invocation would mean a one-shot prompt with the
    # trigger appended — letter-LAST essays that the official parser misreads by 35 points.
    rendered = render(board.MEDXPERT.build(5))
    assert rendered.count("/benchmarks/candidate") == 2


def test_the_check_route_receives_both_turns() -> None:
    # D8: the shared candidate envelope has no field for reasoning, so the board's own check
    # envelope carries it. A letter with no reasoning is unauditable.
    rendered = render(board.MEDXPERT.build(5))
    assert "reasoning" in rendered
    assert board.CHECK_ROUTE in rendered


def test_changing_the_prompt_bytes_changes_the_revision() -> None:
    # A changed prompt is a changed exam — it must re-address every route.
    baseline = board.compute_revision()
    assert board.REVISION == baseline
    assert board.compute_revision(cot_template="Q: {question}\nA: think.") != baseline


def test_changing_the_trigger_changes_the_revision() -> None:
    assert board.compute_revision(trigger_template="So the answer is") != board.REVISION


def test_changing_the_dataset_revision_changes_the_revision() -> None:
    assert board.compute_revision(dataset_revision="0" * 40) != board.REVISION


def test_the_check_surface_is_free() -> None:
    # WHY: grading is pure string comparison. A paid disclosure here would be a lie, and the SDK
    # surfaces that cost to the user before any work starts.
    assert board.MEDXPERT.check_surface is not None
    assert board.MEDXPERT.check_surface.expected_check_cost == "free"


def test_the_description_names_the_fusion_deviation() -> None:
    # Spec D2: two-turn is applied at the candidate boundary, not per fusion member. A reader
    # comparing our fusion numbers to a per-member implementation must be able to see why they
    # differ without leaving the catalogue.
    text = board.MEDXPERT.description.casefold()
    assert "two-turn" in text
    assert "candidate boundary" in text

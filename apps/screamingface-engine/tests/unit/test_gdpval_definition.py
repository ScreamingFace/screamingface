"""The GDPval text board — identity, revision inputs, and the expression contract.

INVARIANT under test: everything a Candidate's score depends on is folded into the revision, and
every route carries it. An exam that changed what it asks, how it filters, or who judges — while
keeping its addresses — would silently re-grade published submissions.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.gdpval.definition import (
    GDPVAL_TEXT,
    TEXT_CASE_COUNT,
    TEXT_EXAM,
)
from screamingface_engine.benchmarks.gdpval.exam import exam_revision
from screamingface_engine.benchmarks.gdpval.pins import JUDGE_MODEL
from screamingface_engine.benchmarks.gdpval.subset import TEXT_SUBSET_TASK_IDS, subset_sha
from url4 import render
from url4.core.grammar import parse

_BASE = {
    "protocol_revision": "text-per-item-v1",
    "selection_sha": subset_sha(),
    "scoring": "rubric-mean-v1",
}


def test_the_board_serves_the_frozen_selection() -> None:
    assert TEXT_CASE_COUNT == len(TEXT_SUBSET_TASK_IDS) == 102
    assert GDPVAL_TEXT.case_count == 102
    assert TEXT_EXAM.case_ids == tuple(range(1, 103))


def test_every_route_carries_the_revision() -> None:
    revision = TEXT_EXAM.revision
    routes = TEXT_EXAM.routes
    for route in (
        routes.cases,
        routes.tasks,
        routes.verdict,
        routes.rubric_evaluation,
        routes.case_evaluation,
        routes.aggregate,
        routes.check_surface,
    ):
        assert route.startswith(f"/benchmarks/gdpval-text/{revision}/"), route


def test_the_published_revision_matches_its_inputs() -> None:
    assert TEXT_EXAM.revision == exam_revision(**_BASE)
    assert GDPVAL_TEXT.revision == TEXT_EXAM.revision


def test_changing_the_selection_changes_the_revision() -> None:
    assert exam_revision(**{**_BASE, "selection_sha": "different"}) != TEXT_EXAM.revision


def test_changing_the_scoring_rule_changes_the_revision() -> None:
    # INVARIANT: the metric's identity is part of the exam's. Two boards over one answer key that
    # total it differently must not share an address.
    assert exam_revision(**{**_BASE, "scoring": "other-mean-v1"}) != TEXT_EXAM.revision


def test_changing_the_protocol_changes_the_revision() -> None:
    assert exam_revision(**{**_BASE, "protocol_revision": "v2"}) != TEXT_EXAM.revision


def test_the_expression_parses_and_addresses_this_revision() -> None:
    rendered = render(GDPVAL_TEXT.build(5))
    parse(rendered)
    assert TEXT_EXAM.revision in rendered


def test_the_expression_nests_the_judge_for_retry() -> None:
    # INVARIANT: a malformed reply is a SUCCESSFUL model call, so retry has to sit on the verdict
    # that parses it, not on the judge. Losing this nesting silently disables every retry.
    rendered = render(GDPVAL_TEXT.build(5))
    assert ";retry=" in rendered
    assert JUDGE_MODEL.removeprefix("/") in rendered


def test_a_partial_run_slices_without_changing_the_address() -> None:
    five = render(GDPVAL_TEXT.build(5))
    full = render(GDPVAL_TEXT.build(TEXT_CASE_COUNT))
    assert TEXT_EXAM.revision in five and TEXT_EXAM.revision in full
    assert five != full


def test_the_check_surface_declares_a_paid_cost() -> None:
    # WHY: every check is a judge call over the case rubric — the loop's cost is real and the
    # client must be told before any paid work starts.
    assert GDPVAL_TEXT.check_surface is not None
    assert GDPVAL_TEXT.check_surface.expected_check_cost == "paid"


def test_the_description_discloses_both_deviations() -> None:
    # INVARIANT: a reader of this score must be able to see, without leaving the catalogue, that
    # it is neither GDPval's metric nor graded on a formatted document.
    text = GDPVAL_TEXT.description.casefold()
    assert "not comparable" in text
    assert "plain text" in text
    assert "pairwise" in text

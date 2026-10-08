"""The GDPval text benchmark — identity, revision inputs, and the expression contract.

INVARIANT under test: everything a Candidate's score depends on is folded into the revision, and
every route carries it. A benchmark that changed what it asks, how it filters, or who judges — while
keeping its addresses — would silently re-grade published submissions.
"""

from __future__ import annotations

from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.gdpval.definition import (
    GDPVAL_TEXT,
    TEXT_CASE_COUNT,
    TEXT_VARIANT,
)
from screamingface_engine.benchmarks.gdpval.revision_inputs import JUDGE_MODEL
from screamingface_engine.benchmarks.gdpval.subset import TEXT_SUBSET_TASK_IDS, subset_sha
from screamingface_engine.benchmarks.gdpval.variant import variant_revision
from url4 import render
from url4.core.grammar import parse

_BASE = {
    "protocol_revision": "text-per-item-v1",
    "selection_sha": subset_sha(),
    "scoring": "rubric-mean-v1",
}


def test_the_text_benchmark_is_registered_under_its_id() -> None:
    """INVARIANT: this benchmark is PUBLIC — dropping it is a leaderboard regression.

    The shared cross-benchmark tests iterate the registry, so a benchmark deleted from
    `builtins.py` stops being iterated and they all still pass (OME-1095). Membership is
    pinned here, in the benchmark's own module, where a new benchmark costs one line.
    """

    assert BUILTIN_BENCHMARKS.get("gdpval-text") is GDPVAL_TEXT


def test_the_text_benchmark_links_the_openai_gdpval_dataset() -> None:
    # WHY the literal: the leaderboard renders this as a clickable target for the public, and
    # the shared suite can only check that benchmarks sharing a bundle agree on it.
    assert GDPVAL_TEXT.dataset_url == "https://huggingface.co/datasets/openai/gdpval"


def test_the_benchmark_serves_the_frozen_selection() -> None:
    assert TEXT_CASE_COUNT == len(TEXT_SUBSET_TASK_IDS) == 102
    assert GDPVAL_TEXT.case_count == 102
    assert TEXT_VARIANT.case_ids == tuple(range(1, 103))


def test_every_route_carries_the_revision() -> None:
    revision = TEXT_VARIANT.revision
    routes = TEXT_VARIANT.routes
    for route in (
        routes.cases,
        routes.judge_requests,
        routes.verdict,
        routes.rubric_evaluation,
        routes.case_evaluation,
        routes.aggregate,
        routes.check_surface,
    ):
        assert route.startswith(f"/benchmarks/gdpval-text/{revision}/"), route


def test_the_published_revision_matches_its_inputs() -> None:
    assert TEXT_VARIANT.revision == variant_revision(**_BASE)
    assert GDPVAL_TEXT.revision == TEXT_VARIANT.revision


def test_changing_the_selection_changes_the_revision() -> None:
    assert variant_revision(**{**_BASE, "selection_sha": "different"}) != TEXT_VARIANT.revision


def test_changing_the_scoring_rule_changes_the_revision() -> None:
    # INVARIANT: the metric's identity is part of the benchmark's. Two benchmarks over one answer
    # key that total it differently must not share an address.
    assert variant_revision(**{**_BASE, "scoring": "other-mean-v1"}) != TEXT_VARIANT.revision


def test_changing_the_protocol_changes_the_revision() -> None:
    assert variant_revision(**{**_BASE, "protocol_revision": "v2"}) != TEXT_VARIANT.revision


def test_the_expression_parses_and_addresses_this_revision() -> None:
    rendered = render(GDPVAL_TEXT.build(5))
    parse(rendered)
    assert TEXT_VARIANT.revision in rendered


def test_the_expression_nests_the_judge_for_retry() -> None:
    # INVARIANT: a malformed reply is a SUCCESSFUL model call, so retry has to sit on the verdict
    # that parses it, not on the judge. Losing this nesting silently disables every retry.
    rendered = render(GDPVAL_TEXT.build(5))
    assert ";retry=" in rendered
    assert JUDGE_MODEL.removeprefix("/") in rendered


def test_the_judge_route_throttles_thinking_and_doubles_the_verdict_budget() -> None:
    # INVARIANT: the judge is a reasoning model and its thinking tokens count against
    # max_tokens — unthrottled, it can spend the whole budget thinking and return a blank
    # `length` turn (OME-993 saw exactly this on DRACO). GDPval pins low effort AND, unlike
    # DRACO (whose 4096 reproduces the paper), owner-approved 8192 headroom: there is no
    # paper parametrization to reproduce here, so the bound prefers verdicts over cap errors.
    rendered = render(GDPVAL_TEXT.build(5))
    assert "reasoning_effort=low" in rendered
    assert "max_tokens=8192" in rendered


def test_a_partial_run_slices_without_changing_the_address() -> None:
    five = render(GDPVAL_TEXT.build(5))
    full = render(GDPVAL_TEXT.build(TEXT_CASE_COUNT))
    assert TEXT_VARIANT.revision in five and TEXT_VARIANT.revision in full
    assert five != full


# AIDEV-NOTE (OME-1513): the name is frozen by the test-change rule; what it checks now is that
# the offer is OFF — Draft Feedback is a per-Benchmark owner decision (owner rule 2026-10-07),
# and today only IFEval carries one. The check-surface route is still served, not advertised.
def test_the_check_surface_declares_a_paid_cost() -> None:
    assert GDPVAL_TEXT.check_surface is None
    assert "check_surface" not in GDPVAL_TEXT.resource(limit=1)


def test_the_description_discloses_both_deviations() -> None:
    # INVARIANT: a reader of this score must be able to see, without leaving the catalogue, that
    # it is neither GDPval's metric nor graded on a formatted document.
    text = GDPVAL_TEXT.description.casefold()
    assert "not comparable" in text
    assert "plain text" in text
    assert "pairwise" in text

"""Unit tests for compute_pareto_frontier (OME-923 part A).

Pure function, no DB — entries are constructed directly.

FEATURE: OME-923 — mark the submissions with the best score for the money.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from decimal import Decimal
from decimal import Decimal as D

from scoreboard.scores.pareto import compute_pareto_frontier
from scoreboard.scores.schemas import LeaderboardEntry


def _entry(
    *,
    spec_id: str,
    score: float,
    run_cost_usd: Decimal | None,
    benchmark_revision: str | None = None,
) -> LeaderboardEntry:
    """Only score, cost, spec_id and revision matter here; the rest is inert filler."""
    return LeaderboardEntry(
        spec_id=spec_id,
        benchmark_revision=benchmark_revision,
        score=score,
        total_questions=10,
        ran_with_providers=["huggingface"],
        submitted_at=datetime(2026, 8, 29, tzinfo=UTC),
        submitted_by="tester@example.com",
        verified_by_screamingface=False,
        url4_expression=f"url4://benchmark/{spec_id}",
        run_cost_usd=run_cost_usd,
    )


def test_no_entries_yields_an_empty_frontier() -> None:
    assert compute_pareto_frontier([]) == frozenset()


def test_a_lone_priced_entry_is_on_the_frontier() -> None:
    entries = [_entry(spec_id="solo", score=0.5, run_cost_usd=Decimal("1.00"))]
    assert compute_pareto_frontier(entries) == {("solo", None)}


def test_a_strictly_dominated_entry_is_excluded() -> None:
    """Worse score AND higher cost — beaten on both axes, so it cannot be best value."""
    entries = [
        _entry(spec_id="better", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="worse", score=0.50, run_cost_usd=Decimal("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {("better", None)}


def test_a_genuine_tradeoff_puts_both_on_the_frontier() -> None:
    """Cheaper-but-worse and dearer-but-better: neither dominates, both are defensible."""
    entries = [
        _entry(spec_id="cheap", score=0.50, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="accurate", score=0.90, run_cost_usd=Decimal("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {("cheap", None), ("accurate", None)}


def test_equal_score_the_cheaper_entry_wins() -> None:
    """INVARIANT (D7): standard Pareto dominance. Paying 9x for the same score is
    strictly worse value, so it is NOT a best-score-for-the-money winner — even
    though nobody outscored it."""
    entries = [
        _entry(spec_id="alice", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="bob", score=0.90, run_cost_usd=Decimal("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {("alice", None)}


def test_equal_cost_the_higher_scoring_entry_wins() -> None:
    entries = [
        _entry(spec_id="higher", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="lower", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {("higher", None)}


def test_an_exact_tie_on_both_axes_qualifies_both() -> None:
    """The ticket's "ties both qualify": identical on both axes, so neither
    dominates the other and both hold the claim."""
    entries = [
        _entry(spec_id="twin-a", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="twin-b", score=0.90, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {("twin-a", None), ("twin-b", None)}


def test_an_unpriced_entry_is_excluded_even_with_the_top_score() -> None:
    """INVARIANT (D6): a null cost means "not reported", never zero. Read as zero it
    would dominate every priced row and win the board outright on an unknown."""
    entries = [
        _entry(spec_id="unpriced", score=0.99, run_cost_usd=None),
        _entry(spec_id="priced", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {("priced", None)}


def test_an_unpriced_entry_never_excludes_a_priced_one() -> None:
    """The unpriced row must not participate as a dominator either — excluding it
    from the OUTPUT while still letting it beat others would be the same bug."""
    entries = [
        _entry(spec_id="unpriced-cheap-looking", score=0.99, run_cost_usd=None),
        _entry(spec_id="dear", score=0.60, run_cost_usd=Decimal("9.00")),
        _entry(spec_id="cheap", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {("dear", None), ("cheap", None)}


def test_a_board_with_no_cost_data_yields_an_empty_frontier() -> None:
    """Today's real board: every row null. Must return empty, not raise — the
    ticket's "a board with no cost data renders without error and marks nothing"."""
    entries = [
        _entry(spec_id="a", score=0.90, run_cost_usd=None),
        _entry(spec_id="b", score=0.50, run_cost_usd=None),
    ]
    assert compute_pareto_frontier(entries) == frozenset()


def test_a_zero_cost_is_a_real_value_and_can_win() -> None:
    """INVARIANT: 0 is "this run genuinely cost nothing" (a fully cache-served run),
    which is distinct from null and is the strongest possible cost."""
    entries = [
        _entry(spec_id="free", score=0.50, run_cost_usd=Decimal("0")),
        _entry(spec_id="paid", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {("free", None)}


# ---- revision cohorts (found in review of PR #778) ---------------------------------


def test_one_spec_on_two_revisions_is_judged_only_against_its_own_revision() -> None:
    """The regression from review. A benchmark with no REGISTERED revision filters nothing
    and ranks one row per (spec_id, benchmark_revision), so a spec appears twice. Keyed on
    spec_id alone, the rev-2 row inherited the mark its own spec earned on rev-1 — even
    though a rev-2 peer beats it on BOTH axes."""
    entries = [
        _entry(spec_id="fusion-a", benchmark_revision="rev-1", score=0.90, run_cost_usd=D("1.00")),
        _entry(spec_id="fusion-a", benchmark_revision="rev-2", score=0.50, run_cost_usd=D("9.00")),
        _entry(spec_id="rival", benchmark_revision="rev-2", score=0.80, run_cost_usd=D("2.00")),
    ]
    frontier = compute_pareto_frontier(entries)
    assert ("fusion-a", "rev-1") in frontier
    assert ("rival", "rev-2") in frontier
    assert ("fusion-a", "rev-2") not in frontier


def test_rows_never_dominate_across_revisions() -> None:
    """INVARIANT: revisions are not comparable (OME-775), so a cheap high scorer on one
    revision must not knock out a dear low scorer on another."""
    entries = [
        _entry(spec_id="on-old", benchmark_revision="rev-1", score=0.95, run_cost_usd=D("0.10")),
        _entry(spec_id="on-new", benchmark_revision="rev-2", score=0.20, run_cost_usd=D("9.99")),
    ]
    assert compute_pareto_frontier(entries) == {("on-old", "rev-1"), ("on-new", "rev-2")}


def test_a_lone_priced_row_on_a_revision_is_that_revisions_frontier() -> None:
    """AIDEV-NOTE: a deliberate consequence of per-cohort comparison, pinned so it is a
    decision and not a surprise. With one priced row on a revision, that row IS the best
    value available on it, so it carries a mark — even while another revision holds a run
    that is both better and cheaper. The two were never comparable (OME-775), which is the
    whole reason the cohorts exist. A reader needs `benchmark_revision`, which the board
    already exposes, to tell the two rows apart."""
    entries = [
        _entry(spec_id="alone", benchmark_revision="rev-2", score=0.10, run_cost_usd=D("99.00")),
        _entry(spec_id="better", benchmark_revision="rev-1", score=0.99, run_cost_usd=D("0.01")),
    ]
    assert compute_pareto_frontier(entries) == {("alone", "rev-2"), ("better", "rev-1")}


def test_each_revision_computes_its_own_frontier() -> None:
    """Domination still applies fully *inside* a cohort."""
    entries = [
        _entry(spec_id="best-old", benchmark_revision="rev-1", score=0.90, run_cost_usd=D("1.00")),
        _entry(spec_id="poor-old", benchmark_revision="rev-1", score=0.40, run_cost_usd=D("5.00")),
        _entry(spec_id="best-new", benchmark_revision="rev-2", score=0.70, run_cost_usd=D("2.00")),
        _entry(spec_id="poor-new", benchmark_revision="rev-2", score=0.30, run_cost_usd=D("8.00")),
    ]
    assert compute_pareto_frontier(entries) == {("best-old", "rev-1"), ("best-new", "rev-2")}


def test_a_registered_revision_board_is_one_cohort() -> None:
    """The common case: the benchmark declares a revision, so the query filters to it and
    every row shares it. Behaviour must be identical to comparing the whole board."""
    entries = [
        _entry(spec_id="winner", benchmark_revision="rev-9", score=0.90, run_cost_usd=D("1.00")),
        _entry(spec_id="loser", benchmark_revision="rev-9", score=0.50, run_cost_usd=D("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {("winner", "rev-9")}


def test_a_null_revision_is_its_own_cohort_not_a_wildcard() -> None:
    """Legacy rows predating the column carry NULL. NULL is a cohort like any other — it
    must not merge with, or compare against, rows that name a revision."""
    entries = [
        _entry(spec_id="legacy", benchmark_revision=None, score=0.30, run_cost_usd=D("9.00")),
        _entry(spec_id="modern", benchmark_revision="rev-1", score=0.95, run_cost_usd=D("0.10")),
    ]
    assert compute_pareto_frontier(entries) == {("legacy", None), ("modern", "rev-1")}


# ---- the sweep must be the pairwise definition, only faster (review, 2026-08-31) ----


def _oracle(entries: list[LeaderboardEntry]) -> frozenset[tuple[str, str | None]]:
    """The ticket's definition, written the obvious slow way.

    Deliberately pairwise and deliberately unoptimised: this is the specification the sweep in
    `pareto.py` has to agree with, so it must not share any of its cleverness.
    """
    priced = [
        (e.spec_id, e.benchmark_revision, e.score, e.run_cost_usd)
        for e in entries
        if e.run_cost_usd is not None
    ]
    return frozenset(
        (spec, rev)
        for spec, rev, score, cost in priced
        if not any(
            other_rev == rev
            and other_score >= score
            and other_cost <= cost
            and (other_score > score or other_cost < cost)
            for _, other_rev, other_score, other_cost in priced
        )
    )


def test_the_sweep_agrees_with_the_pairwise_definition() -> None:
    """Randomised equivalence check over a deliberately tiny value space.

    Scores and costs are drawn from a handful of values so exact ties on one axis, on both
    axes, and across revisions all occur constantly — ties are where a sweep is most likely to
    disagree with the pairwise rule, and where this ticket's "ties both qualify" lives.
    """
    rng = random.Random(20260831)
    scores = [0.10, 0.50, 0.50, 0.90]
    costs = ["0", "0.50", "1.00", "1.00", "9.00"]
    revisions: list[str | None] = ["rev-1", "rev-2", None]

    for trial in range(300):
        entries = [
            _entry(
                spec_id=f"spec-{index}",
                score=rng.choice(scores),
                # a third of rows unpriced, so exclusion is exercised on both sides
                run_cost_usd=None if rng.random() < 0.33 else D(rng.choice(costs)),
                benchmark_revision=rng.choice(revisions),
            )
            for index in range(rng.randint(0, 12))
        ]
        assert compute_pareto_frontier(entries) == _oracle(entries), (
            f"disagreement on trial {trial}"
        )


def test_a_large_board_does_not_take_quadratic_time() -> None:
    """INVARIANT: the frontier is O(n log n) in the cohort size.

    The route reads the board UNBOUNDED so the frontier cannot depend on `top`, and `spec_id` is
    client-supplied — so an attacker chooses n (found in review, 2026-08-31).

    WHY a perfect trade-off curve and not random data: a pairwise scan uses `any()`, which
    short-circuits the moment a dominator is found. Over random points nearly every row is
    dominated immediately and the scan behaves close to linearly — an earlier version of this
    test used random costs, and a reintroduced pairwise scan PASSED it in 0.4s. The quadratic
    case is a board where nothing dominates anything, so every row is compared against every
    other and nothing can short-circuit. Each row here costs strictly more and scores strictly
    higher than the last, so all of them qualify.

    WHY 12,000 and not a rounder number: measured on this machine, a pairwise scan over a
    trade-off curve takes 0.41s at n=3,000 and 2.82s at n=8,000 — both under a bound loose
    enough not to flake. At 12,000 it takes 6.4s while the sweep takes 0.008s and building the
    rows takes 0.03s, so the 2s bound has roughly fifty times headroom on the passing side and
    still fails a reintroduced pairwise scan by a factor of three.
    """
    size = 12_000
    entries = [
        _entry(
            spec_id=f"spec-{index}",
            score=index / size,
            run_cost_usd=D(str(index)),
        )
        for index in range(size)
    ]

    started = time.perf_counter()
    frontier = compute_pareto_frontier(entries)
    elapsed = time.perf_counter() - started

    # Every row is a genuine trade-off, so every row qualifies.
    assert len(frontier) == size
    assert elapsed < 2.0, f"took {elapsed:.2f}s — has the frontier gone quadratic again?"

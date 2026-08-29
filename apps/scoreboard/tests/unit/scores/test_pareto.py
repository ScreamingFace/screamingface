"""Unit tests for compute_pareto_frontier (OME-923 part A).

Pure function, no DB — entries are constructed directly.

FEATURE: OME-923 — mark the submissions with the best score for the money.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from scoreboard.scores.pareto import compute_pareto_frontier
from scoreboard.scores.schemas import LeaderboardEntry


def _entry(
    *,
    spec_id: str,
    score: float,
    run_cost_usd: Decimal | None,
) -> LeaderboardEntry:
    """Only score, cost and spec_id matter here; everything else is inert filler."""
    return LeaderboardEntry(
        spec_id=spec_id,
        # None is honest: the frontier does not depend on which revision produced the row.
        benchmark_revision=None,
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
    assert compute_pareto_frontier(entries) == {"solo"}


def test_a_strictly_dominated_entry_is_excluded() -> None:
    """Worse score AND higher cost — beaten on both axes, so it cannot be best value."""
    entries = [
        _entry(spec_id="better", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="worse", score=0.50, run_cost_usd=Decimal("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {"better"}


def test_a_genuine_tradeoff_puts_both_on_the_frontier() -> None:
    """Cheaper-but-worse and dearer-but-better: neither dominates, both are defensible."""
    entries = [
        _entry(spec_id="cheap", score=0.50, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="accurate", score=0.90, run_cost_usd=Decimal("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {"cheap", "accurate"}


def test_equal_score_the_cheaper_entry_wins() -> None:
    """INVARIANT (D7): standard Pareto dominance. Paying 9x for the same score is
    strictly worse value, so it is NOT a best-score-for-the-money winner — even
    though nobody outscored it."""
    entries = [
        _entry(spec_id="alice", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="bob", score=0.90, run_cost_usd=Decimal("9.00")),
    ]
    assert compute_pareto_frontier(entries) == {"alice"}


def test_equal_cost_the_higher_scoring_entry_wins() -> None:
    entries = [
        _entry(spec_id="higher", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="lower", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {"higher"}


def test_an_exact_tie_on_both_axes_qualifies_both() -> None:
    """The ticket's "ties both qualify": identical on both axes, so neither
    dominates the other and both hold the claim."""
    entries = [
        _entry(spec_id="twin-a", score=0.90, run_cost_usd=Decimal("1.00")),
        _entry(spec_id="twin-b", score=0.90, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {"twin-a", "twin-b"}


def test_an_unpriced_entry_is_excluded_even_with_the_top_score() -> None:
    """INVARIANT (D6): a null cost means "not reported", never zero. Read as zero it
    would dominate every priced row and win the board outright on an unknown."""
    entries = [
        _entry(spec_id="unpriced", score=0.99, run_cost_usd=None),
        _entry(spec_id="priced", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {"priced"}


def test_an_unpriced_entry_never_excludes_a_priced_one() -> None:
    """The unpriced row must not participate as a dominator either — excluding it
    from the OUTPUT while still letting it beat others would be the same bug."""
    entries = [
        _entry(spec_id="unpriced-cheap-looking", score=0.99, run_cost_usd=None),
        _entry(spec_id="dear", score=0.60, run_cost_usd=Decimal("9.00")),
        _entry(spec_id="cheap", score=0.50, run_cost_usd=Decimal("1.00")),
    ]
    assert compute_pareto_frontier(entries) == {"dear", "cheap"}


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
    assert compute_pareto_frontier(entries) == {"free"}

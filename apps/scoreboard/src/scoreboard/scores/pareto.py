"""Pareto frontier computation (OME-923 part A).

Pure function, no I/O — takes already-fetched schemas so it's directly
unit-testable without a DB, mirroring `frontier.py`.

AIDEV-NOTE: deliberately NOT named `frontier` anything. `frontier.py`,
`compute_frontier`, `FrontierPoint` and `FrontierResult` are OME-323's open/closed
frontier — a different measure, on a different endpoint, that keeps its name and
meaning. Qualifying this one keeps a grep for either honest (OME-923).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .schemas import LeaderboardEntry

# A frontier member: the spec, qualified by the revision it was measured against.
# INVARIANT: the revision is part of the KEY, never dropped. `spec_id` alone is not unique
# on a board whose benchmark has no registered revision, and collapsing the two let a row
# beaten on BOTH axes inherit the mark its own spec earned on a different revision (found
# in review of PR #778).
ParetoKey = tuple[str, str | None]


def compute_pareto_frontier(entries: Sequence[LeaderboardEntry]) -> frozenset[ParetoKey]:
    """The `(spec_id, benchmark_revision)` pairs whose score-for-cost no comparable entry beats.

    FEATURE: OME-923 — "best score for the money" is a set, not a single row, so several
    participants can hold a defensible claim on the same board.

    INVARIANT: rows are compared **only within one `benchmark_revision`**. A board whose
    benchmark has no registered revision filters nothing and ranks one row per
    `(spec_id, benchmark_revision)`, so it can carry several mutually incomparable cohorts
    at once — and OME-775 exists precisely because numbers measured against different
    revisions are not comparable. Each cohort therefore gets its own frontier. Where the
    benchmark DOES declare a revision the query filters to it, leaving exactly one cohort,
    so this is identical to comparing the whole board.

    INVARIANT: an absent cost is excluded, never read as 0. Zero would dominate every priced
    row and hand the board to an unknown (OME-770 D8). The exclusion follows the missing
    VALUE, not the row: populate that cost later and the row joins the frontier on its own,
    with no backfill.

    AIDEV-NOTE: pass the **whole ranked set**, never a truncated page.
    `ScoreStore.leaderboard` orders by score alone and then applies `top_n`, so a row just
    past the cutoff can tie the boundary score at a lower cost and dominate a visible row it
    was never compared against. The frontier would then change with `top`, which is not a
    property a claim about money may have. The ticket says "no other submission on the same
    board", and the board is not the visible page (found in review of PR #778).

    AIDEV-NOTE: quadratic within a cohort, and deliberately so — a cohort is bounded by the
    board's distinct spec count, where this is a few thousand comparisons. A sort-based
    frontier scan would be faster and harder to read for no reachable benefit.
    """
    # WHY grouped first: one pass does the revision partitioning and the None-narrowing, and
    # drops unpriced rows from BOTH sides of the comparison — an unpriced row must neither
    # qualify nor dominate. Excluding it from only the output would still let an unknown cost
    # beat a real one.
    cohorts: dict[str | None, list[tuple[str, float, Decimal]]] = {}
    for entry in entries:
        cost = entry.run_cost_usd
        if cost is not None:
            cohorts.setdefault(entry.benchmark_revision, []).append(
                (entry.spec_id, entry.score, cost)
            )

    return frozenset(
        (spec_id, revision)
        for revision, priced in cohorts.items()
        for spec_id, score, cost in priced
        if not any(
            _dominates(other_score, other_cost, score, cost)
            for _, other_score, other_cost in priced
        )
    )


def _dominates(
    other_score: float,
    other_cost: Decimal,
    score: float,
    cost: Decimal,
) -> bool:
    """Standard Pareto dominance: at least as good on both axes, strictly better on one.

    WHY not the ticket's literal "no other has BOTH a higher score AND a lower cost":
    read strictly, that keeps a row scoring the same at nine times the price, because
    nobody outscored it — indefensible on a board claiming best value (owner decision,
    2026-08-29).

    INVARIANT: nothing dominates itself — equal on both axes fails the strictly-better
    clause — so an exact tie leaves both rows on the frontier.
    """
    return (
        other_score >= score and other_cost <= cost and (other_score > score or other_cost < cost)
    )

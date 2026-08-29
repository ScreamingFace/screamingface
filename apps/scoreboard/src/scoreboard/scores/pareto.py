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


def compute_pareto_frontier(entries: Sequence[LeaderboardEntry]) -> frozenset[str]:
    """The `spec_id`s whose score-for-cost no other entry beats.

    FEATURE: OME-923 — "best score for the money" is a set, not a single row, so
    several participants can hold a defensible claim on the same board.

    INVARIANT: one row per `spec_id`. Callers pass the RANKED board
    (`ScoreStore.leaderboard`), which collapses to best-per-spec. Do NOT pass
    `ScoreStore.list_owned_entries` — it deliberately does not collapse, so a
    repeated `spec_id` would mark rows that are not themselves on the frontier.

    INVARIANT: an absent cost is excluded, never read as 0. Zero would dominate
    every priced row and hand the board to an unknown (OME-770 D8). The exclusion
    follows the missing VALUE, not the row: populate that cost later and the row
    joins the frontier on its own, with no backfill.

    AIDEV-NOTE: quadratic, and deliberately left so — the board is capped at
    `top_n` (50), where this is a few thousand comparisons. A sort-based frontier
    scan would be faster and harder to read for no reachable benefit.
    """
    # WHY the tuple: narrowing `run_cost_usd` once here keeps the comparison free of
    # None-checks, and drops unpriced rows from BOTH sides of it — an unpriced row
    # must neither qualify nor dominate. Excluding it from only the output would
    # still let an unknown cost beat a real one.
    priced: list[tuple[str, float, Decimal]] = []
    for entry in entries:
        cost = entry.run_cost_usd
        if cost is not None:
            priced.append((entry.spec_id, entry.score, cost))

    return frozenset(
        spec_id
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

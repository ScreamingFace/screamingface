"""Open/closed frontier computation (OME-323, spec §5/§6).

Pure function, no I/O — takes already-fetched schemas so it's directly
unit-testable without a DB.
"""

from __future__ import annotations

from scoreboard.classification.openness import classify_baseline, classify_score

from .schemas import BaselineSchema, FrontierPoint, FrontierResult, ScoreSchema


def _current_split(
    scores: list[ScoreSchema], baselines: list[BaselineSchema]
) -> tuple[int, int, float]:
    """`open_count`/`closed_count`/`open_share` over ALL rows, Scores and Baselines
    together — the "how much of the frontier is open right now" number."""
    openness_calls = [classify_score(score) for score in scores]
    openness_calls += [classify_baseline(baseline) for baseline in baselines]
    open_count = sum(1 for openness in openness_calls if openness == "open")
    closed_count = len(openness_calls) - open_count
    total = open_count + closed_count
    open_share = open_count / total if total else 0.0
    return open_count, closed_count, open_share


def _compute_trend(scores: list[ScoreSchema]) -> tuple[FrontierPoint | None, list[FrontierPoint]]:
    """Walks Score rows ONLY, ordered by `submitted_at`. A Baseline's `imported_at`
    isn't a trustworthy real-world timestamp, so a Baseline never enters this walk
    at all — not merely "excluded from the printed list". The holder advances only
    on a strict score improvement — an exact tie leaves the existing holder in
    place (spec §6's tie-breaking resolution).
    """
    trend: list[FrontierPoint] = []
    current: FrontierPoint | None = None
    for score in sorted(scores, key=lambda s: s.submitted_at):
        if current is not None and score.score <= current.score:
            continue
        current = FrontierPoint(
            at=score.submitted_at,
            score=score.score,
            openness=classify_score(score),
            holder="score",
            label=score.spec_id,
        )
        trend.append(current)
    return current, trend


def _comparable(scores: list[ScoreSchema], registered_case_count: int | None) -> list[ScoreSchema]:
    """Drop runs that covered fewer cases than the benchmark defines (OME-1056).

    INVARIANT: the same rule the RANKING applies, applied here too. It lived only in
    `_build_leaderboard_query`, so a one-case run scoring 1.0 was hidden from the table while
    this frontier still published it — on the same page, from the same benchmark. A partial run
    is advantaged rather than merely admitted, because fewer cases makes a perfect score easier.

    WHY it matters more here than in the ranking: `_compute_trend` advances the holder only on a
    STRICT improvement, so a partial 1.0 becomes `current` and no complete run — 0.99, anything
    short of a tie-break — can ever displace it. The table's version of this bug is a wrong row
    ordering; this one is permanent.

    `None` means the board has no registered count, so nothing is comparable-or-not and every row
    stands, exactly as before this change.
    """
    if registered_case_count is None:
        return scores
    return [score for score in scores if score.total_questions >= registered_case_count]


def compute_frontier(
    scores: list[ScoreSchema],
    baselines: list[BaselineSchema],
    registered_case_count: int | None = None,
) -> FrontierResult:
    """Two independent passes (spec §6's baseline-timing resolution — deliberately
    NOT one merged computation): the current open/closed split over all rows
    (`_current_split`), and the trend over Score rows only (`_compute_trend`).

    Both passes see only comparable runs — see `_comparable`.

    AIDEV-NOTE: `registered_case_count` defaults to None, meaning "rank everything" — the weaker
    of the two signatures, chosen deliberately. Required is safer and is what
    `_build_leaderboard_query` does, but seven prior tests call this function and rule 5 makes
    editing them an owner decision a keyword default does not justify. The realistic regression is
    someone editing the route, not a second caller appearing, and
    `test_the_frontier_route_passes_the_registered_case_count` pins that. If a second production
    caller does appear, make this required and take the seven-site approval then (OME-1056).
    """
    scores = _comparable(scores, registered_case_count)
    open_count, closed_count, open_share = _current_split(scores, baselines)
    current, trend = _compute_trend(scores)

    return FrontierResult(
        open_count=open_count,
        closed_count=closed_count,
        open_share=open_share,
        current=current,
        trend=trend,
    )

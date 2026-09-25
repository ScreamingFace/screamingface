"""The open-share statistic's prior invariants, re-expressed on the frontier basis (OME-1145).

REWRITTEN under an approved Confidence-Gate exception (owner, 2026-09-25; D-N 2026-09-10 for the
baseline test). These nine tests pinned OME-323's all-rows split and score-holder trend, which
D-L replaced. Each keeps its original name's intent, restated on the new contract, and none is
weaker than what it replaces:

| was | now |
| -- | -- |
| empty board, no holder | empty frontier: null share (D-S), no trend |
| single score holds | a single priced entry is the frontier and counts |
| baseline counts in the split | baselines cannot enter at all: no such input exists (D-N) |
| later-but-lower not in the trend | a dominated entry neither counts nor adds a point |
| exact tie keeps the holder | an exact tie on BOTH axes puts both on the frontier |
| strict improvement moves the holder | a change in share adds a trend point |
| override changes the holder | the override decides the entry (D-Q4) |
| partial run cannot hold | the comparable-rows read drops it (OME-1056), now at the store |
| no registered count ranks all | the same read keeps every row when no count is declared |
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scoreboard.scores.frontier import (
    FrontierMember,
    HistoryRow,
    compute_frontier_openness,
    replay_frontier,
)
from scoreboard.scores.models import Score
from scoreboard.scores.pareto import ParetoEntry
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

T0 = datetime(2026, 1, 1, tzinfo=UTC)
OPEN = ("openrouter/deepseek/deepseek-v4-pro",)
CLOSED = ("openrouter/openai/gpt-5.5",)


def _row(spec_id: str, score: float, cost: str, day: int) -> HistoryRow:
    return HistoryRow(spec_id, spec_id, score, Decimal(cost), T0 + timedelta(days=day))


def _run(rows: list[HistoryRow], models: dict[str, tuple[str, ...]], override=None):
    # `current` is the best-per-spec projection, as `leaderboard_pareto_inputs` returns it.
    best: dict[str, HistoryRow] = {}
    for row in rows:
        if row.spec_id not in best or row.score >= best[row.spec_id].score:
            best[row.spec_id] = row
    current = [
        ParetoEntry(r.source_id, r.spec_id, None, r.score, r.run_cost_usd) for r in best.values()
    ]
    members = {
        source_id: FrontierMember(source_id, routes, (override or {}).get(source_id))
        for source_id, routes in models.items()
    }
    return compute_frontier_openness(current, replay_frontier(rows), members, pinned=True)


def test_empty_benchmark_has_no_crash_no_holder() -> None:
    result = _run([], {})

    assert result.frontier_size == 0
    assert result.open_share is None
    assert result.trend == []
    assert (result.open_count, result.closed_count) == (0, 0)


def test_single_score_becomes_the_current_holder() -> None:
    result = _run([_row("spec-1", 0.5, "1.00", 0)], {"spec-1": OPEN})

    assert result.frontier_size == 1
    assert (result.open_count, result.open_share) == (1, 1.0)
    assert len(result.trend) == 1


def test_baseline_counts_in_split_but_never_becomes_trend_holder() -> None:
    """D-N (owner, 2026-09-10): baselines leave the statistic. They carry no cost, so they cannot
    sit on a cost/score frontier even in principle. Pinned structurally: there is no input
    through which a baseline could be counted."""
    assert "baselines" not in inspect.signature(compute_frontier_openness).parameters


def test_later_but_lower_accuracy_score_is_not_in_the_trend() -> None:
    result = _run(
        [_row("spec-1", 0.8, "1.00", 0), _row("spec-2", 0.5, "2.00", 1)],
        {"spec-1": CLOSED, "spec-2": OPEN},
    )

    assert result.frontier_size == 1
    assert result.open_count == 0
    assert len(result.trend) == 1


def test_exact_tie_does_not_move_the_holder() -> None:
    """Pareto ties: equal on BOTH axes, neither dominates, so both are on the frontier and both
    count. The old score-only rule kept the earlier entry alone."""
    result = _run(
        [_row("spec-1", 1.0, "1.00", 0), _row("spec-2", 1.0, "1.00", 1)],
        {"spec-1": OPEN, "spec-2": CLOSED},
    )

    assert result.frontier_size == 2
    assert (result.open_count, result.closed_count) == (1, 1)


def test_strict_improvement_after_a_tie_does_move_the_holder() -> None:
    result = _run(
        [
            _row("spec-1", 0.5, "1.00", 0),
            _row("spec-2", 0.5, "1.00", 1),
            _row("spec-3", 0.6, "1.00", 2),
        ],
        {"spec-1": OPEN, "spec-2": OPEN, "spec-3": CLOSED},
    )

    # 1.0 with the tied pair, then 0.0 once spec-3 dominates both.
    assert [p.open_share for p in result.trend] == [1.0, 0.0]
    assert result.frontier_size == 1


def test_openness_override_changes_the_holders_reported_openness() -> None:
    result = _run([_row("spec-1", 0.9, "1.00", 0)], {"spec-1": CLOSED}, {"spec-1": "open"})

    assert (result.open_count, result.closed_count) == (1, 0)


# --- Coverage (OME-1056): now enforced by the comparable-rows read --------------------------------


async def _seed_coverage(case_count: int | None) -> None:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="ifeval", display_name="IFEval", revision="rev", case_count=case_count
    )
    for spec_id, score, total in (("one-case-run", 1.0, 1), ("honest-full-run", 0.85, 541)):
        outcome = await store.submit(
            ScoreSubmission(
                benchmark_id="ifeval",
                spec_id=spec_id,
                url4_expression=f"url4://{spec_id}",
                submitted_by="tester",
                score=score,
                total_questions=total,
                ran_with_providers=["openrouter"],
                run_cost_usd=Decimal("1.000000"),
                run_cost_status="complete",
            )
        )
        await Score.filter(id=outcome.score.id).update(benchmark_revision="rev")


@pytest.mark.asyncio
async def test_a_partial_run_does_not_hold_the_frontier(tortoise_db: None) -> None:
    """INVARIANT (OME-1056): a run covering fewer cases than the benchmark defines is not
    comparable, and is ADVANTAGED: fewer cases makes a perfect score easier. Both reads behind
    the statistic apply the rule the ranking applies, so it can neither count nor shape the trend.
    """
    await _seed_coverage(541)
    store = ScoreStore()

    history = await store.frontier_history_inputs(
        "ifeval", registered_revision="rev", registered_case_count=541
    )
    current = await store.leaderboard_pareto_inputs(
        "ifeval", registered_revision="rev", registered_case_count=541
    )

    assert [row.spec_id for row in history] == ["honest-full-run"]
    assert [entry.spec_id for entry in current] == ["honest-full-run"]


@pytest.mark.asyncio
async def test_a_board_with_no_registered_count_still_ranks_everything(tortoise_db: None) -> None:
    # None means the board declares no canonical scope, so nothing is comparable-or-not.
    await _seed_coverage(None)

    history = await ScoreStore().frontier_history_inputs(
        "ifeval", registered_revision="rev", registered_case_count=None
    )

    assert {row.spec_id for row in history} == {"one-case-run", "honest-full-run"}

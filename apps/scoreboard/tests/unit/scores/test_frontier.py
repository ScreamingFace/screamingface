"""Unit tests for compute_frontier (OME-323, spec §5/§6/§9).

Pure function, no DB — scores/baselines are constructed directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from scoreboard.scores.frontier import compute_frontier
from scoreboard.scores.schemas import BaselineSchema, ScoreSchema


def _score(
    *,
    spec_id: str = "spec-1",
    score: float,
    submitted_at: datetime,
    ran_with_providers: list[str] | None = None,
    openness_override: Literal["open", "closed"] | None = None,
) -> ScoreSchema:
    return ScoreSchema(
        id=uuid4(),
        version=1,
        benchmark_id="hle",
        # OME-852: required since OME-775. None is honest here — frontier and openness
        # classification do not depend on which benchmark revision produced the score.
        benchmark_revision=None,
        # OME-770 made this required: a nullable-but-required field means a construction
        # site cannot silently omit a cost, which would read as free rather than unknown.
        # None is honest here — frontier and openness classification ignore cost.
        run_cost_usd=None,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}",
        submitted_by="tester",
        submitted_at=submitted_at,
        score=score,
        total_questions=10,
        correct_questions=int(score * 10),
        ran_with_providers=ran_with_providers or ["huggingface"],
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=False,
        metadata=None,
        openness_override=openness_override,
    )


def _baseline(
    *,
    model_name: str = "gpt-5.2",
    score: float,
    openness_override: Literal["open", "closed"] | None = None,
) -> BaselineSchema:
    return BaselineSchema(
        id=uuid4(),
        benchmark_id="hle",
        model_name=model_name,
        score=score,
        source="lmarena",
        source_url=None,
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata=None,
        openness_override=openness_override,
    )


def test_empty_benchmark_has_no_crash_no_holder() -> None:
    result = compute_frontier(scores=[], baselines=[])

    assert result.current is None
    assert result.trend == []
    assert result.open_count == 0
    assert result.closed_count == 0
    assert result.open_share == 0.0


def test_single_score_becomes_the_current_holder() -> None:
    score = _score(score=0.5, submitted_at=datetime(2026, 1, 1, tzinfo=UTC))
    result = compute_frontier(scores=[score], baselines=[])

    assert result.current is not None
    assert result.current.score == 0.5
    assert result.current.openness == "open"
    assert len(result.trend) == 1


def test_baseline_counts_in_split_but_never_becomes_trend_holder() -> None:
    """Spec §6's baseline-timing resolution: a Baseline can outscore every Score but
    must never become the trend's holder — imported_at isn't a trustworthy
    timestamp. It still counts toward the current open/closed split."""
    high_baseline = _baseline(model_name="gpt-5.2", score=0.99)  # closed, highest
    low_score = _score(
        score=0.2,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        ran_with_providers=["huggingface"],  # open
    )

    result = compute_frontier(scores=[low_score], baselines=[high_baseline])

    assert result.current is not None
    assert result.current.score == 0.2  # the Score, never the higher Baseline
    assert result.open_count == 1  # the score
    assert result.closed_count == 1  # the baseline
    assert result.open_share == 0.5


def test_later_but_lower_accuracy_score_is_not_in_the_trend() -> None:
    first = _score(score=0.8, submitted_at=datetime(2026, 1, 1, tzinfo=UTC))
    later_worse = _score(spec_id="spec-2", score=0.5, submitted_at=datetime(2026, 1, 2, tzinfo=UTC))

    result = compute_frontier(scores=[first, later_worse], baselines=[])

    assert len(result.trend) == 1
    assert result.current is not None
    assert result.current.score == 0.8


def test_exact_tie_does_not_move_the_holder() -> None:
    """Spec §6's tie-breaking resolution: the earliest holder keeps the position on
    an exact tie, even when the later entry has different openness."""
    first = _score(
        score=1.0,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        ran_with_providers=["huggingface"],
    )
    tied_later = _score(
        spec_id="spec-2",
        score=1.0,
        submitted_at=datetime(2026, 1, 2, tzinfo=UTC),
        ran_with_providers=["openai"],
    )

    result = compute_frontier(scores=[first, tied_later], baselines=[])

    assert len(result.trend) == 1
    assert result.current is not None
    assert result.current.label == "spec-1"
    assert result.current.openness == "open"


def test_strict_improvement_after_a_tie_does_move_the_holder() -> None:
    """Contrast with the tie test above: a later entry that genuinely beats the
    tied accuracy DOES become the new holder."""
    first = _score(score=0.5, submitted_at=datetime(2026, 1, 1, tzinfo=UTC))
    tied = _score(spec_id="spec-2", score=0.5, submitted_at=datetime(2026, 1, 2, tzinfo=UTC))
    strictly_better = _score(
        spec_id="spec-3", score=0.6, submitted_at=datetime(2026, 1, 3, tzinfo=UTC)
    )

    result = compute_frontier(scores=[first, tied, strictly_better], baselines=[])

    assert len(result.trend) == 2  # spec-1 at 0.5, spec-3 at 0.6 — spec-2 never moves it
    assert result.current is not None
    assert result.current.label == "spec-3"
    assert result.current.score == 0.6


def test_openness_override_changes_the_holders_reported_openness() -> None:
    score = _score(
        score=0.9,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        ran_with_providers=["openai"],
        openness_override="open",
    )

    result = compute_frontier(scores=[score], baselines=[])

    assert result.current is not None
    assert result.current.openness == "open"
    assert result.open_count == 1
    assert result.closed_count == 0


def _coverage_score(
    *, spec_id: str, score: float, total_questions: int, minute: int
) -> ScoreSchema:
    """A score whose `total_questions` varies — the prior `_score` helper hardcodes it to 10.

    Built here rather than by extending that helper: it is a prior test fixture, and rule 5 makes
    editing one an owner decision that a new keyword argument does not justify (OME-1056).
    """
    return ScoreSchema(
        id=uuid4(),
        version=1,
        benchmark_id="hle",
        benchmark_revision=None,
        run_cost_usd=None,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}",
        submitted_by="tester",
        submitted_at=datetime(2026, 9, 2, 12, minute, tzinfo=UTC),
        score=score,
        total_questions=total_questions,
        correct_questions=None,
        ran_with_providers=["huggingface"],
        ran_at_local=None,
        client_name=None,
        client_version=None,
        client_platform=None,
        verified_by_screamingface=False,
        metadata=None,
        openness_override=None,
    )


def test_a_partial_run_does_not_hold_the_frontier() -> None:
    """OME-1056: the same coverage rule the ranking applies.

    INVARIANT: this is the WORSE half of the bug the ranking fix addressed. `_compute_trend`
    advances the holder only on a STRICT improvement, so a one-case 1.0 becomes `current` and no
    complete run can ever displace it — the table's version is a wrong ordering, this one is
    permanent. Before this filter the board hid the partial run from the ranking while publishing
    it as the state of the art on the same page.
    """
    result = compute_frontier(
        scores=[
            _coverage_score(spec_id="one-case-run", score=1.0, total_questions=1, minute=0),
            _coverage_score(spec_id="honest-full-run", score=0.85, total_questions=541, minute=1),
        ],
        baselines=[],
        registered_case_count=541,
    )

    assert result.current is not None
    assert result.current.label == "honest-full-run"
    assert [point.label for point in result.trend] == ["honest-full-run"]
    assert result.open_count + result.closed_count == 1


def test_a_board_with_no_registered_count_still_ranks_everything() -> None:
    # None means the board declares no canonical scope, so nothing is comparable-or-not and the
    # frontier behaves exactly as it did before this change.
    result = compute_frontier(
        scores=[_coverage_score(spec_id="one-case-run", score=1.0, total_questions=1, minute=0)],
        baselines=[],
        registered_case_count=None,
    )

    assert result.current is not None
    assert result.current.label == "one-case-run"

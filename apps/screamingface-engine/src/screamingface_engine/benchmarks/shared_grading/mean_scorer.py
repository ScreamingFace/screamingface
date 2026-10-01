"""The shared benchmark-level reduction — folding per-Case marks into the class results.

Every Case (one question) has already been graded to a number by this point. This
module is the benchmark office: it takes the stack of per-Case grades and totals them into
ONE headline score plus a fixed row of quality metrics for the leaderboard.

The benchmark chooses exactly one thing here — its ``mean``, the official way its
per-Case scores average into the headline number (GDPval: plain average; HealthBench:
clip each score into [0, 1] first; the worst-30% challenge metric: average only the
lowest 30% of scores). Everything else — which metrics exist and what they are
named — is fixed shared-grading vocabulary, so a leaderboard reader parses one shape no matter
the benchmark.

Worked example — 3 Cases, scores [0.8, 0.5, 0.2], each rubric 5 items, all judged,
one MET count of 9 across the run:

    score             = mean([0.8, 0.5, 0.2])       → 0.5    (the benchmark's formula)
    pass_rate         = 9 met / 15 judged           → 0.6    (rubric items, not Cases)
    scored_cases      = 3
    score_sd          = sample stdev (n−1) of [0.8, 0.5, 0.2] → 0.3
    verdict_coverage  = 15 judged / 15 expected     → 1.0    (must be 1.0 to be valid)
    judge_invalid_replies = 0

The scorer REFUSES partial input: an ungraded Case in the stack is an assertion
error, never skipped — skipping would silently inflate the mean (the upstream scored
path is responsible for turning every failure into a graded-or-failed Case first).

FEATURE: one shared grading code per benchmark (OME-1024, extracted in OME-1097) — this
scorer existed as a near byte-identical closure in gdpval and healthbench.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CaseGrade, CaseResult


def mean_scorer(
    mean: Callable[[Sequence[float]], float | None],
) -> Callable[[Sequence[CaseResult]], CandidateScore]:
    """Bind one benchmark's benchmark-level mean into the shared penalty-bearing reduction.

    The metric vocabulary is fixed shared-grading vocabulary — every rubric benchmark publishes
    exactly ``pass_rate``, ``scored_cases``, ``score_sd``, ``verdict_coverage``,
    ``judge_invalid_replies``; the ``mean`` is the only benchmark choice.
    """

    def score(cases: Sequence[CaseResult]) -> CandidateScore:
        grades: list[CaseGrade | None] = [case.grade for case in cases]
        if any(grade is None or grade.score is None for grade in grades):  # pragma: no cover
            raise AssertionError("the mean scorer requires complete graded Cases")
        typed: list[CaseGrade] = [
            grade for grade in grades if grade is not None and grade.score is not None
        ]
        scores: list[float] = [float(grade.score) for grade in typed if grade.score is not None]
        judged_items: int = sum(int(grade.metrics["judged"]) for grade in typed)
        total_items: int = sum(int(grade.metrics["expected"]) for grade in typed)
        invalid_replies: int = sum(int(grade.metrics["invalid_replies"]) for grade in typed)
        met_items: int = sum(
            1 for grade in typed for check in grade.checks if check.outcome == "MET"
        )
        mean_score: float | None = mean(scores)
        if mean_score is None:  # pragma: no cover - a Benchmark always selects one Case
            raise AssertionError("the mean scorer requires at least one Case")
        return CandidateScore(
            score=round(mean_score, 4),
            metrics={
                "pass_rate": round(met_items / judged_items, 4) if judged_items else 0.0,
                "scored_cases": len(scores),
                "score_sd": round(sample_stdev(scores), 4),
                "verdict_coverage": round(verdict_coverage(judged_items, total_items), 4),
                "judge_invalid_replies": invalid_replies,
            },
        )

    return score


def sample_stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (n−1) over Case scores — a reporting-only metric.

    WHY n−1: population stdev (÷n) understates spread ~10% at small n, and a partial
    run (the SDK's ``limit=N``) is exactly the small-n case a reader is most likely
    to see (defect review S-DR1).
    """

    if len(values) < 2:
        return 0.0
    centre: float = sum(values) / len(values)
    return (sum((value - centre) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def verdict_coverage(judged: int, total: int) -> float:
    """Fraction of rubric items with a valid verdict; 1.0 is required for a valid attempt."""

    if total <= 0:
        return 0.0
    return judged / total


__all__ = ["mean_scorer", "sample_stdev", "verdict_coverage"]

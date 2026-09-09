"""The shared exam-level reduction — folding per-Case marks into the class results.

Every Case (one question) has already been graded to a number by this point. This
module is the exam office: it takes the stack of per-Case grades and totals them into
ONE headline score plus a fixed row of quality metrics for the leaderboard.

The benchmark chooses exactly one thing here — its ``mean``, the official way its
per-Case scores average into the headline number (GDPval: plain average; HealthBench:
clip each score into [0, 1] first; the worst-30% challenge metric: average only the
lowest 30% of scores). Everything else — which metrics exist and what they are
named — is fixed spine vocabulary, so a leaderboard reader parses one shape no matter
the benchmark.

Worked example — 3 Cases, scores [0.8, 0.5, 0.2], each rubric 5 items, all judged,
one MET count of 9 across the run:

    score             = mean([0.8, 0.5, 0.2])       → 0.5    (the board's formula)
    pass_rate         = 9 met / 15 judged           → 0.6    (rubric items, not Cases)
    scored_cases      = 3
    score_sd          = sample stdev (n−1) of [0.8, 0.5, 0.2] → 0.3
    verdict_coverage  = 15 judged / 15 expected     → 1.0    (must be 1.0 to be valid)
    judge_invalid_replies = 0

The scorer REFUSES partial input: an ungraded Case in the stack is an assertion
error, never skipped — skipping would silently inflate the mean (the upstream scored
path is responsible for turning every failure into a graded-or-failed Case first).

FEATURE: one grading spine per benchmark (OME-1024, extracted in OME-1097) — this
scorer existed as a near byte-identical closure in gdpval and healthbench.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.contract import CaseResult


def exam_scorer(
    mean: Callable[[Sequence[float]], float | None],
) -> Callable[[Sequence[CaseResult]], CandidateScore]:
    """Bind one board's exam-level mean into the shared penalty-bearing reduction.

    The metric vocabulary is fixed spine vocabulary — every rubric board publishes
    exactly ``pass_rate``, ``scored_cases``, ``score_sd``, ``verdict_coverage``,
    ``judge_invalid_replies``; the ``mean`` is the only board choice.
    """

    def score(cases: Sequence[CaseResult]) -> CandidateScore:
        grades = [case.grade for case in cases]
        if any(grade is None or grade.score is None for grade in grades):  # pragma: no cover
            raise AssertionError("the exam scorer requires complete graded Cases")
        typed = [grade for grade in grades if grade is not None and grade.score is not None]
        scores = [float(grade.score) for grade in typed if grade.score is not None]
        judged_items = sum(int(grade.metrics["judged"]) for grade in typed)
        total_items = sum(int(grade.metrics["expected"]) for grade in typed)
        invalid_replies = sum(int(grade.metrics["invalid_replies"]) for grade in typed)
        met_items = sum(1 for grade in typed for check in grade.checks if check.outcome == "MET")
        exam_score = mean(scores)
        if exam_score is None:  # pragma: no cover - a Benchmark always selects one Case
            raise AssertionError("the exam scorer requires at least one Case")
        return CandidateScore(
            score=round(exam_score, 4),
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
    centre = sum(values) / len(values)
    return (sum((value - centre) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def verdict_coverage(judged: int, total: int) -> float:
    """Fraction of rubric items with a valid verdict; 1.0 is required for a valid attempt."""

    if total <= 0:
        return 0.0
    return judged / total


__all__ = ["exam_scorer", "sample_stdev", "verdict_coverage"]

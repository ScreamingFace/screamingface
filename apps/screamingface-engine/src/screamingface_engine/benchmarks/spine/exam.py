"""The shared exam-level reduction — folding per-Case marks into the class results.

Think of it as the exam office totalling a stack of graded papers into one final
grade: the board chooses only the ``mean`` (HealthBench's official clip vs the
worst-30% challenge metric vs GDPval's plain average); every other number and every
metric key is fixed spine vocabulary, so leaderboard readers parse one shape.

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

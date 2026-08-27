"""The GDPval text-subset metric — pure arithmetic, no I/O and no model calls.

A GDPval rubric is a graded checklist. Each criterion carries points: positive means "a good
answer does this", negative means "a good answer never does this". The judge has already decided
which criteria the answer met; this module turns those verdicts into a number.

    points = [+5, +3, -3], judge says criterion 1 met, 2 missed, 3 (the penalty) met

        winnable = 5 + 3    = 8   # only POSITIVE points are winnable: a perfect answer earns
                                  # every plus and triggers no penalty, so penalties are points
                                  # you can LOSE, never points you can win
        earned   = 5 + (-3) = 2   # met criteria only — pluses add, the penalty bites
        score    = 2 / 8    = 0.25

INVARIANT: no clamp, at either level. GDPval rubrics carry penalties down to -85, and a
genuinely harmful answer must be able to rank below one that said nothing.

INVARIANT: an unscorable Case is ``None``, never ``0.0``. "We could not score this" and "the
answer scored zero" are different facts; collapsing them turns a judge outage into a plausible
model weakness, which is precisely the reading this benchmark must never invite.

WHY this is not imported from ``healthbench.scoring``, whose per-case math is identical: that
module is bound to simple-evals parity and must follow the reference if it moves. This board's
metric answers to the GDPval rubrics alone. Two modules that agree today for different reasons
are not duplication worth collapsing — the shared version could only drift under one caller's
obligations while silently redefining the other's exam.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


def case_score(points: Sequence[int], verdicts: Mapping[int, bool]) -> float | None:
    """Score one Case: points earned over points winnable, or ``None`` if unscorable.

    ``verdicts`` maps a 1-based position in ``points`` to whether the judge met that criterion.
    Positions outside the rubric are ignored — the judge never sees rubric ids (the Engine stamps
    them), so a stray id is a bug elsewhere and must not widen this Case's denominator.

    INVARIANT: only judged criteria count, and only positive ones are winnable. A partial verdict
    set can therefore only be scored on what was actually judged — a judge failure on a penalty
    criterion silently erases that penalty, which is why the aggregate scores fully-judged Cases
    only.
    """

    judged = {rubric_id for rubric_id in verdicts if 1 <= rubric_id <= len(points)}
    winnable = sum(
        value for index, value in enumerate(points, start=1) if index in judged and value > 0
    )
    if winnable <= 0:
        return None
    earned = sum(
        value for index, value in enumerate(points, start=1) if index in judged and verdicts[index]
    )
    return earned / winnable


def mean(scores: Iterable[float | None]) -> float | None:
    """The exam score: a plain average over Cases that produced a number.

    INVARIANT: unscorable Cases are SKIPPED, not averaged in as zero — otherwise a judge outage
    would depress a candidate's exam score in a way indistinguishable from bad answers.

    INVARIANT: no floor at zero. HealthBench's professional board clips because the official
    HealthBench metric does; GDPval's official metric is an expert pairwise win rate, so there is
    no published convention to match and a clip here would imply one exists.
    """

    graded = [score for score in scores if score is not None]
    if not graded:
        return None
    return sum(graded) / len(graded)


def sample_stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (n-1) over Case scores — a reporting-only metric.

    WHY n-1: population stdev understates spread by roughly 10% at small n, and a partial run
    (the SDK's ``limit=N``) is exactly the small-n case a reader is most likely to see.
    """

    if len(values) < 2:
        return 0.0
    centre = sum(values) / len(values)
    return (sum((value - centre) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def verdict_coverage(judged: int, total: int) -> float:
    """Fraction of criteria carrying a valid verdict; 1.0 is required for a valid attempt."""

    if total <= 0:
        return 0.0
    return judged / total


__all__ = ["case_score", "mean", "sample_stdev", "verdict_coverage"]

"""Pure HealthBench scoring primitives — the per-Case math, and BOTH exam-level metrics.

Mirrors the reference ``calculate_score`` (simple-evals ``healthbench_eval.py``): a Case
score is achieved points over the sum of POSITIVE points, negatives subtract, and the
per-Case value is UNCLAMPED. That half is shared by every HealthBench board.

The exam-level reduction is where the two boards part, and each picks its own here:

- ``clipped_mean`` — the OFFICIAL metric (``np.clip(mean, 0, 1)``), used by the full
  525-case professional board so its number is comparable to published figures.
- ``unclipped_mean`` — the challenge metric, used by the worst-30% board. It DIVERGES
  from the reference deliberately: on that subset every serious baseline mean is
  negative, so the official clip would flatten the whole leaderboard to 0.00. Never
  present an unclipped score as an official HealthBench score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def case_score(
    points: Sequence[int],
    verdicts: Mapping[int, bool],
) -> float | None:
    """Score one Case: points earned / best possible points. Penalties only subtract.

    A rubric is a graded checklist. Each item is worth points: positive = "a good
    answer does this" (e.g. +5 "recommends seeing a doctor"), negative = "a good
    answer never does this" (e.g. -3 "invents a dosage"). The judge already decided
    which items the answer hit: ``verdicts[i]`` is True/False for item ``i``
    (1-based position in ``points``).

    Worked example — ``points = [+5, +3, -3]``, judge says item 1 hit, item 2
    missed, item 3 (the penalty) hit::

        best possible = 5 + 3      = 8    # only POSITIVE items count as "possible":
                                          # a perfect answer earns every plus and
                                          # triggers no penalty — penalties are not
                                          # points you can win, only lose
        earned        = 5 + (-3)   = 2    # hit items only: pluses add, penalty bites
        score         = 2 / 8      = 0.25

    Hit enough penalties and ``earned`` goes negative → the score goes below 0.
    That's intended: no clamp here (module docstring explains why).

    The ``None`` case: if no positive item got judged, "best possible" is 0 —
    there is nothing to divide by. We return ``None``, NOT 0.0, because "we
    couldn't score this" and "the answer scored zero" are different facts.

    Same math as the reference ``calculate_score``
    (https://github.com/openai/simple-evals/blob/main/healthbench_eval.py);
    the steps below map 1:1 onto the example.

    INVARIANT: only fully-judged Cases may be scored (the aggregate enforces it) —
    negative-points items never enter the denominator, so scoring a partial verdict set
    could only inflate the Case: a judge failure on a penalty item would erase the
    penalty.
    """

    # Which items actually got a verdict (ignore ids outside this Case's rubric).
    judged = {rubric_id for rubric_id in verdicts if 1 <= rubric_id <= len(points)}
    # "Best possible" — sum of positive points only.
    denominator = sum(
        value for index, value in enumerate(points, start=1) if index in judged and value > 0
    )
    # Nothing positive judged → unscorable, not zero.
    if denominator <= 0:
        return None
    # "Earned" — hit items only: pluses add, the penalty bites.
    achieved = sum(
        value
        for index, value in enumerate(points, start=1)
        if index in judged and verdicts.get(index, False)
    )
    return achieved / denominator


def unclipped_mean(values: Sequence[float]) -> float | None:
    """The challenge aggregate — the raw mean, NO ``max(0, …)`` clip (see module WHY)."""

    if not values:
        return None
    return sum(values) / len(values)


def clipped_mean(values: Sequence[float]) -> float | None:
    """The OFFICIAL HealthBench exam metric — the reference's ``np.clip(mean, 0, 1)``.

    A Case score can be negative (enough safety penalties make an answer worse than an
    empty one), so the plain average of a rough run can be negative too. Published
    HealthBench figures never are: the reference floors the exam-level average at 0.

    Worked example — two Cases scoring ``[0.8, -1.4]``::

        mean    = (0.8 + -1.4) / 2 = -0.3    # the challenge metric would report this
        clipped = max(0.0, -0.3)   =  0.0    # what a published HealthBench number says

    WHY the upper clip is here yet never bites: a Case score is earned/best-possible with
    earned <= best possible, so no mean can exceed 1.0. It is kept so this function IS the
    reference's clip rather than half of it.

    Args:
        values: the per-Case scores of every gradeable Case in the run.

    Returns:
        The clipped mean, or ``None`` when nothing was gradeable — "we could not score
        this" is a different fact from "the exam scored zero" (see ``case_score``).
    """

    if not values:
        return None
    return min(1.0, max(0.0, sum(values) / len(values)))


__all__ = ["case_score", "clipped_mean", "unclipped_mean"]

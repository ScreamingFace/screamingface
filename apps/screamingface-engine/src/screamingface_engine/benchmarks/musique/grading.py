"""MuSiQue-Ans's deterministic grading — a thin typed wrapper over the paper's own scorer.

The scorer is COPIED, not re-implemented: `vendor/` holds `metrics/answer.py` and
`metrics/support.py` from https://github.com/StonyBrookNLP/musique at commit
922ac98f19a201998dbdae6d7f2887a5258dbdeb (CC BY 4.0), byte-identical but for one import line
(`tests/unit/test_musique_vendor.py` proves it).

INVARIANT — this module calls the copied functions and nothing else. It adds no normalisation,
no rounding and no special cases, because every line between the reply and the number moves our
score away from the paper's (spec D8). It mirrors the official `evaluate_v1.0.py` for one
answerable Case: ground truths are `[answer] + answer_aliases`, the support gold is the
`is_supporting` paragraph numbers.

AIDEV-NOTE: the official script ROUNDS each mean to 3 decimals for display. This module returns
unrounded per-Case values; averaging them is the aggregate's job, and rounding is presentation.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from screamingface_engine.benchmarks.musique.vendor.answer import (
    compute_exact,
    compute_f1,
    metric_max_over_ground_truths,
)
from screamingface_engine.benchmarks.musique.vendor.support import SupportMetric


@dataclass(frozen=True, slots=True)
class AnswerScore:
    """One Case's answer grades — the paper's token F1 and exact match (0 or 1)."""

    f1: float
    exact: int


def score_answer(prediction: str, answer: str, aliases: Sequence[str]) -> AnswerScore:
    """Grade one committed answer against the gold answer and its aliases, as the paper does.

    Mental model: a marker holding an answer key with a few accepted spellings. Each spelling is
    compared with the reply after both are normalised (lowercase, punctuation and `a/an/the`
    dropped, spaces collapsed), and the reply keeps its BEST comparison — exactly the official
    `AnswerMetric.__call__`, without its running total.

    Stages, in execution order:

    1. **Ground truths.** `[answer, *aliases]`, the official order (`evaluate_v1.0.py`).
    2. **Token F1.** For each ground truth, the overlap of normalised tokens: precision is the
       share of the reply's tokens that match, recall the share of the gold's; F1 is their
       harmonic mean. The best over ground truths wins.
    3. **Exact match.** 1 when some ground truth normalises to exactly the reply, else 0.

    Worked example — real Case `3hop1__454441_55349_651302`, gold `Denver`, alias
    `Denver, Colorado`, reply `Denver, CO`:

    - against `Denver`: reply tokens [denver, co], gold [denver] → precision 1/2, recall 1/1,
      F1 = 2·0.5·1 / 1.5 = 0.667;
    - against `Denver, Colorado`: gold [denver, colorado] → precision 1/2, recall 1/2, F1 0.5;
    - best possible F1 0.667; exact match 0 (neither normalises to `denver co`).

    Args:
        prediction: the committed answer from `answering.extract_reply`, unnormalised.
        answer: the dataset's gold answer for this Case.
        aliases: the dataset's `answer_aliases` (often empty).

    Returns:
        ``AnswerScore(f1, exact)``: F1 in [0, 1] as a float; exact match as the int 0 or 1.
    """

    # Stage 1 — ground truths, in the official order.
    ground_truths: list[str] = [answer, *aliases]
    # Stage 2 — best token F1. WHY float(): upstream returns the INT 0 or 1 on its early exits.
    f1: float = float(metric_max_over_ground_truths(compute_f1, prediction, ground_truths))
    # Stage 3 — best exact match, already 0/1 upstream; int() as AnswerMetric does.
    exact: int = int(metric_max_over_ground_truths(compute_exact, prediction, ground_truths))
    return AnswerScore(f1=f1, exact=exact)


def score_support(predicted: Collection[int], gold: Collection[int]) -> float:
    """Support F1 for one Case: the cited paragraph numbers against the gold supporting ones.

    WHY a fresh `SupportMetric` per call: the upstream class ACCUMULATES a running mean across
    calls. One shared instance would make each Case's score the mean of every Case before it.
    The inputs are sorted only to make the call deterministic; upstream turns both into sets.
    """

    metric: SupportMetric = SupportMetric()
    metric(sorted(predicted), sorted(gold))
    _, f1 = metric.get_metric()
    return float(f1)


__all__ = ["AnswerScore", "score_answer", "score_support"]

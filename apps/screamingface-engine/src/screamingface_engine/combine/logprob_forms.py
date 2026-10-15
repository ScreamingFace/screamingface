"""The logprob and entropy declared values (E4b part 3; logprob PRD §3, entropy PRD §3).

FEATURE: turn one member's reply numbers (the token count, the exact sum of the token
log-probabilities, the mean token entropy) into the number that a declared sf.Logprob(form) or
sf.Entropy source gives the combine step.
INVARIANT: pure arithmetic on Python floats, standard library only; a result is a finite float or
None, and never -0.0.
"""

from __future__ import annotations

import math
from typing import Literal

type LogprobForm = Literal["mean", "sum", "prob"]


def logprob_value(
    tokens: float | None, logprob_sum: float | None, form: LogprobForm
) -> float | None:
    """``"sum"`` is s, ``"mean"`` is s / n, ``"prob"`` is exp(s / n) (n tokens, sum s).

    None when n or s is unknown or not finite, when n < 1 (no token, LP-D2), when s > 0 (a
    log-probability is never positive), or when ``"prob"`` underflows to 0.0 (P10, LP-D4).
    """
    if tokens is None or logprob_sum is None or not _usable(tokens, logprob_sum):
        return None
    mean = logprob_sum / tokens + 0.0  # WHY + 0.0: -0.0 becomes 0.0
    values = {"sum": logprob_sum + 0.0, "mean": mean, "prob": math.exp(mean)}
    value = values[form]
    return None if form == "prob" and value == 0.0 else value


def _usable(tokens: float, logprob_sum: float) -> bool:
    """At least one token, and a finite sum that is at most 0 (a log-probability)."""
    return math.isfinite(tokens) and math.isfinite(logprob_sum) and tokens >= 1 and logprob_sum <= 0


def entropy_value(entropy_mean: float | None) -> float | None:
    """The declared entropy: the reply's mean token entropy in nats, when it is finite and >= 0."""
    if entropy_mean is None or not math.isfinite(entropy_mean) or entropy_mean < 0:
        return None
    return entropy_mean + 0.0


__all__ = ["LogprobForm", "entropy_value", "logprob_value"]

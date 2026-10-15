"""The logprob and entropy declared values (E4b part 3; logprob PRD §3, entropy PRD §3).

FEATURE: turn one member's reply numbers (the token count, the exact sum of the token
log-probabilities, the mean token entropy) into the number that a declared sf.Logprob(form) or
sf.Entropy source gives the combine step.
INVARIANT: pure arithmetic on Python floats, standard library only; a result is a finite float or
None, and never -0.0.
"""

from __future__ import annotations

from typing import Literal

type LogprobForm = Literal["mean", "sum", "prob"]


def logprob_value(
    tokens: float | None, logprob_sum: float | None, form: LogprobForm
) -> float | None:
    """``"sum"`` is s, ``"mean"`` is s / n, ``"prob"`` is exp(s / n) (n tokens, sum s)."""
    raise NotImplementedError("E4b part 3 unit 4")


def entropy_value(entropy_mean: float | None) -> float | None:
    """The declared entropy: the reply's mean token entropy in nats, when it is finite and >= 0."""
    raise NotImplementedError("E4b part 3 unit 4")


__all__ = ["LogprobForm", "entropy_value", "logprob_value"]

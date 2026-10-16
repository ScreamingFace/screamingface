"""The value of a declared sum of signals (E4b part 6; signal-sum PRD §2.1, erd §1).

FEATURE: turn one member's component values into the number that a declared
``{"source": "sum", "coefficients": {...}}`` entry gives the combine step:
sum(coefficient x value) over the components.
INVARIANT: pure arithmetic, standard library only. The sum is exact (``fractions.Fraction``) and
is rounded ONCE to a float (SU-I4), so the order of the terms never changes the result. The result
is a finite float or None, and never -0.0.
WHY not ``math.fsum`` of the float products: each product is rounded before the sum, so
0.1 x 3 + 0.1 x 0.1 gives 0.31000000000000005 and not 0.31 (signal-sum SM-D1, overview P5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction


def sum_value(
    terms: Sequence[tuple[str, float]], values: Mapping[str, float | None]
) -> float | None:
    """The exact sum of coefficient x value over ``terms``, rounded once to a float (SU-I4).

    None when a component value is None (SU-I3: missing is not zero), or when the exact sum is
    outside the float range. Every name of ``terms`` is a key of ``values``; every number is finite.
    """
    total = Fraction(0)
    for name, coefficient in terms:
        value = values[name]
        if value is None:
            return None
        total += Fraction(coefficient) * Fraction(value)
    try:
        return float(total) + 0.0  # WHY + 0.0: an underflowing negative sum gives -0.0
    except OverflowError:  # the exact sum is outside the float range
        return None


__all__ = ["sum_value"]

"""A saved-cost total is exact for any number of contributions, not just for two.

FEATURE: run-level saved cost (PRD ans:Q2). Money is added, never rounded — a total an operator
reconciles against a provider invoice has to be the sum, not an approximation of it.

The defect this pins (PR #930 review round 3, finding 3): the accumulator added under a FIXED
`AMOUNT_PRECISION`, sized for ONE amount at the producer's published bound (18 integer + 33
fractional digits, so 51 significant digits, plus 2 of headroom). A SUM of N such amounts needs
`51 + ceil(log10(N))` significant digits, so at N = 1000 the total silently lost its last digit.
No fixed constant can bound an unbounded sum; the precision has to come from the operands.

INVARIANT under test: exactness is checked against `Fraction`, never against another `Decimal`
expression. `a * 1000` is itself evaluated under the ambient 28-digit context, so a Decimal
"expected" value launders the very rounding these tests exist to catch — the first draft of this
file made exactly that mistake and reported the shipped code as correct.

INVARIANT: `AMOUNT_PRECISION` remains a FLOOR. Deriving precision must never make a small sum
LESS precise than the single-amount conversion that produced its operands.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from screamingface_engine.runner.cache_counters import SavedCostTotals
from screamingface_engine.world.accounting import AMOUNT_PRECISION

# The producer's published bound, exactly: 18 integer digits and 33 fractional digits. A value
# that arrived AT the bound is legal input, so the accumulator must carry it without rounding.
_AT_THE_BOUND = Decimal("999999999999999999.000000000000000000000000000000001")


def _summed(amount: Decimal, times: int) -> Decimal:
    """`amount` accumulated `times` over, through the real routing the run counter uses.

    Asserts the total ARRIVED: a `None` here would mean the amounts never landed at all, and
    comparing `Fraction(None)` would fail for that reason instead of for an inexact sum —
    a passing-looking failure is worse than a loud one.
    """
    totals = SavedCostTotals()
    for _ in range(times):
        totals.add_saved_cost(amount, "reported")
    assert totals.saved_cost_usd is not None, "no amount reached the reported accumulator"
    return totals.saved_cost_usd


def test_a_thousand_boundary_amounts_sum_exactly() -> None:
    # The reviewer's own repro. Under the shipped fixed precision this produced
    # …000.00000000000000000000000000000010 — the final `1` rounded away, and silently, because
    # `Decimal` signals inexactness only when the caller asks.
    total = _summed(_AT_THE_BOUND, 1000)

    assert Fraction(total) == Fraction(_AT_THE_BOUND) * 1000


def test_the_two_value_case_round_two_fixed_stays_exact() -> None:
    # Regression guard for the previous round's fix: raising the precision must not be traded
    # away by the new derivation.
    total = _summed(_AT_THE_BOUND, 2)

    assert Fraction(total) == Fraction(_AT_THE_BOUND) * 2


def test_the_total_stays_exact_well_past_the_next_digit_boundary() -> None:
    # 10_000 crosses one more integer digit than 1_000 does. If the derivation were itself a
    # fixed constant chosen to pass the repro, this is where it would fail.
    total = _summed(_AT_THE_BOUND, 10_000)

    assert Fraction(total) == Fraction(_AT_THE_BOUND) * 10_000


def test_widely_separated_magnitudes_do_not_round_the_small_one() -> None:
    # The exponent SPAN, not the digit count, is what a sum needs: a large amount beside a tiny
    # one needs digits enough to span both, and dropping the tiny one is the classic failure.
    totals = SavedCostTotals()
    totals.add_saved_cost(Decimal("999999999999999999"), "reported")
    totals.add_saved_cost(Decimal("0.000000000000000000000000000000001"), "reported")

    assert totals.saved_cost_usd is not None
    assert Fraction(totals.saved_cost_usd) == Fraction(
        "999999999999999999.000000000000000000000000000000001"
    )


def test_the_archive_accumulator_is_exact_too() -> None:
    # Both provenances share one routine, and the invariant is not "the reported total is exact"
    # but "a total is exact". Pinned so a future split cannot fix one and leave the other.
    totals = SavedCostTotals()
    for _ in range(1000):
        totals.add_saved_cost(_AT_THE_BOUND, "archive_matched")

    assert totals.saved_cost_archive_usd is not None
    assert Fraction(totals.saved_cost_archive_usd) == Fraction(_AT_THE_BOUND) * 1000
    assert totals.saved_cost_usd is None


def test_an_ordinary_pair_of_cents_is_untouched() -> None:
    # The everyday case must stay boringly exact, and must not acquire trailing noise from a
    # larger working precision.
    totals = SavedCostTotals()
    totals.add_saved_cost(Decimal("0.01"), "reported")
    totals.add_saved_cost(Decimal("0.02"), "reported")

    assert totals.saved_cost_usd == Decimal("0.03")


def test_the_derived_precision_never_drops_below_the_single_amount_floor() -> None:
    # INVARIANT: `AMOUNT_PRECISION` is a floor, not a replaced value. Two tiny amounts need far
    # fewer digits than 53 to add exactly, and the context must not shrink to fit them — the
    # operands were CONVERTED at 53, so narrowing here would round what conversion preserved.
    assert AMOUNT_PRECISION == 18 + 33 + 2

    totals = SavedCostTotals()
    totals.add_saved_cost(Decimal("1"), "reported")
    totals.add_saved_cost(Decimal("2"), "reported")

    assert totals.saved_cost_usd == Decimal("3")

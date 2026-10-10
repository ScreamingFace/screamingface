"""The v1 reducers and selectors turn readings into one chosen answer (OME-1289, E4a, unit 2).

FEATURE: a vote, a weighted vote and a median pick their answer the same way on every replay.
STORY: as an author of a majority-vote Candidate, ties go to the first member in author order.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

import pytest
from combine_golden_support import (
    member_readings,
    reduce_result,
    select_result,
)

from screamingface_engine.combine.ports import (
    Answer,
    Reduction,
    SpecInvalid,
    TallyRow,
    canonical_decimal,
)


def _rows(reduction: Reduction) -> list[tuple[str, str, tuple[str, ...]]]:
    assert reduction.tally is not None
    return [(r.value, canonical_decimal(r.score), r.holders) for r in reduction.tally]


def test_mode_needs_extracted_values() -> None:
    bare = (Answer("member_1", None, None, "answered", None),)
    with pytest.raises(SpecInvalid, match="extracted values"):
        reduce_result("mode@1", bare)


# Only the canonical form `numeric@1` writes (`-?[0-9]+(\.[0-9]+)?`) is a usable median input.
_NOT_CANONICAL = ["x", "NaN", "1E+999999999", "\uff13", "1e3", " 5"]


@pytest.mark.parametrize("bad", _NOT_CANONICAL)
def test_median_rejects_non_numeric_values(bad: str) -> None:
    for values in ([bad], ["1", bad], [bad, "2"]):
        with pytest.raises(SpecInvalid, match="median@1 needs numeric values"):
            reduce_result("median@1", member_readings(values))


def test_median_rejects_a_voter_with_no_value() -> None:
    bare = (Answer("member_1", None, None, "answered", None),)
    with pytest.raises(SpecInvalid, match="median@1 needs numeric values"):
        reduce_result("median@1", bare)


def test_median_accepts_the_canonical_form_numeric_writes() -> None:
    statistic = reduce_result("median@1", member_readings(["-3", "-1.5", "0.25"])).statistic
    assert statistic == Decimal("-1.5")


@pytest.mark.parametrize("bad", _NOT_CANONICAL)
def test_nearest_rejects_non_canonical_numeric_values(bad: str) -> None:
    for values in ([bad], ["1", bad]):
        with pytest.raises(SpecInvalid, match="nearest@1 needs numeric values"):
            select_result("nearest@1", Reduction(statistic=Decimal(1)), member_readings(values))


def test_nearest_rejects_a_voter_with_no_value() -> None:
    bare = (Answer("member_1", None, None, "answered", None),)
    with pytest.raises(SpecInvalid, match="nearest@1 needs numeric values"):
        select_result("nearest@1", Reduction(statistic=Decimal(1)), bare)


def test_arithmetic_ignores_a_hostile_global_decimal_context() -> None:
    weighted = member_readings(["5", "5"], ["0.111", "0.222"])
    two = member_readings(["1.23", "4.56"])
    shares = Reduction(
        tally=(
            TallyRow("b", Decimal("0.222"), ("member_2",)),
            TallyRow("a", Decimal("0.111"), ("member_1",)),
        )
    )
    context = getcontext()
    saved = context.prec
    context.prec = 2
    try:
        summed = reduce_result("weighted_mode@1", weighted)
        statistic = reduce_result("median@1", two).statistic
        chosen = select_result("first_holder@1", shares, weighted)
    finally:
        context.prec = saved
    assert _rows(summed) == [("5", "0.333", ("member_1", "member_2"))]
    assert statistic is not None
    assert canonical_decimal(statistic) == "2.895"
    assert chosen.agreement == 0.6666666666666666


def test_a_zero_total_tally_is_a_spec_error_not_a_division_error() -> None:
    zero = Reduction(tally=(TallyRow("a", Decimal(0), ("member_1",)),))
    with pytest.raises(SpecInvalid, match="first_holder@1"):
        select_result("first_holder@1", zero, member_readings(["a"]))

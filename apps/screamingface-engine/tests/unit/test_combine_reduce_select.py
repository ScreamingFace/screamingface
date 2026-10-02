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
    Selection,
    SpecInvalid,
    TallyRow,
    canonical_decimal,
)


def _rows(reduction: Reduction) -> list[tuple[str, str, tuple[str, ...]]]:
    assert reduction.tally is not None
    return [(r.value, canonical_decimal(r.score), r.holders) for r in reduction.tally]


def test_mode_and_weighted_mode_tallies() -> None:
    readings = member_readings(["18", "18", "26", "18", "18", None])
    mode = reduce_result("mode@1", readings)
    assert _rows(mode) == [
        ("18", "4", ("member_1", "member_2", "member_4", "member_5")),
        ("26", "1", ("member_3",)),
    ]
    assert mode.statistic is None
    weighted = reduce_result(
        "weighted_mode@1",
        member_readings(["9", "9", "12", "12", "12"], ["3", "3", "1", "1", "1"]),
    )
    assert _rows(weighted) == [
        ("9", "6", ("member_1", "member_2")),
        ("12", "3", ("member_3", "member_4", "member_5")),
    ]
    decimals = reduce_result("weighted_mode@1", member_readings(["5", "5"], ["0.1", "0.2"]))
    assert _rows(decimals) == [("5", "0.3", ("member_1", "member_2"))]


def test_mode_ties_keep_first_holder_order() -> None:
    assert [
        row[0] for row in _rows(reduce_result("mode@1", member_readings(["7", "9", "7", "9"])))
    ] == [
        "7",
        "9",
    ]
    assert [
        row[0] for row in _rows(reduce_result("mode@1", member_readings(["9", "7", "7", "9"])))
    ] == [
        "9",
        "7",
    ]


def test_weighted_mode_needs_weights() -> None:
    with pytest.raises(SpecInvalid, match="needs weights"):
        reduce_result("weighted_mode@1", member_readings(["9", "9"]))
    skipped = member_readings(["9", None], ["2", None])
    assert _rows(reduce_result("weighted_mode@1", skipped)) == [("9", "2", ("member_1",))]


def test_mode_needs_extracted_values() -> None:
    bare = (Answer("member_1", None, None, "answered", None),)
    with pytest.raises(SpecInvalid, match="extracted values"):
        reduce_result("mode@1", bare)


def test_median_even_count_is_mean_of_middle() -> None:
    for values, expected in (
        (["3", "9", "9", "12"], "9"),
        (["2", "4"], "3"),
        (["10", "12", "30", "40"], "21"),
        (["4", None, "8"], "6"),
        (["5"], "5"),
        (["9", "1", "5"], "5"),
    ):
        statistic = reduce_result("median@1", member_readings(values)).statistic
        assert statistic is not None
        assert canonical_decimal(statistic) == expected, values
    assert reduce_result("median@1", member_readings(["3", "9"])).tally is None


# Only the canonical form `numeric@1` writes (`-?[0-9]+(\.[0-9]+)?`) is a usable median input.
_NOT_CANONICAL = [
    "x",
    "NaN",
    "Infinity",
    "1E+999999999",
    "\uff13",
    "1_000",
    "1e3",
    "1.",
    ".5",
    "+5",
    " 5",
    "",
]


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


def _tally(*rows: tuple[str, str, tuple[str, ...]]) -> Reduction:
    return Reduction(tally=tuple(TallyRow(v, Decimal(s), h) for v, s, h in rows))


def test_first_holder_tie_and_agreement() -> None:
    readings = member_readings(["18", "18", "26", "18", "18"])
    selection = select_result("first_holder@1", reduce_result("mode@1", readings), readings)
    assert selection == Selection(chosen=("member_1",), output=None, tie=False, agreement=0.8)
    tied = member_readings(["7", "9", "7", "9"])
    selection = select_result("first_holder@1", reduce_result("mode@1", tied), tied)
    assert selection == Selection(chosen=("member_1",), output=None, tie=True, agreement=0.5)
    with pytest.raises(SpecInvalid):
        select_result("first_holder@1", Reduction(), readings)
    with pytest.raises(SpecInvalid):
        select_result("first_holder@1", Reduction(tally=()), readings)


def test_max_weight_holder_tie_goes_to_author_order() -> None:
    reduction = _tally(("a", "3", ("member_1", "member_2")))
    heavier = member_readings(["a", "a"], ["1", "2"])
    assert select_result("max_weight_holder@1", reduction, heavier) == Selection(
        chosen=("member_2",), output=None, tie=False, agreement=1.0
    )
    equal = member_readings(["a", "a"], ["2", "2"])
    assert select_result("max_weight_holder@1", reduction, equal).chosen == ("member_1",)
    with pytest.raises(SpecInvalid, match="needs weights"):
        select_result("max_weight_holder@1", reduction, member_readings(["a", "a"]))
    with pytest.raises(SpecInvalid):
        select_result("max_weight_holder@1", Reduction(), equal)


def test_nearest_and_value_select_modes() -> None:
    cases = (
        (["3", "9", "9", "12"], "9", "member_2", False, 0.5),
        (["2", "4"], "3", "member_1", True, 0.5),
        (["10", "12", "30"], "12", "member_2", False, 1 / 3),
        (["9", "9", "12"], "9", "member_1", False, 2 / 3),
    )
    for values, median, member, tie, agreement in cases:
        readings = member_readings(list(values))
        reduction = Reduction(statistic=Decimal(median))
        assert select_result("nearest@1", reduction, readings) == Selection(
            chosen=(member,), output=None, tie=tie, agreement=agreement
        ), values
    assert select_result("value@1", Reduction(statistic=Decimal("21")), ()) == Selection(
        chosen=(), output="21"
    )
    assert select_result("value@1", Reduction(statistic=Decimal("2.50")), ()).output == "2.5"
    for op_id in ("nearest@1", "value@1"):
        with pytest.raises(SpecInvalid):
            select_result(op_id, Reduction(), member_readings(["1"]))
    with pytest.raises(SpecInvalid, match="numeric"):
        select_result("nearest@1", Reduction(statistic=Decimal(1)), member_readings(["x"]))

"""The v1 reducers and selectors turn readings into one chosen answer (OME-1289, E4a, unit 2).

FEATURE: a vote, a weighted vote and a median pick their answer the same way on every replay.
STORY: as an author of a majority-vote Candidate, ties go to the first member in author order.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import cast

import pytest
from combine_golden_support import find

from screamingface_engine.combine.ports import (
    CombineInput,
    MemberReading,
    ReadingStatus,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    SpecInvalid,
    TallyRow,
    canonical_decimal,
)


def _readings(
    values: Sequence[str | None], weights: Sequence[str | None] | None = None
) -> tuple[MemberReading, ...]:
    rows: list[MemberReading] = []
    for index, value in enumerate(values):
        weight = None if weights is None or weights[index] is None else Decimal(str(weights[index]))
        status: ReadingStatus = "voted" if value is not None else "empty"
        rows.append(MemberReading(f"member_{index + 1}", value, value, status, weight))
    return tuple(rows)


def _input(readings: tuple[MemberReading, ...]) -> CombineInput:
    return CombineInput(readings=readings, outputs={r.member: "" for r in readings}, signals={})


def _reduce(op_id: str, readings: tuple[MemberReading, ...]) -> Reduction:
    return cast("ReduceOp", find(op_id).run)(_input(readings), {})


def _select(op_id: str, reduction: Reduction, readings: tuple[MemberReading, ...]) -> Selection:
    return cast("SelectOp", find(op_id).run)(reduction, _input(readings), {})


def _rows(reduction: Reduction) -> list[tuple[str, str, tuple[str, ...]]]:
    assert reduction.tally is not None
    return [(r.value, canonical_decimal(r.score), r.holders) for r in reduction.tally]


def test_mode_and_weighted_mode_tallies() -> None:
    readings = _readings(["18", "18", "26", "18", "18", None])
    mode = _reduce("mode@1", readings)
    assert _rows(mode) == [
        ("18", "4", ("member_1", "member_2", "member_4", "member_5")),
        ("26", "1", ("member_3",)),
    ]
    assert mode.statistic is None
    weighted = _reduce(
        "weighted_mode@1",
        _readings(["9", "9", "12", "12", "12"], ["3", "3", "1", "1", "1"]),
    )
    assert _rows(weighted) == [
        ("9", "6", ("member_1", "member_2")),
        ("12", "3", ("member_3", "member_4", "member_5")),
    ]
    decimals = _reduce("weighted_mode@1", _readings(["5", "5"], ["0.1", "0.2"]))
    assert _rows(decimals) == [("5", "0.3", ("member_1", "member_2"))]


def test_mode_ties_keep_first_holder_order() -> None:
    assert [row[0] for row in _rows(_reduce("mode@1", _readings(["7", "9", "7", "9"])))] == [
        "7",
        "9",
    ]
    assert [row[0] for row in _rows(_reduce("mode@1", _readings(["9", "7", "7", "9"])))] == [
        "9",
        "7",
    ]


def test_weighted_mode_needs_weights() -> None:
    with pytest.raises(SpecInvalid, match="needs weights"):
        _reduce("weighted_mode@1", _readings(["9", "9"]))
    skipped = _readings(["9", None], ["2", None])
    assert _rows(_reduce("weighted_mode@1", skipped)) == [("9", "2", ("member_1",))]


def test_mode_needs_extracted_values() -> None:
    bare = (MemberReading("member_1", None, None, "voted", None),)
    with pytest.raises(SpecInvalid, match="extracted values"):
        _reduce("mode@1", bare)


def test_median_even_count_is_mean_of_middle() -> None:
    for values, expected in (
        (["3", "9", "9", "12"], "9"),
        (["2", "4"], "3"),
        (["10", "12", "30", "40"], "21"),
        (["4", None, "8"], "6"),
        (["5"], "5"),
        (["9", "1", "5"], "5"),
    ):
        statistic = _reduce("median@1", _readings(values)).statistic
        assert statistic is not None
        assert canonical_decimal(statistic) == expected, values
    assert _reduce("median@1", _readings(["3", "9"])).tally is None


def test_median_rejects_non_numeric_values() -> None:
    for values in (["x"], ["1", "NaN"], ["Infinity", "2"]):
        with pytest.raises(SpecInvalid, match="needs numeric values"):
            _reduce("median@1", _readings(values))


def _tally(*rows: tuple[str, str, tuple[str, ...]]) -> Reduction:
    return Reduction(tally=tuple(TallyRow(v, Decimal(s), h) for v, s, h in rows))


def test_first_holder_tie_and_agreement() -> None:
    readings = _readings(["18", "18", "26", "18", "18"])
    selection = _select("first_holder@1", _reduce("mode@1", readings), readings)
    assert selection == Selection(chosen=("member_1",), output=None, tie=False, agreement=0.8)
    tied = _readings(["7", "9", "7", "9"])
    selection = _select("first_holder@1", _reduce("mode@1", tied), tied)
    assert selection == Selection(chosen=("member_1",), output=None, tie=True, agreement=0.5)
    with pytest.raises(SpecInvalid):
        _select("first_holder@1", Reduction(), readings)
    with pytest.raises(SpecInvalid):
        _select("first_holder@1", Reduction(tally=()), readings)


def test_max_weight_holder_tie_goes_to_author_order() -> None:
    reduction = _tally(("a", "3", ("member_1", "member_2")))
    heavier = _readings(["a", "a"], ["1", "2"])
    assert _select("max_weight_holder@1", reduction, heavier) == Selection(
        chosen=("member_2",), output=None, tie=False, agreement=1.0
    )
    equal = _readings(["a", "a"], ["2", "2"])
    assert _select("max_weight_holder@1", reduction, equal).chosen == ("member_1",)
    with pytest.raises(SpecInvalid, match="needs weights"):
        _select("max_weight_holder@1", reduction, _readings(["a", "a"]))
    with pytest.raises(SpecInvalid):
        _select("max_weight_holder@1", Reduction(), equal)


def test_nearest_and_value_select_modes() -> None:
    cases = (
        (["3", "9", "9", "12"], "9", "member_2", False, 0.5),
        (["2", "4"], "3", "member_1", True, 0.5),
        (["10", "12", "30"], "12", "member_2", False, 1 / 3),
        (["9", "9", "12"], "9", "member_1", False, 2 / 3),
    )
    for values, median, member, tie, agreement in cases:
        readings = _readings(list(values))
        reduction = Reduction(statistic=Decimal(median))
        assert _select("nearest@1", reduction, readings) == Selection(
            chosen=(member,), output=None, tie=tie, agreement=agreement
        ), values
    assert _select("value@1", Reduction(statistic=Decimal("21")), ()) == Selection(
        chosen=(), output="21"
    )
    assert _select("value@1", Reduction(statistic=Decimal("2.50")), ()).output == "2.5"
    for op_id in ("nearest@1", "value@1"):
        with pytest.raises(SpecInvalid):
            _select(op_id, Reduction(), _readings(["1"]))
    with pytest.raises(SpecInvalid, match="numeric"):
        _select("nearest@1", Reduction(statistic=Decimal(1)), _readings(["x"]))

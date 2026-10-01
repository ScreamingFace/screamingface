"""Reduce operators: every member reading -> one tally or one statistic (OME-1289, E4a).

FEATURE: a vote, a weighted vote and a median are counted the same way on every replay.
STORY: as an author of a majority-vote Candidate, the winning value is the one with most votes.

Mental model: a ballot box. Members that gave a usable value drop one ballot (or their weight)
under their value; the box lists the values from most to fewest, and a tie keeps the order in
which the values first appeared.

INVARIANT: each operator is pure; all Decimal arithmetic runs in ``DECIMAL_CONTEXT``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation, localcontext

from screamingface_engine.combine.ports import (
    DECIMAL_CONTEXT,
    CombineInput,
    MemberReading,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    SpecInvalid,
    TallyRow,
)


def _value(reading: MemberReading, op_id: str) -> str:
    if reading.value is None:
        raise SpecInvalid(f"{op_id} needs extracted values")
    return reading.value


def _tally(
    voters: Sequence[MemberReading], op_id: str, score: Callable[[MemberReading], Decimal]
) -> Reduction:
    """Group voters by value in author order; the stable sort keeps first-holder order on ties."""
    scores: dict[str, Decimal] = {}
    holders: dict[str, list[str]] = {}
    with localcontext(DECIMAL_CONTEXT):
        for reading in voters:
            value = _value(reading, op_id)
            scores[value] = scores.get(value, Decimal(0)) + score(reading)
            holders.setdefault(value, []).append(reading.member)
        rows = [TallyRow(value, scores[value], tuple(holders[value])) for value in scores]
        rows.sort(key=lambda row: -row.score)
    return Reduction(tally=tuple(rows))


def mode(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """One vote per member with a usable value."""
    return _tally(combine_input.voters, "mode@1", lambda reading: Decimal(1))


def _weight(reading: MemberReading) -> Decimal:
    if reading.weight is None:
        raise SpecInvalid("weighted_mode@1 needs weights")
    return reading.weight


def weighted_mode(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """The member's weight per vote."""
    voters = combine_input.voters
    for reading in voters:
        _weight(reading)
    return _tally(voters, "weighted_mode@1", _weight)


def _decimal(reading: MemberReading) -> Decimal:
    try:
        number = Decimal(_value(reading, "median@1"))
    except InvalidOperation as exc:
        raise SpecInvalid("median@1 needs numeric values") from exc
    if not number.is_finite():
        raise SpecInvalid("median@1 needs numeric values")
    return number


def median(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Median of the numeric values; an even count takes the mean of the two middle values."""
    numbers = sorted(_decimal(reading) for reading in combine_input.voters)
    middle = len(numbers) // 2
    if len(numbers) % 2 == 1:
        return Reduction(statistic=numbers[middle])
    with localcontext(DECIMAL_CONTEXT):
        return Reduction(statistic=(numbers[middle - 1] + numbers[middle]) / 2)


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor("mode", 1, "reduce", "One vote per member.", mode),
    OperatorDescriptor(
        "weighted_mode", 1, "reduce", "The member's weight per vote.", weighted_mode
    ),
    OperatorDescriptor("median", 1, "reduce", "Median of the numeric values.", median),
)

__all__ = ["OPERATORS"]

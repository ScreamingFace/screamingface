"""Reduce operators: every member reading -> one tally or one statistic (OME-1289, E4a).

FEATURE: a vote, a weighted vote, a median and a mean are counted the same way on every replay.
STORY: as an author of a majority-vote Candidate, the winning value is the one with most votes.

Mental model: a ballot box. Members that gave a usable value drop one ballot (or their weight)
under their value; the box lists the values from most to fewest, and a tie keeps the order in
which the values first appeared.

INVARIANT: each operator is pure; all Decimal arithmetic runs in ``DECIMAL_CONTEXT``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from decimal import Decimal, localcontext
from typing import cast

from screamingface_engine.combine.ports import (
    DECIMAL_CONTEXT,
    Answer,
    CombineInput,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    SpecInvalid,
    TallyRow,
)

# WHY only this form: it is what numeric@1 writes, and it keeps Decimal() from ever seeing NaN,
# an exponent like 1E+999999999 (which overflows the mean), or a non-ASCII digit.
_CANONICAL_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")

# WHY 34 (E4b P1, MN-D1): a mean such as 4/3 would otherwise carry 1000 digits. The sums stay exact
# in DECIMAL_CONTEXT; only the one division is rounded, ROUND_HALF_EVEN as DECIMAL_CONTEXT.
_MEAN_DIGITS = 34


def _value(answer: Answer, op_id: str) -> str:
    if answer.value is None:
        raise SpecInvalid(f"{op_id} needs extracted values")
    return answer.value


def _tally(voters: Sequence[Answer], op_id: str, score: Callable[[Answer], Decimal]) -> Reduction:
    """Group voters by value in author order; the stable sort keeps first-holder order on ties."""
    scores: dict[str, Decimal] = {}
    holders: dict[str, list[str]] = {}
    with localcontext(DECIMAL_CONTEXT):
        for answer in voters:
            value = _value(answer, op_id)
            scores[value] = scores.get(value, Decimal(0)) + score(answer)
            holders.setdefault(value, []).append(answer.member_id)
        rows = [TallyRow(value, scores[value], tuple(holders[value])) for value in scores]
        rows.sort(key=lambda row: -row.score)
    return Reduction(tally=tuple(rows))


def mode(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """One vote per member with a usable value."""
    return _tally(combine_input.voters, "mode@1", lambda answer: Decimal(1))


def _signal_weight(answer: Answer, op_id: str) -> Decimal | None:
    """A fixed weight as authored; a missing signal weight does not vote (SR-D1)."""
    if answer.weight is None and not answer.signals:
        raise SpecInvalid(f"{op_id} needs weights")
    return answer.weight


def _weighted_voters(combine_input: CombineInput, op_id: str) -> tuple[Answer, ...]:
    """The voters with a usable weight; the others are dropped (ans:Q2). None left is NoVotes."""
    weighted = tuple(a for a in combine_input.voters if _signal_weight(a, op_id) is not None)
    if not weighted:
        raise NoVotes("no voter has a usable weight")
    return weighted


def weighted_mode(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """The member's weight per vote; a voter whose signal weight is missing does not vote."""
    weighted = _weighted_voters(combine_input, "weighted_mode@1")
    return _tally(weighted, "weighted_mode@1", lambda a: cast(Decimal, a.weight))


def _decimal(answer: Answer, op_id: str = "median@1") -> Decimal:
    if answer.value is None or _CANONICAL_NUMBER.fullmatch(answer.value) is None:
        raise SpecInvalid(f"{op_id} needs numeric values")
    return Decimal(answer.value)


def median(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Median of the numeric values; an even count takes the mean of the two middle values."""
    numbers = sorted(_decimal(answer) for answer in combine_input.voters)
    middle = len(numbers) // 2
    if len(numbers) % 2 == 1:
        return Reduction(statistic=numbers[middle])
    with localcontext(DECIMAL_CONTEXT):
        return Reduction(statistic=(numbers[middle - 1] + numbers[middle]) / 2)


def weighted_median(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """The value where the running weight first reaches half the total weight (WM-1, WM-2).

    Participants are the voters with a usable weight. They are sorted by value; the stable sort
    keeps author order among equal values. At exactly half the weight the result is the mean of
    this value and the next one, so equal weights give the median@1 result (P3).
    """
    op_id = "weighted_median@1"
    weighted = _weighted_voters(combine_input, op_id)
    pairs = sorted(
        ((_decimal(answer, op_id), cast(Decimal, answer.weight)) for answer in weighted),
        key=lambda pair: pair[0],
    )
    participants = tuple(answer.member_id for answer in weighted)
    with localcontext(DECIMAL_CONTEXT):
        total = sum((weight for _, weight in pairs), Decimal(0))
        running = Decimal(0)
        index = 0
        for index, (_, weight) in enumerate(pairs):
            running += weight
            if 2 * running >= total:
                break
        number = pairs[index][0]
        if 2 * running == total:
            # WHY index + 1 exists: every weight is > 0, so the last running sum is the total,
            # and 2 * total == total is false.
            return Reduction(
                statistic=(number + pairs[index + 1][0]) / 2, participants=participants
            )
        return Reduction(statistic=number, participants=participants)


def _mean_of(pairs: Sequence[tuple[Decimal, Decimal]]) -> Decimal:
    """sum(w * x) / sum(w): exact sums in DECIMAL_CONTEXT, then ONE division to 34 digits (P1)."""
    with localcontext(DECIMAL_CONTEXT):
        total = sum((weight * number for number, weight in pairs), Decimal(0))
        weights = sum((weight for _, weight in pairs), Decimal(0))
    with localcontext(DECIMAL_CONTEXT, prec=_MEAN_DIGITS):
        return total / weights


def mean(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Mean of the numeric values; spec weights are ignored, as mode@1 ignores them (CS-I1)."""
    numbers = [_decimal(answer, "mean@1") for answer in combine_input.voters]
    if not numbers:
        raise NoVotes("no voter has a value")
    return Reduction(statistic=_mean_of([(number, Decimal(1)) for number in numbers]))


def weighted_mean(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """sum(w * x) / sum(w) over the voters with a usable weight; the others are dropped (ans:Q2)."""
    op_id = "weighted_mean@1"
    weighted = _weighted_voters(combine_input, op_id)
    pairs = [(_decimal(a, op_id), cast(Decimal, a.weight)) for a in weighted]
    return Reduction(statistic=_mean_of(pairs), participants=tuple(a.member_id for a in weighted))


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor("mode", 1, "reduce", "One vote per member.", mode),
    OperatorDescriptor(
        "weighted_mode", 1, "reduce", "The member's weight per vote.", weighted_mode
    ),
    OperatorDescriptor("median", 1, "reduce", "Median of the numeric values.", median),
    OperatorDescriptor(
        "weighted_median",
        1,
        "reduce",
        "Weighted median of the numeric values; a member with no usable weight is dropped.",
        weighted_median,
    ),
    OperatorDescriptor("mean", 1, "reduce", "Mean of the numeric values.", mean),
    OperatorDescriptor(
        "weighted_mean",
        1,
        "reduce",
        "Weighted mean of the numeric values; a member with no usable weight is dropped.",
        weighted_mean,
    ),
)

__all__ = ["OPERATORS"]

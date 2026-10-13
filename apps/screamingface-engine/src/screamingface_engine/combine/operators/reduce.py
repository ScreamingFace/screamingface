"""Reduce operators: every member reading -> one tally or one statistic (OME-1289, E4a).

FEATURE: a vote, a weighted vote and a median are counted the same way on every replay.
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


def _signal_weight(answer: Answer) -> Decimal | None:
    """A fixed weight as authored; a missing signal weight does not vote (SR-D1)."""
    if answer.weight is None and not answer.signals:
        raise SpecInvalid("weighted_mode@1 needs weights")
    return answer.weight


def weighted_mode(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """The member's weight per vote; a voter whose signal weight is missing does not vote."""
    weighted = tuple(a for a in combine_input.voters if _signal_weight(a) is not None)
    if not weighted:
        raise NoVotes("no voter has a usable weight")
    return _tally(weighted, "weighted_mode@1", lambda a: cast(Decimal, a.weight))


def _decimal(answer: Answer) -> Decimal:
    if answer.value is None or _CANONICAL_NUMBER.fullmatch(answer.value) is None:
        raise SpecInvalid("median@1 needs numeric values")
    return Decimal(answer.value)


def median(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Median of the numeric values; an even count takes the mean of the two middle values."""
    numbers = sorted(_decimal(answer) for answer in combine_input.voters)
    middle = len(numbers) // 2
    if len(numbers) % 2 == 1:
        return Reduction(statistic=numbers[middle])
    with localcontext(DECIMAL_CONTEXT):
        return Reduction(statistic=(numbers[middle - 1] + numbers[middle]) / 2)


def mean(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Mean of the numeric values; spec weights are ignored, as mode@1 ignores them (CS-I1)."""
    raise NotImplementedError("E4b unit 3")


def weighted_mean(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """sum(w * x) / sum(w) over the voters with a usable weight; the others are dropped (ans:Q2)."""
    raise NotImplementedError("E4b unit 3")


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor("mode", 1, "reduce", "One vote per member.", mode),
    OperatorDescriptor(
        "weighted_mode", 1, "reduce", "The member's weight per vote.", weighted_mode
    ),
    OperatorDescriptor("median", 1, "reduce", "Median of the numeric values.", median),
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

"""Select operators: one reduction -> the chosen member(s) or a built value (OME-1289, E4a).

FEATURE: the answer is a member's own text (byte for byte) or the median value, never a rewrite.
STORY: as an author of a majority-vote Candidate, a tie goes to the first member in author order.

Mental model: a referee reading the ballot box. It names the winner, says if the result was a
tie, and says how much of the vote the winner held.

INVARIANT: each operator is pure; all Decimal arithmetic runs in ``DECIMAL_CONTEXT``.
AIDEV-NOTE: ``tie`` for ``nearest@1`` means two or more different values at the minimum distance;
``value@1`` has ``agreement`` null. Both are v1 behavior pinned by the golden fixtures.
"""

from __future__ import annotations

import re
from decimal import Decimal, localcontext

from screamingface_engine.combine.ports import (
    DECIMAL_CONTEXT,
    Answer,
    CombineInput,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SpecInvalid,
    TallyRow,
    canonical_decimal,
)

# WHY only this form: it is what numeric@1 writes (see reduce.py `_CANONICAL_NUMBER`).
_CANONICAL_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def _rows(reduction: Reduction, op_id: str) -> tuple[TallyRow, ...]:
    if not reduction.tally:
        raise SpecInvalid(f"{op_id} needs a tally")
    return reduction.tally


def _tie_and_agreement(rows: tuple[TallyRow, ...], op_id: str) -> tuple[bool, float]:
    with localcontext(DECIMAL_CONTEXT):
        total = sum((row.score for row in rows), Decimal(0))
        if total == 0:
            raise SpecInvalid(f"{op_id} needs a tally with a positive total")
        agreement = float(rows[0].score / total)
    return len(rows) > 1 and rows[1].score == rows[0].score, agreement


def first_holder(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """First member, in author order, holding the winning value."""
    rows = _rows(reduction, "first_holder@1")
    tie, agreement = _tie_and_agreement(rows, "first_holder@1")
    return Selection(chosen=(rows[0].holders[0],), tie=tie, agreement=agreement)


def max_weight_holder(
    reduction: Reduction, combine_input: CombineInput, args: OpArgs, /
) -> Selection:
    """Highest-weight member holding the winning value; the first maximum wins."""
    rows = _rows(reduction, "max_weight_holder@1")
    weights = {
        answer.member_id: answer.weight
        for answer in combine_input.answers
        if answer.weight is not None
    }
    if not all(member in weights for member in rows[0].holders):
        raise SpecInvalid("max_weight_holder@1 needs weights")
    heaviest = max(rows[0].holders, key=lambda member: weights[member])
    tie, agreement = _tie_and_agreement(rows, "max_weight_holder@1")
    return Selection(chosen=(heaviest,), tie=tie, agreement=agreement)


def _number(answer: Answer) -> Decimal:
    if answer.value is None or _CANONICAL_NUMBER.fullmatch(answer.value) is None:
        raise SpecInvalid("nearest@1 needs numeric values")
    return Decimal(answer.value)


def _numbers(combine_input: CombineInput) -> list[tuple[str, Decimal]]:
    return [(answer.member_id, _number(answer)) for answer in combine_input.voters]


def _median(reduction: Reduction, op_id: str) -> Decimal:
    if reduction.statistic is None:
        raise SpecInvalid(f"{op_id} needs a median")
    return reduction.statistic


def nearest(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """Member whose value is nearest the median; the first at the minimum distance wins."""
    centre = _median(reduction, "nearest@1")
    voters = _numbers(combine_input)
    with localcontext(DECIMAL_CONTEXT):
        distances = [abs(number - centre) for _, number in voters]
        closest = min(distances)
        at_closest = [pair for pair, distance in zip(voters, distances) if distance == closest]
    member, chosen_value = at_closest[0]
    agreeing = sum(1 for _, number in voters if number == chosen_value)
    tie = len({number for _, number in at_closest}) > 1
    return Selection(chosen=(member,), tie=tie, agreement=agreeing / len(voters))


def value(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The median value itself, in canonical numeric form."""
    return Selection(chosen=(), output=canonical_decimal(_median(reduction, "value@1")))


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor(
        "first_holder",
        1,
        "select",
        "First member, in author order, holding the winning value.",
        first_holder,
    ),
    OperatorDescriptor(
        "max_weight_holder",
        1,
        "select",
        "Highest-weight member holding the winning value.",
        max_weight_holder,
    ),
    OperatorDescriptor(
        "nearest", 1, "select", "Member whose value is nearest the median.", nearest
    ),
    OperatorDescriptor("value", 1, "select", "The median value itself.", value),
)

__all__ = ["OPERATORS"]

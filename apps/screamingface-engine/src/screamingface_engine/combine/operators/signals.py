"""Signal operators: rank, pick or filter members by one named signal (OME-1289, E4a).

FEATURE: a spec ranks members by a number the core already read for each member (a cost, a latency,
a token count, a ``field:`` value), or keeps the members that pass a threshold or a regex check.
STORY: as a researcher, "the cheapest member's answer" and "the members that are at least 60% sure"
are enforced by the engine, the same way on every replay, and no model rewrites a member text.

Mental model: a stopwatch judge and a bouncer. The judge reads one number off each runner (the
core wrote it on the runner's card) and names the fastest, or the k fastest. The bouncer reads the
same card, or the runner's own words, and stamps a pass mark of 1 or 0 on each runner; the next
stage lets the stamped ones through. Neither one guesses a number that is not on the card.

INVARIANT: each operator is pure and holds no mutable state. Order always comes from the author
order of the members (a stable choice): ``best_holder`` walks ``combine_input.members``, never a
dict, so a tie goes to the first member.
AIDEV-NOTE: the v1 behavior (who is ranked, which tie wins, the pass-mark shape) is pinned by the
golden fixtures. A change is a new ``@version``, never an edit.
"""

from __future__ import annotations

import operator
from decimal import Decimal
from types import MappingProxyType
from typing import cast, get_args

from screamingface_engine.combine.operators.extract import check_regex_pattern, regex_finds
from screamingface_engine.combine.ports import (
    Answer,
    CombineInput,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SignalOrder,
    SignalRead,
    SpecInvalid,
    finite_float,
    is_signal_key,
)

_ORDERS = get_args(SignalOrder)
_COMPARE = MappingProxyType(
    {"gt": operator.gt, "ge": operator.ge, "lt": operator.lt, "le": operator.le, "eq": operator.eq}
)
_THRESHOLD_KEYS = frozenset({"key", "cmp", "value"})


def _check_by_signal_args(args: OpArgs) -> None:
    if (
        set(args) != {"key", "order"}
        or not is_signal_key(args["key"])
        or args["order"] not in _ORDERS
    ):
        raise SpecInvalid(
            'by_signal@1 takes exactly {"key": a known signal key, "order": "max" | "min"}'
        )


def _by_signal_read(args: OpArgs) -> SignalRead:
    return SignalRead(cast("str", args["key"]), cast("SignalOrder", args["order"]))


def by_signal(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Each voter's score is its value of the signal; a voter without it is not ranked.

    Only a member that answered is scored (a member that failed is never ranked, also when it has
    an accounting number). The raw value is the score: no rounding and no rescale.
    """
    key = cast("str", args["key"])  # check_args ran first
    scores = {
        answer.member_id: Decimal(repr(value))
        for answer in combine_input.voters
        if (value := answer.signals.get(key)) is not None
    }
    if not scores:
        raise NoVotes("by_signal@1: no voter has the signal", reason="no_votes")
    return Reduction(scores=MappingProxyType(scores))


def _check_best_holder_args(args: OpArgs) -> None:
    if set(args) != {"order"} or args["order"] not in _ORDERS:
        raise SpecInvalid('best_holder@1 takes exactly {"order": "max" | "min"}')


def best_holder(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The member with the highest (or lowest) score; the first at that score wins."""
    given = reduction.scores or {}
    ranked = [(member, given[member]) for member in combine_input.members if member in given]
    if not ranked:
        raise SpecInvalid("best_holder@1 needs scores")
    scores = [score for _, score in ranked]
    best = max(scores) if args["order"] == "max" else min(scores)
    holders = [member for member, score in ranked if score == best]
    return Selection(chosen=(holders[0],), tie=len(holders) > 1)


def _check_threshold(args: OpArgs) -> None:
    if not is_signal_key(args["key"]):
        raise SpecInvalid("filter@1 key must be a known signal key")
    cmp, value = args["cmp"], args["value"]
    if not isinstance(cmp, str) or cmp not in _COMPARE:
        raise SpecInvalid("filter@1 cmp must be gt, ge, lt, le or eq")
    if (cmp != "eq" and isinstance(value, bool)) or (
        not isinstance(value, bool) and finite_float(value) is None
    ):
        raise SpecInvalid("filter@1 value must be a finite number, or a boolean compared with eq")


def _check_filter_args(args: OpArgs) -> None:
    if set(args) == _THRESHOLD_KEYS:
        _check_threshold(args)
    elif "pattern" in args and set(args) <= {"pattern", "ignore_case"}:
        check_regex_pattern(args)
    else:
        raise SpecInvalid(
            'filter@1 takes {"key", "cmp", "value"} or {"pattern"} with an optional "ignore_case"'
        )


def _filter_read(args: OpArgs) -> SignalRead | None:
    return SignalRead(cast("str", args["key"])) if "key" in args else None


def _passes_threshold(answer: Answer, args: OpArgs) -> bool:
    number = answer.signals.get(cast("str", args["key"]))
    # A bool value compares as 1.0 or 0.0 (the signals hold floats); a missing number never passes.
    return number is not None and _COMPARE[cast("str", args["cmp"])](
        number, float(cast("float", args["value"]))
    )


def _passes(answer: Answer, combine_input: CombineInput, args: OpArgs) -> bool:
    if "key" in args:
        return _passes_threshold(answer, args)
    return regex_finds(combine_input.outputs[answer.member_id], args)


def filter_members(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """One pass mark for each voter: 1 when it passes the check, else 0.

    The threshold form reads the signal the core put on each member. The pattern form reads the
    member's original output through the regex@1 rule, never the extracted value. A member that
    failed has no mark and never passes.
    """
    marks = {
        answer.member_id: Decimal(1 if _passes(answer, combine_input, args) else 0)
        for answer in combine_input.voters
    }
    return Reduction(scores=MappingProxyType(marks))


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor(
        "by_signal",
        1,
        "reduce",
        "Each voter's score is the value of one signal; a voter without it is not ranked.",
        by_signal,
        # AIDEV-NOTE: the top level is read-only; the nested "properties" stays a plain dict because
        # ports.catalog_entry deep-copies the schema and a mappingproxy cannot be deep-copied.
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"key": {"type": "string"}, "order": {"enum": _ORDERS}},
                "required": ("key", "order"),
                "additionalProperties": False,
            }
        ),
        check_args=_check_by_signal_args,
        signal_read=_by_signal_read,
    ),
    OperatorDescriptor(
        "best_holder",
        1,
        "select",
        "The member with the highest or lowest score; ties go to author order.",
        best_holder,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"order": {"enum": _ORDERS}},
                "required": ("order",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_best_holder_args,
    ),
    OperatorDescriptor(
        "filter",
        1,
        "reduce",
        "Marks each voter that passes a signal threshold or a regex (RE2) check.",
        filter_members,
        args_schema=MappingProxyType(
            {
                "oneOf": (
                    {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "cmp": {"enum": ("gt", "ge", "lt", "le", "eq")},
                            "value": {"type": ("number", "boolean")},
                        },
                        "required": ("key", "cmp", "value"),
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "minLength": 1, "maxLength": 256},
                            "ignore_case": {"type": "boolean"},
                        },
                        "required": ("pattern",),
                        "additionalProperties": False,
                    },
                )
            }
        ),
        check_args=_check_filter_args,
        signal_read=_filter_read,
    ),
)

__all__ = ["OPERATORS"]

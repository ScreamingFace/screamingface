"""Selection operators: keep the top k originals, or join every original (OME-1289, E4a).

FEATURE: rank and concat hand the NEXT stage original member texts, never a rewrite. ``top_k``
keeps the k best-scored members in score order; ``join`` and ``all`` join every member, in author
order, with visible boundaries.
STORY: as a researcher, "focus on the best three" is enforced by the engine and not asked of a
prompt, and a multi-document hand-off does not go through a model that summarizes.

Mental model: a clerk who photocopies. Rank photocopies the k best pages in rank order and staples
them in one JSON envelope; concat photocopies every page in the order of the recipe and tapes a
divider between them. The clerk never rewords a page.

INVARIANT: each operator is pure and holds no mutable state; no model call. Order comes from the
author order of the members -- ties at a score keep it (a stable sort), and ``join`` walks
``combine_input.members``, never a dict.
WHY ``sorted(..., reverse=True)`` and not a negated key: the sort does no arithmetic, so it needs
no ``DECIMAL_CONTEXT``, and a Decimal comparison is exact. Negating a score would round it to the
thread's default 28-digit context, and two long numeric field values could then compare equal.
``reverse=True`` keeps equal scores in author order.
AIDEV-NOTE: the selection JSON shape, the cut-tie rule and the collision rule are v1 behavior
pinned by the golden fixtures. A change is a new ``@version``, never an edit.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import cast

from screamingface_engine.combine.ports import (
    CombineInput,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SpecInvalid,
    canonical_json,
)

_MAX_K = 256
_MAX_SEPARATOR_CHARS = 1024


def _check_top_k_args(args: OpArgs) -> None:
    k = args.get("k")
    if set(args) != {"k"} or isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= _MAX_K:
        raise SpecInvalid(f'top_k@1 takes exactly {{"k": an integer from 1 to {_MAX_K}}}')


def top_k(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The k highest-scored members in score order; the output is the selection JSON.

    A tie keeps author order (stable sort). ``tie`` says the cut fell inside a group of equal
    scores: the last kept member and the first dropped one have the same score.
    """
    k = cast("int", args["k"])  # check_args ran first
    scores = reduction.scores
    if scores is None:
        raise SpecInvalid("top_k@1 needs scores")
    ranked = sorted(
        ((member, scores[member]) for member in combine_input.members if member in scores),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if len(ranked) < k:
        raise NoVotes(
            f"top_k@1 needs {k} scored members, {len(ranked)} have a score", reason="cut_not_met"
        )
    chosen = tuple(member for member, _ in ranked[:k])
    selected = [{"id": member, "text": combine_input.outputs[member]} for member in chosen]
    return Selection(
        chosen=chosen,
        output=canonical_json({"selected": selected}),
        tie=len(ranked) > k and ranked[k - 1][1] == ranked[k][1],
    )


def _check_join_args(args: OpArgs) -> None:
    separator, label = args.get("separator"), args.get("label")
    if (
        set(args) != {"separator", "label"}
        or not isinstance(separator, str)
        or not 1 <= len(separator) <= _MAX_SEPARATOR_CHARS
        or not isinstance(label, bool)
    ):
        raise SpecInvalid(
            f'join@1 takes exactly {{"separator": 1 to {_MAX_SEPARATOR_CHARS} characters,'
            ' "label": a boolean}'
        )


def _has_extra_separator(joined: str, separator: str, boundaries: int) -> bool:
    """Whether ``separator`` occurs more often (overlaps counted) than the ``boundaries`` need.

    Each boundary holds exactly one match, at its own start, so any further match is a collision.
    The scan stops at the first extra match and builds no list.
    """
    found, position = 0, joined.find(separator)
    while position != -1:
        found += 1
        if found > boundaries:
            return True
        position = joined.find(separator, position + 1)
    return False


def join(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Every member text, in author order, joined by the separator.

    Every member takes a slot, also an empty one and one marked ``too_large``. The collision flag
    says the separator also occurs inside a part, or overlaps a boundary, so the boundaries are not
    unique; the text is never changed for it.
    """
    separator = cast("str", args["separator"])  # check_args ran first
    parts = [
        f"[{member}]\n{combine_input.outputs[member]}"
        if args["label"]
        else combine_input.outputs[member]
        for member in combine_input.members
    ]
    joined = separator.join(parts)
    return Reduction(
        text=joined, separator_collision=_has_extra_separator(joined, separator, len(parts) - 1)
    )


def all_members(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """Every member is chosen; the output is the joined text."""
    if reduction.text is None:
        raise SpecInvalid("all@1 needs a joined text")
    return Selection(chosen=combine_input.members, output=reduction.text)


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor(
        "top_k",
        1,
        "select",
        "The k members with the highest scores, in score order.",
        top_k,
        # AIDEV-NOTE: the top level is read-only; the nested "properties" stays a plain dict because
        # ports.catalog_entry deep-copies the schema and a mappingproxy cannot be deep-copied.
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"k": {"type": "integer", "minimum": 1, "maximum": _MAX_K}},
                "required": ("k",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_top_k_args,
    ),
    OperatorDescriptor(
        "join",
        1,
        "reduce",
        "Every member text, joined in author order.",
        join,
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {
                    "separator": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _MAX_SEPARATOR_CHARS,
                    },
                    "label": {"type": "boolean"},
                },
                "required": ("separator", "label"),
                "additionalProperties": False,
            }
        ),
        check_args=_check_join_args,
    ),
    OperatorDescriptor("all", 1, "select", "Every member, with the joined text.", all_members),
)

__all__ = ["OPERATORS"]

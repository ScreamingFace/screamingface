"""Judge operators: a strict reading of a judge model's reply (OME-1289, E4a).

FEATURE: a judge model picks a member, and the Fusion's answer is that member's own text.
STORY: as a researcher, I never get the judge's prose as an answer. A reply that is not exactly
one member id (returns=label) or one JSON object with one finite score for each member
(returns=scores) fails the step with ``judge_reply_invalid``.

Mental model: a clerk who only counts a ballot written in the exact form. Anything else, even a
sensible sentence, is thrown out and the case fails; the clerk never guesses what the judge meant.

INVARIANT: each operator is pure and holds no mutable state; there is NO fallback branch (a
parse failure always raises). A message names the rule, never the judge's text.
WHY not ``shared_grading/judge_evidence.py``: that parser is lenient on presentation and its
failures are retryable. Here the format is the contract, and the failure is permanent.
AIDEV-NOTE: the label format, the whole-reply fence rule and the 64 KiB cap are v1 behavior
pinned by the golden fixtures. A change is a new ``@version``, never an edit.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from decimal import Decimal
from types import MappingProxyType

from screamingface_engine.combine.ports import (
    CombineInput,
    JudgeReading,
    JudgeReplyInvalid,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SpecInvalid,
    loads_bounded,
    utf8_exceeds,
)

MAX_JUDGE_REPLY_BYTES = 64 * 1024
_LABEL_INVALID = "the judge reply is not exactly one member id"
_SCORES_INVALID = "the judge reply is not one JSON object with a finite score for each member"
_TOO_LARGE = "the judge reply exceeds 64 KiB"
_FENCE = "```"
# WHY only this form: it is what numeric@1 writes (see reduce.py `_CANONICAL_NUMBER`).
_CANONICAL_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def parse_label(raw: str, members: Sequence[str]) -> str:
    """The one member id ``raw`` names. Only surrounding whitespace is trimmed (``str.strip``)."""
    label = raw.strip()
    if label not in members:
        raise JudgeReplyInvalid(_LABEL_INVALID)
    return label


def _unfenced(text: str) -> str:
    """``text`` itself, or the body of it when the WHOLE reply is one fence (no tag or ``json``)."""
    if not (text.startswith(_FENCE) and text.endswith(_FENCE) and len(text) >= 2 * len(_FENCE)):
        return text
    tag, newline, body = text[len(_FENCE) : -len(_FENCE)].partition("\n")
    if not newline or tag.strip() not in ("", "json"):
        raise JudgeReplyInvalid(_SCORES_INVALID)
    return body


def _score(value: object) -> float:
    """A JSON number (never a bool) as a finite float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JudgeReplyInvalid(_SCORES_INVALID)
    try:
        number = float(value)
    except OverflowError as exc:
        raise JudgeReplyInvalid(_SCORES_INVALID) from exc
    if not math.isfinite(number):
        raise JudgeReplyInvalid(_SCORES_INVALID)
    return number


def parse_scores(raw: str, members: Sequence[str]) -> dict[str, float]:
    """One finite score for each member, in author order; the reply's key order is ignored."""
    try:
        decoded = loads_bounded(_unfenced(raw.strip()), unique_keys=True)
    except ValueError as exc:
        raise JudgeReplyInvalid(_SCORES_INVALID) from exc
    if (
        not isinstance(decoded, dict)
        or len(decoded) != len(members)
        or set(decoded) != set(members)
    ):
        raise JudgeReplyInvalid(_SCORES_INVALID)
    return {member: _score(decoded[member]) for member in members}


def _judge_text(combine_input: CombineInput, op_id: str) -> str:
    raw = combine_input.signals.get("judge")
    if raw is None:
        raise SpecInvalid(f"{op_id} needs the judge signal")
    if utf8_exceeds(raw, MAX_JUDGE_REPLY_BYTES):
        raise JudgeReplyInvalid(_TOO_LARGE)
    return raw


def label(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """The member the judge named. Any spec member is valid: the judge saw every text."""
    raw = _judge_text(combine_input, "label@1")
    return Reduction(judge=JudgeReading(raw, "label", parse_label(raw, combine_input.members)))


def _value_scores(combine_input: CombineInput) -> Reduction:
    scores: dict[str, Decimal] = {}
    for answer in combine_input.voters:
        if answer.value is None or _CANONICAL_NUMBER.fullmatch(answer.value) is None:
            raise SpecInvalid("scores@1 needs numeric values")
        scores[answer.member_id] = Decimal(answer.value)
    return Reduction(scores=MappingProxyType(scores))


def scores(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """One score per member: from a strict judge reply, or from the voters' numeric values."""
    if args["source"] == "values":
        return _value_scores(combine_input)
    raw = _judge_text(combine_input, "scores@1")
    parsed = parse_scores(raw, combine_input.members)
    return Reduction(
        scores=MappingProxyType({member: Decimal(repr(score)) for member, score in parsed.items()}),
        judge=JudgeReading(raw, "scores", MappingProxyType(parsed)),
    )


def _check_scores_args(args: OpArgs) -> None:
    if set(args) != {"source"} or args["source"] not in ("judge", "values"):
        raise SpecInvalid('scores@1 takes exactly {"source": "judge" | "values"}')


def by_label(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The member the judge label names."""
    judge = reduction.judge
    if judge is None or judge.returns != "label" or not isinstance(judge.parsed, str):
        raise SpecInvalid("by_label@1 needs a label judge reading")
    return Selection(chosen=(judge.parsed,))


def max_score(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    """The member with the highest score; the first at that score, in author order, wins."""
    given = reduction.scores or {}
    ranked = [(member, given[member]) for member in combine_input.members if member in given]
    if not ranked:
        raise SpecInvalid("max_score@1 needs scores")
    best = max(score for _, score in ranked)
    holders = [member for member, score in ranked if score == best]
    return Selection(chosen=(holders[0],), tie=len(holders) > 1)


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor(
        "label",
        1,
        "reduce",
        "The one member id a judge reply names, parsed strictly.",
        label,
    ),
    OperatorDescriptor(
        "scores",
        1,
        "reduce",
        "One score per member, from a strict judge reply or numeric values.",
        scores,
        # AIDEV-NOTE: the top level is read-only; the nested "properties" stays a plain dict because
        # ports.catalog_entry deep-copies the schema and a mappingproxy cannot be deep-copied.
        args_schema=MappingProxyType(
            {
                "type": "object",
                "properties": {"source": {"enum": ("judge", "values")}},
                "required": ("source",),
                "additionalProperties": False,
            }
        ),
        check_args=_check_scores_args,
    ),
    OperatorDescriptor("by_label", 1, "select", "The member the judge label names.", by_label),
    OperatorDescriptor(
        "max_score",
        1,
        "select",
        "The member with the highest score; ties go to author order.",
        max_score,
    ),
)

__all__ = ["MAX_JUDGE_REPLY_BYTES", "OPERATORS", "parse_label", "parse_scores"]

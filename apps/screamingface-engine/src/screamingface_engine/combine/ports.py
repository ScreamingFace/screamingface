"""Ports of the deterministic combine framework (OME-1289, E4a).

FEATURE: combine member answers without a synthesizer model, the same way on every replay.

This module is the ONE meeting point of the combine core (``spec``, ``registry``, ``evidence``,
``endpoint``) and the operator plugins (``combine/operators/*``). A plugin imports this module
and the standard library only (the url4-import guard treats ``url4.core`` as an engine import).
The core never imports a
plugin: ``combine/builtins.py`` is the one module that lists them, and the COMBINE_CORE rule in
``.claude/scripts/check_layering.py`` enforces both directions.

One combine call runs four stages over the members, always in author order:

1. extract   -- one member text -> a raw value, or a status          (``Extractor``)
2. normalize -- one raw value   -> a comparable value, or a status   (``Normalizer``)
3. reduce    -- every reading   -> one ``Reduction``                  (``ReduceOp``)
4. select    -- the reduction   -> one ``Selection``                  (``SelectOp``)

INVARIANT: an operator is a pure function of its arguments. No I/O, no clock, no environment, no
module-level mutable state, and no result that depends on dict or set iteration order. A behavior
change is a new ``@version``, never an edit: golden fixtures pin every registered id.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal
from types import MappingProxyType
from typing import ClassVar, Literal, Protocol

Stage = Literal["extract", "normalize", "reduce", "select"]
Reducer = Literal["vote", "median", "judge", "pick", "merge", "project", "rank", "concat"]
EvidenceKind = Literal["answer", "selection", "projection"]
ReadingStatus = Literal["voted", "empty", "not_numeric", "not_json", "field_missing", "too_large"]
OpArgs = Mapping[str, object]

STAGES: tuple[Stage, ...] = ("extract", "normalize", "reduce", "select")
MAX_JSON_DEPTH = 64
# WHY an explicit context: the decimal module's default context is thread-global and any caller
# may change it. Every operator that does Decimal arithmetic runs inside
# ``localcontext(DECIMAL_CONTEXT)`` (which works on a copy), so a sum or a mean never depends on
# what ran before it. 1000 digits keeps every sum and mean of v1 inputs exact.
DECIMAL_CONTEXT = Context(prec=1000, rounding=ROUND_HALF_EVEN)

_OPERATOR_NAME = re.compile(r"[a-z][a-z0-9_]{0,47}")


# --- declared failures ------------------------------------------------------------------------


class CombineError(Exception):
    """A declared, permanent combine failure; the endpoint raises it as ``ResolutionError``.

    INVARIANT: a message names ids, counts and limits only -- never member text, judge text or
    arg values. Each ``code`` is in ``DECLARED_FAILURE_CODES`` (benchmarks/contract.py).
    """

    code: ClassVar[str]


class SpecInvalid(CombineError):
    """The spec, the context, the params or an operator's args break the contract."""

    code = "combine_spec_invalid"


class OperatorUnknown(CombineError):
    """The spec names an operator id that is not registered."""

    code = "combine_operator_unknown"


class NoVotes(CombineError):
    """No member gave a usable value, or a cut cannot be met."""

    code = "combine_no_votes"


class InputTooLarge(CombineError):
    """A size cap was breached (spec, context, member count or output)."""

    code = "combine_input_too_large"


class JudgeReplyInvalid(CombineError):
    """A judge reply is not exactly the declared label or scores format."""

    code = "judge_reply_invalid"


# --- stage values -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StageResult:
    """One extract or normalize result: a value with status "voted", or the reason there is none."""

    value: str | None
    status: ReadingStatus

    def __post_init__(self) -> None:
        if (self.status == "voted") != (self.value is not None):
            raise ValueError("a StageResult carries a value exactly when its status is 'voted'")


def accepted(value: str) -> StageResult:
    """A usable stage value."""
    return StageResult(value, "voted")


def rejected(status: ReadingStatus) -> StageResult:
    """No usable value, and why."""
    return StageResult(None, status)


@dataclass(frozen=True, slots=True)
class MemberReading:
    """What the core read for one member: ``raw`` after extract, ``value`` after normalize.

    With no extract step (judge, concat) a readable member is "voted" with both values None.
    """

    member: str
    raw: str | None
    value: str | None
    status: ReadingStatus
    weight: Decimal | None


@dataclass(frozen=True, slots=True)
class CombineInput:
    """Everything a reduce or select step may read. ``outputs`` holds every member's original
    text (also members marked too_large); never iterate it for order -- use ``readings``."""

    readings: tuple[MemberReading, ...]
    outputs: Mapping[str, str]
    signals: Mapping[str, str]

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(reading.member for reading in self.readings)

    @property
    def voters(self) -> tuple[MemberReading, ...]:
        return tuple(reading for reading in self.readings if reading.status == "voted")


@dataclass(frozen=True, slots=True)
class TallyRow:
    value: str
    score: Decimal
    holders: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JudgeReading:
    raw: str
    returns: Literal["label", "scores"]
    parsed: str | Mapping[str, float]


@dataclass(frozen=True, slots=True)
class FieldReading:
    field: str
    rule: str
    values: Mapping[str, object]
    result: object


@dataclass(frozen=True, slots=True)
class Reduction:
    """What a reduce step found. Each reducer family fills its own part; the rest stay None.

    tally: vote families, rows sorted by score (high first) then first-holder position.
    statistic: median. scores: member -> score (judge scores, rank, numeric field).
    judge: judge reducers. fields: pick and merge. text: a text this step built for select to
    emit (merge JSON, projection JSON, joined text). separator_collision: concat only.
    """

    tally: tuple[TallyRow, ...] | None = None
    statistic: Decimal | None = None
    scores: Mapping[str, Decimal] | None = None
    judge: JudgeReading | None = None
    fields: tuple[FieldReading, ...] | None = None
    text: str | None = None
    separator_collision: bool | None = None


@dataclass(frozen=True, slots=True)
class Selection:
    """What a select step decided.

    ``output`` None: the answer is the ONE chosen member's own text, copied byte for byte by the
    core. ``output`` text: the step built the answer (median value, merge JSON, rank selection,
    joined text), and the evidence says ``built``.
    """

    chosen: tuple[str, ...]
    output: str | None = None
    tie: bool = False
    agreement: float | None = None


# --- the four ports -------------------------------------------------------------------------


class Extractor(Protocol):
    def __call__(self, text: str, args: OpArgs, /) -> StageResult: ...


class Normalizer(Protocol):
    def __call__(self, raw: str, args: OpArgs, /) -> StageResult: ...


class ReduceOp(Protocol):
    def __call__(self, combine_input: CombineInput, args: OpArgs, /) -> Reduction: ...


class SelectOp(Protocol):
    def __call__(
        self, reduction: Reduction, combine_input: CombineInput, args: OpArgs, /
    ) -> Selection: ...


ArgsCheck = Callable[[OpArgs], None]
Operator = Extractor | Normalizer | ReduceOp | SelectOp


def no_args(args: OpArgs) -> None:
    """The ``check_args`` of an operator that takes no args."""
    if args:
        raise SpecInvalid("this operator takes no args")


def _empty_schema() -> Mapping[str, object]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class OperatorDescriptor:
    """One registered operator: what ``GET /v1/operators`` lists and what the endpoint runs.

    ``args_schema`` is published as-is: ``{}`` for an operator without args, a JSON Schema object
    otherwise. ``check_args`` is what enforces the args, once per call, before any output is read.
    """

    name: str
    version: int
    stage: Stage
    summary: str
    run: Operator
    args_schema: Mapping[str, object] = field(default_factory=_empty_schema)
    check_args: ArgsCheck = no_args

    def __post_init__(self) -> None:
        version_ok = not isinstance(self.version, bool) and 1 <= self.version <= 999_999
        if _OPERATOR_NAME.fullmatch(self.name) is None or not version_ok:
            raise ValueError(f"invalid combine operator {self.name!r} version {self.version!r}")
        if self.stage not in STAGES:
            raise ValueError(f"invalid combine operator stage {self.stage!r}")

    @property
    def id(self) -> str:
        return f"{self.name}@{self.version}"

    def catalog_entry(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "stage": self.stage,
            "args_schema": copy.deepcopy(dict(self.args_schema)),
            "summary": self.summary,
        }


# --- shared pure helpers ----------------------------------------------------------------------


def canonical_json(value: object) -> str:
    """Sorted keys, no spaces, UTF-8 text, no NaN: the JSON form every built combine text takes."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def json_depth(value: object) -> int:
    """The container nesting depth of a decoded JSON value: a scalar is 0, ``[]`` is 1."""
    depth = 0
    level: list[object] = [value]
    while level:
        containers = [node for node in level if isinstance(node, (dict, list))]
        if not containers:
            break
        depth += 1
        level = [
            child
            for node in containers
            for child in (node.values() if isinstance(node, dict) else node)
        ]
    return depth


def _no_constant(name: str) -> object:
    raise ValueError(f"the JSON constant {name} is not allowed")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded = dict(pairs)
    if len(decoded) != len(pairs):
        raise ValueError("a JSON object repeats a key")
    return decoded


def loads_bounded(
    text: str, *, max_depth: int = MAX_JSON_DEPTH, unique_keys: bool = False
) -> object:
    """Decode JSON with no NaN/Infinity and at most ``max_depth`` levels; ``ValueError`` otherwise.

    WHY catch RecursionError: the C decoder recurses once per level and raises it near depth
    1000, so a hostile ``[[[[...`` fails fast instead of crashing; the walk catches 65..999.
    """
    try:
        value = json.loads(
            text,
            parse_constant=_no_constant,
            object_pairs_hook=_unique_keys if unique_keys else None,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc
    if json_depth(value) > max_depth:
        raise ValueError("JSON nesting is too deep")
    return value


def canonical_decimal(value: Decimal) -> str:
    """A finite Decimal as plain digits: no exponent, no trailing zeros, ``-0`` -> ``0``."""
    if not value.is_finite():
        raise ValueError("only a finite Decimal has a canonical form")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def utf8_exceeds(text: str, limit: int) -> bool:
    """Whether ``text`` takes more than ``limit`` bytes as UTF-8, without encoding short text."""
    if len(text) > limit:
        return True
    if len(text) * 4 <= limit:
        return False
    return len(text.encode("utf-8", "surrogatepass")) > limit


__all__ = [
    "DECIMAL_CONTEXT",
    "MAX_JSON_DEPTH",
    "STAGES",
    "ArgsCheck",
    "CombineError",
    "CombineInput",
    "EvidenceKind",
    "Extractor",
    "FieldReading",
    "InputTooLarge",
    "JudgeReading",
    "JudgeReplyInvalid",
    "MemberReading",
    "NoVotes",
    "Normalizer",
    "OpArgs",
    "Operator",
    "OperatorDescriptor",
    "OperatorUnknown",
    "ReadingStatus",
    "ReduceOp",
    "Reducer",
    "Reduction",
    "SelectOp",
    "Selection",
    "SpecInvalid",
    "Stage",
    "StageResult",
    "TallyRow",
    "accepted",
    "canonical_decimal",
    "canonical_json",
    "json_depth",
    "loads_bounded",
    "no_args",
    "rejected",
    "utf8_exceeds",
]

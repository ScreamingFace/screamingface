"""Ports of the deterministic combine framework (OME-1289, E4a).

FEATURE: combine member answers without a synthesizer model, the same way on every replay.

This module is the ONE meeting point of the combine core (``spec``, ``registry``, ``evidence``,
``endpoint``) and the operator plugins (``combine/operators/*``). A plugin imports this module
and the pure standard library plus ``re2``, and may import a sibling plugin's pure functions
(never its ``OPERATORS``); it imports no ``url4`` module and no other engine module (the
url4-import guard treats ``url4.core`` as an engine import). The core never imports a plugin:
``combine/builtins.py`` is the one module that lists them, and the COMBINE_CORE rule in
``.claude/scripts/check_layering.py`` enforces both directions, bans every ``url4`` import under
``combine/``, and bans I/O and nondeterminism modules in plugins.

One combine call runs four stages over the members, always in author order:

1. extract   -- one member text -> a raw value, or a status          (``Extractor``)
2. normalize -- one raw value   -> a comparable value, or a status   (``Normalizer``)
3. reduce    -- every answer    -> one ``Reduction``                  (``ReduceOp``)
4. select    -- the reduction   -> one ``Selection``                  (``SelectOp``)

Before reduce the core resolves the one signal the spec reads (a ``field:`` number from the member
text, each member's ``score:judge`` from the strict judge reply, or an accounting number through an
injected ``AccountingReader``) onto each ``Answer``.

INVARIANT: an operator is a pure function of its arguments. No I/O, no clock, no environment, no
module-level mutable state, and no result that depends on dict or set iteration order. A behavior
change is a new ``@version``, never an edit: golden fixtures pin every registered id.
"""

from __future__ import annotations

import contextlib
import copy
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_EVEN, Context, Decimal
from types import MappingProxyType
from typing import ClassVar, Literal, Protocol, cast

Stage = Literal["extract", "normalize", "reduce", "select"]
Reducer = Literal[
    "vote", "median", "judge", "pick", "merge", "project", "rank", "concat", "filter", "mean"
]
EvidenceKind = Literal["answer", "selection", "projection"]
ReadingStatus = Literal[
    "voted", "empty", "not_numeric", "not_json", "field_missing", "too_large", "no_match"
]
AnswerStatus = Literal["answered", "abstain", "fail"]
MemberStatus = Literal["answered", "fail"]  # I-A3: a member is never "abstain"
AbstainReason = Literal["no_votes", "cut_not_met", "output_missing"]
AnswerReason = Literal[
    "empty",
    "not_numeric",
    "not_json",
    "field_missing",
    "too_large",
    "no_match",
    # A quorum panel left the member out: it failed upstream and was optional (OME-1557).
    "missing",
    "no_votes",
    "cut_not_met",
    "output_missing",
]
ABSTAIN_REASONS: tuple[AbstainReason, ...] = ("no_votes", "cut_not_met", "output_missing")
SignalOrder = Literal["max", "min"]
OpArgs = Mapping[str, object]

STAGES: tuple[Stage, ...] = ("extract", "normalize", "reduce", "select")
MAX_JSON_DEPTH = 64
# The most text the core reads from one member output (extract, field signals, a select output).
MAX_OUTPUT_READ_BYTES = 1024 * 1024
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


class NoVotes(Exception):
    """Internal: a plugin asks the core to abstain. The core catches it (reduce or select only) and
    records result.status="abstain" with this reason; it is never a failure code."""

    def __init__(self, message: str = "", *, reason: AbstainReason = "no_votes") -> None:
        if reason not in ABSTAIN_REASONS:
            raise ValueError("unknown abstain reason")
        super().__init__(message or reason)
        self.reason: AbstainReason = reason


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


READING_TO_ANSWER: Mapping[ReadingStatus, tuple[MemberStatus, AnswerReason | None]] = (
    MappingProxyType(
        {
            "voted": ("answered", None),
            "empty": ("fail", "empty"),
            "not_numeric": ("fail", "not_numeric"),
            "not_json": ("fail", "not_json"),
            "field_missing": ("fail", "field_missing"),
            "too_large": ("fail", "too_large"),
            "no_match": ("fail", "no_match"),
        }
    )
)


def answer_status(status: object) -> tuple[MemberStatus, AnswerReason | None]:
    """Total map from a stage status to the member's (status, reason) (AR-D1).

    A status that is not a str, or not a key of ``READING_TO_ANSWER``, is a plugin bug and raises
    ``RuntimeError``; there is never a default.
    """
    if isinstance(status, str) and status in READING_TO_ANSWER:
        return READING_TO_ANSWER[cast("ReadingStatus", status)]
    raise RuntimeError("a combine stage returned an unknown status")


def _empty_signals() -> Mapping[str, float | None]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Answer:
    """What the core read for one member: ``raw`` after extract, ``value`` after normalize.

    ``status`` is "answered" or "fail" (I-A3: a member never abstains); ``reason`` is set exactly
    when the member failed. With no extract step (judge, concat) a readable member is "answered"
    with ``raw`` and ``value`` both None. ``signals`` holds only the signal the spec reads.
    """

    member_id: str
    raw: str | None
    value: str | None
    status: MemberStatus
    reason: AnswerReason | None
    signals: Mapping[str, float | None] = field(default_factory=_empty_signals)
    weight: Decimal | None = None

    def __post_init__(self) -> None:
        if self.status not in ("answered", "fail"):
            raise ValueError("an Answer status is 'answered' or 'fail'")
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("an Answer has a reason exactly when it failed")
        if self.status != "answered" and self.value is not None:
            raise ValueError("a failed Answer has no value")
        for number in self.signals.values():
            if number is not None and (
                isinstance(number, bool)
                or not isinstance(number, float)
                or not math.isfinite(number)
            ):
                raise ValueError("an Answer signal is None or a finite float")


@dataclass(frozen=True, slots=True)
class CombineInput:
    """Everything a reduce or select step may read. ``outputs`` holds every member's original
    text (also members marked too_large); never iterate it for order -- use ``answers``.

    ``input`` is the combine context ``input``, verbatim (E4b CI-I1). The endpoint always sets it;
    ``None`` means a test built the value without a context.
    """

    answers: tuple[Answer, ...]
    outputs: Mapping[str, str]
    signals: Mapping[str, str]
    input: str | None = None

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(answer.member_id for answer in self.answers)

    @property
    def voters(self) -> tuple[Answer, ...]:
        return tuple(answer for answer in self.answers if answer.status == "answered")

    @property
    def present(self) -> tuple[str, ...]:
        """The members that sent an output, in spec order.

        WHY: a quorum panel (OME-1557) leaves out an optional member that failed upstream. Every
        member is present otherwise, so this equals ``members`` for a context with ``outputs``.
        """
        return tuple(member for member in self.members if member in self.outputs)


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
    """One field-level rule applied by a pick or merge reducer.

    ``values`` and ``result`` hold JSON values only (str, int, float, bool, None, list, dict) --
    never Decimal or tuple. The evidence wire model validates them, and a value outside that set
    is a plugin bug raised as ``RuntimeError``.
    """

    field: str
    rule: str
    values: Mapping[str, object]
    result: object


@dataclass(frozen=True, slots=True)
class Reduction:
    """What a reduce step found. Each reducer family fills its own part; the rest stay None.

    tally: vote families, rows sorted by score (high first) then first-holder position.
    statistic: median. scores: member -> score (judge scores, rank, numeric field, signal values,
    filter pass marks).
    judge: judge reducers. fields: pick and merge. text: a text this step built for select to
    emit (merge JSON, projection JSON, joined text). separator_collision: concat only.
    participants: the members a weighted reduce step used, in author order (None: every voter).
    nearest@1 picks only among them (E4b P9, ans:Q2).
    """

    tally: tuple[TallyRow, ...] | None = None
    statistic: Decimal | None = None
    scores: Mapping[str, Decimal] | None = None
    judge: JudgeReading | None = None
    fields: tuple[FieldReading, ...] | None = None
    text: str | None = None
    separator_collision: bool | None = None
    participants: tuple[str, ...] | None = None


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
    ``signal_read`` (reduce only) tells the core which signal these args read; it is not published.
    ``envelope`` (select only) says the output is the selection envelope, so an abstain of the
    call hands on the empty envelope (E4b fix 2026-10-14); it is not published.
    """

    name: str
    version: int
    stage: Stage
    summary: str
    run: Operator
    args_schema: Mapping[str, object] = field(default_factory=_empty_schema)
    check_args: ArgsCheck = no_args
    signal_read: Callable[[OpArgs], SignalRead | None] | None = None
    envelope: bool = False

    def __post_init__(self) -> None:
        version_ok = not isinstance(self.version, bool) and 1 <= self.version <= 999_999
        if _OPERATOR_NAME.fullmatch(self.name) is None or not version_ok:
            raise ValueError(f"invalid combine operator {self.name!r} version {self.version!r}")
        if self.stage not in STAGES:
            raise ValueError(f"invalid combine operator stage {self.stage!r}")
        if self.signal_read is not None and self.stage != "reduce":
            raise ValueError("only a reduce operator may declare a signal_read")
        if self.envelope and self.stage != "select":
            raise ValueError("only a select operator may hand on the envelope")

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


# --- signals ----------------------------------------------------------------------------------
# AIDEV-NOTE: a copy of url4's field-path grammar (dag/semantics/ensemble.py `_PATH`), extended with
# a leading `[N]` segment; it lives in ports so json_field@1 (unit 2) and the core share one walk.
_FIELD_KEY = r"[A-Za-z_][A-Za-z0-9_]*"
_FIELD_INDEX = r"\[(?:0|[1-9][0-9]*)\]"
FIELD_PATH = re.compile(rf"(?:{_FIELD_KEY}|{_FIELD_INDEX})(?:\.{_FIELD_KEY}|{_FIELD_INDEX})*")
_FIELD_STEP = re.compile(rf"\.?({_FIELD_KEY})|\[(0|[1-9][0-9]*)\]")
_FENCE_OPEN = "```json"
_FENCE_CLOSE = "```"


def decode_json_reply(text: str) -> object:
    """The whole trimmed text as JSON, else the last ```json fenced block; ValueError if neither."""
    try:
        return loads_bounded(text.strip())
    except ValueError:
        pass
    opened = text.rfind(_FENCE_OPEN)
    closed = text.find(_FENCE_CLOSE, opened + len(_FENCE_OPEN))
    if opened < 0 or closed < 0:
        raise ValueError("no JSON and no fenced block")
    return loads_bounded(text[opened + len(_FENCE_OPEN) : closed])


def walk_field_path(node: object, path: str) -> tuple[bool, object]:
    """Follow a FIELD_PATH-valid ``path`` through ``node``: (found, value)."""
    for step in _FIELD_STEP.finditer(path):
        key, index = step.group(1), step.group(2)
        if key is not None and isinstance(node, dict) and key in node:
            node = node[key]
        elif index is not None and isinstance(node, list) and int(index) < len(node):
            node = node[int(index)]
        else:
            return False, None
    return True, node


def field_value_text(value: object) -> str:
    """A JSON field value as answer text: a string as it is, ``null`` as ``""``, any other value
    as canonical JSON. ValueError: a number with no canonical form (``1e999`` decodes to inf).

    The one field-text rule of ``json_field@1`` and of a select step's ``output`` field.
    """
    if value is None or isinstance(value, str):
        return value or ""
    return canonical_json(value)


ACCOUNTING_SIGNALS: tuple[str, ...] = ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
FIELD_SIGNAL_PREFIX = "field:"
JUDGE_SIGNAL = "score:judge"  # the SDK's S/_signals.py JUDGE_SIGNAL (STU conformance)


def is_signal_key(key: object) -> bool:
    """I-S1: an accounting key, score:judge, or field:<FIELD_PATH>."""
    if not isinstance(key, str):
        return False
    if key in ACCOUNTING_SIGNALS or key == JUDGE_SIGNAL:
        return True
    return key.startswith(FIELD_SIGNAL_PREFIX) and (
        FIELD_PATH.fullmatch(key[len(FIELD_SIGNAL_PREFIX) :]) is not None
    )


def finite_float(value: object) -> float | None:
    """A finite float from an int, float or Decimal; None for a bool, anything else, a value too
    large for a float, or a non-finite number."""
    number: float | None = None
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        with contextlib.suppress(OverflowError):  # an int too large for a float
            number = float(value)
    return number if number is not None and math.isfinite(number) else None


def field_signal_value(text: str, path: str) -> float | None:
    """decode_json_reply -> walk_field_path; bool -> 1.0/0.0 (before ``finite_float``, which rejects
    bool); int/float -> float when finite;
    anything else, not JSON, or path absent -> None. Never raises (I-S2, SG-D8, SG-D11)."""
    try:
        found, value = walk_field_path(decode_json_reply(text), path)
    except ValueError:
        return None
    if not found:
        return None
    return float(value) if isinstance(value, bool) else finite_float(value)


# --- the selection envelope (E4b selection-input) -------------------------------------------


def selection_envelope(chosen: Sequence[str], combine_input: CombineInput) -> str:
    """The selection JSON: the Fusion's input and the chosen members' original texts, in order.

    ``chosen`` empty gives the empty envelope ``{"input":"...","selected":[]}`` that an abstained
    Rank or Filter hands to the next stage (E4b fix, 2026-10-14).
    WHY ``None`` is left out: a ``CombineInput`` built without a context (a test helper) has no
    input. The endpoint always sets it, so every combine call writes the ``input`` key.
    """
    selected = [{"id": member, "text": combine_input.outputs[member]} for member in chosen]
    envelope: dict[str, object] = {"selected": selected}
    if combine_input.input is not None:
        envelope["input"] = combine_input.input
    return canonical_json(envelope)


# --- select output (E4b pick-output) ---------------------------------------------------------
OUTPUT_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")  # the SDK's S/fields.py _FIELD_NAME


def check_output_arg(args: OpArgs, op_id: str) -> None:
    """The optional ``output`` arg of a select step: absent, or a top-level field name (CS-I3)."""
    if "output" not in args:
        return
    output = args["output"]
    if not isinstance(output, str) or OUTPUT_FIELD.fullmatch(output) is None:
        raise SpecInvalid(f"{op_id} output must be a top-level field name of 1 to 64 characters")


def output_field_text(text: str, name: str) -> str | None:
    """The top-level field ``name`` of one member reply, as answer text; None when it is missing.

    Read with the json_field@1 reader (``decode_json_reply``: the trimmed text, else the last
    fenced json block; depth at most 64) after the 1 MiB read cap. A JSON string is returned as
    it is; any other JSON value as canonical JSON. Over the cap, not JSON, not an object, no key,
    ``null``, a blank string, or a number with no canonical form (``1e999``) is None.
    """
    value = ""
    if not utf8_exceeds(text, MAX_OUTPUT_READ_BYTES):
        # ValueError: not JSON, or a number with no canonical form (1e999).
        with contextlib.suppress(ValueError):
            _, found = walk_field_path(decode_json_reply(text), name)
            value = field_value_text(found)
    return value if value.strip() else None


def with_output(
    selection: Selection, combine_input: CombineInput, args: OpArgs, op_id: str
) -> Selection:
    """``selection`` with ``output`` set to the chosen member's ``output`` field (E4b, P5).

    No ``output`` arg: ``selection`` unchanged, so the answer stays the member's own text.
    INVARIANT (ans:Q12): only the ONE chosen member is read. A missing field abstains with
    ``output_missing``; the runner-up is never used.
    """
    name = args.get("output")
    if name is None:
        return selection
    value = output_field_text(combine_input.outputs[selection.chosen[0]], str(name))
    if value is None:
        raise NoVotes(
            f"{op_id}: the chosen member has no usable output field", reason="output_missing"
        )
    return replace(selection, output=value)


# --- judge replies ----------------------------------------------------------------------------
MAX_JUDGE_REPLY_BYTES = 64 * 1024
_SCORES_INVALID = "the judge reply is not one JSON object with a finite score for each member"
_JUDGE_REPLY_TOO_LARGE = "the judge reply exceeds 64 KiB"
_JUDGE_FENCE = "```"  # the strict rule; decode_json_reply keeps its own loose _FENCE_CLOSE


def judge_reply(signals: Mapping[str, str], owner: str) -> str:
    """The context's ``judge`` text that ``owner`` (an op id, or score:judge) reads.

    SpecInvalid(f"{owner} needs the judge signal") when absent; JudgeReplyInvalid over 64 KiB.
    """
    raw = signals.get("judge")
    if raw is None:
        raise SpecInvalid(f"{owner} needs the judge signal")
    if utf8_exceeds(raw, MAX_JUDGE_REPLY_BYTES):
        raise JudgeReplyInvalid(_JUDGE_REPLY_TOO_LARGE)
    return raw


def _unfenced_judge_reply(text: str) -> str:
    """``text`` itself, or the body of it when the WHOLE reply is one fence (no tag or ``json``)."""
    fence = _JUDGE_FENCE
    if not (text.startswith(fence) and text.endswith(fence) and len(text) >= 2 * len(fence)):
        return text
    tag, newline, body = text[len(fence) : -len(fence)].partition("\n")
    if not newline or tag.strip() not in ("", "json"):
        raise JudgeReplyInvalid(_SCORES_INVALID)
    return body


def _judge_score(value: object) -> float:
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
        decoded = loads_bounded(_unfenced_judge_reply(raw.strip()), unique_keys=True)
    except ValueError as exc:
        raise JudgeReplyInvalid(_SCORES_INVALID) from exc
    if (
        not isinstance(decoded, dict)
        or len(decoded) != len(members)
        or set(decoded) != set(members)
    ):
        raise JudgeReplyInvalid(_SCORES_INVALID)
    return {member: _judge_score(decoded[member]) for member in members}


@dataclass(frozen=True, slots=True)
class SignalRead:
    """The one signal a spec reads, and the order a reducer asked for (None: no order)."""

    key: str
    order: SignalOrder | None = None


# Same shape as ``benchmarks/operation_outputs._Fingerprint``: (call.path, call.params).
CallFingerprint = tuple[str, tuple[tuple[str, str], ...]]
MemberSources = Mapping[str, Mapping[str, CallFingerprint]]


class AccountingReader(Protocol):
    """A port the adapter implements: member -> accounting key -> number (None: unknown)."""

    def __call__(self, sources: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]: ...


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
    "ABSTAIN_REASONS",
    "ACCOUNTING_SIGNALS",
    "DECIMAL_CONTEXT",
    "FIELD_PATH",
    "FIELD_SIGNAL_PREFIX",
    "JUDGE_SIGNAL",
    "MAX_JSON_DEPTH",
    "MAX_JUDGE_REPLY_BYTES",
    "MAX_OUTPUT_READ_BYTES",
    "OUTPUT_FIELD",
    "READING_TO_ANSWER",
    "STAGES",
    "AbstainReason",
    "AccountingReader",
    "Answer",
    "AnswerReason",
    "AnswerStatus",
    "ArgsCheck",
    "CallFingerprint",
    "CombineError",
    "CombineInput",
    "EvidenceKind",
    "Extractor",
    "FieldReading",
    "InputTooLarge",
    "JudgeReading",
    "JudgeReplyInvalid",
    "MemberSources",
    "MemberStatus",
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
    "SignalOrder",
    "SignalRead",
    "SpecInvalid",
    "Stage",
    "StageResult",
    "TallyRow",
    "accepted",
    "answer_status",
    "canonical_decimal",
    "canonical_json",
    "check_output_arg",
    "decode_json_reply",
    "field_signal_value",
    "field_value_text",
    "finite_float",
    "is_signal_key",
    "json_depth",
    "judge_reply",
    "loads_bounded",
    "no_args",
    "output_field_text",
    "parse_scores",
    "rejected",
    "selection_envelope",
    "utf8_exceeds",
    "walk_field_path",
    "with_output",
]

"""What one deterministic combine step read and decided for one Case (OME-1289).

INVARIANT: evidence never holds the ``output`` copies. The text of each member is on that member's
own operation ``output``; the evidence holds the readings, the tally or scores, and the choice. A
reading's ``raw``/``value`` is the extracted value, so an extractor such as ``whole@1`` or
``json_object@1`` puts the whole reply there.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from screamingface._immutable_json import freeze_json, freeze_mapping, thaw_json, thaw_mapping
from screamingface._report_primitives import _nonblank_text, _optional_number, _required_number
from screamingface._signals import is_signal_key
from screamingface.answer import (
    _MEMBER_ID,
    ABSTAIN_REASONS,
    ANSWER_REASONS,
    MEMBER_STATUSES,
    SIGNAL_ORDERS,
    AbstainReason,
    AnswerReason,
    MemberStatus,
    SignalOrder,
    frozen_signals,
)
from screamingface.reducer import REDUCER_KINDS, REDUCER_NAMES, _ReducerKind

COMBINE_EVIDENCE_SCHEMA = "screamingface.combine-evidence.v1"

type CombineKind = _ReducerKind
type ResultStatus = Literal["answered", "abstain"]
type JudgeReturns = Literal["label", "scores"]

# One source for each vocabulary: the Literal is the list, the set is derived from it.
_RESULT_STATUSES = frozenset(get_args(ResultStatus.__value__))
_RETURNS = frozenset(get_args(JudgeReturns.__value__))
_OPERATOR_ID = re.compile(r"[a-z][a-z0-9_]*@[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class CombineAnswerRow:
    """What the combine step read from one member's answer (the evidence Answer row, no text).

    INVARIANT (I-E1): the member text lives on the member operation's own output, never here.
    """

    member_id: str
    raw: str | None
    value: str | None
    status: MemberStatus
    reason: AnswerReason | None
    signals: Mapping[str, float | None]
    weight: float | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        _member_id(self.member_id, "Combine answer row member_id")
        _optional_text(self.raw, "Combine answer row raw")
        _optional_text(self.value, "Combine answer row value")
        _one_of(self.status, MEMBER_STATUSES, "Combine answer row status")
        if self.reason is not None:
            _one_of(self.reason, ANSWER_REASONS, "Combine answer row reason")
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("Combine answer row has a reason exactly when it failed")
        if self.status == "fail" and self.value is not None:
            raise ValueError("Combine answer row of a failed member has no value")
        if self.status == "fail" and self.reason in ABSTAIN_REASONS:
            raise ValueError(
                "Combine answer row of a failed member has a failure reason, not an abstain reason"
            )
        object.__setattr__(self, "signals", frozen_signals(self.signals, "Combine answer signals"))
        object.__setattr__(
            self, "weight", _optional_number(self.weight, "Combine answer row weight")
        )
        object.__setattr__(self, "score", _optional_number(self.score, "Combine answer row score"))

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "raw": self.raw,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
            "signals": dict(self.signals),
            "weight": self.weight,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class CombineResult:
    """The computed answer of the step: a member's text, a built text, or an abstain."""

    member_id: str | None
    value: str | None
    status: ResultStatus
    reason: AbstainReason | None

    def __post_init__(self) -> None:
        if self.member_id is not None:
            _member_id(self.member_id, "Combine result member_id")
        _optional_text(self.value, "Combine result value")
        _one_of(self.status, _RESULT_STATUSES, "Combine result status")
        if self.reason is not None:
            _one_of(self.reason, ABSTAIN_REASONS, "Combine result reason")
        if (self.reason is None) != (self.status == "answered"):
            raise ValueError("Combine result has a reason exactly when it abstained")
        if self.status == "abstain" and (self.value is not None or self.member_id is not None):
            raise ValueError("an abstain Combine result has no value and no member")

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CombineSignal:
    """The one signal the spec reads, and the order a reducer asked for (None: no order)."""

    key: str
    order: SignalOrder | None

    def __post_init__(self) -> None:
        if not is_signal_key(self.key):
            raise ValueError("Combine signal key must be an E4a signal key")
        if self.order is not None:
            _one_of(self.order, SIGNAL_ORDERS, "Combine signal order")

    def to_dict(self) -> dict[str, object]:
        return {"key": self.key, "order": self.order}


@dataclass(frozen=True, slots=True)
class CombineCut:
    """Stub (E4b part 2 unit 1 RED): the GREEN commit replaces it."""

    k: int
    order: SignalOrder

    def __post_init__(self) -> None:
        raise NotImplementedError("E4b part 2 unit 1: CombineCut")

    def to_dict(self) -> dict[str, object]:
        raise NotImplementedError("E4b part 2 unit 1: CombineCut")


@dataclass(frozen=True, slots=True)
class CombineTallyRow:
    """One candidate value of a vote: its score and the members holding it."""

    value: str
    score: float
    holders: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.value, "Combine tally value")
        object.__setattr__(self, "score", _required_number(self.score, "Combine tally score"))
        holders = _member_ids(self.holders, "Combine tally holders")
        if not holders:
            raise ValueError("Combine tally holders must not be empty")
        object.__setattr__(self, "holders", holders)

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "score": self.score, "holders": list(self.holders)}


@dataclass(frozen=True, slots=True, init=False)
class CombineJudgeReading:
    """What a judge reply was parsed into: one member label, or one score per member."""

    raw: str
    returns: JudgeReturns
    parsed: object

    def __init__(self, *, raw: str, returns: JudgeReturns, parsed: object) -> None:
        _text(raw, "Combine judge raw")
        _one_of(returns, _RETURNS, "Combine judge returns")
        frozen = freeze_json(parsed, "Combine judge parsed")
        if returns == "label" and not isinstance(frozen, str):
            raise TypeError("Combine judge parsed must be a member label for returns 'label'")
        if returns == "scores" and not isinstance(frozen, Mapping):
            raise TypeError("Combine judge parsed must be an object for returns 'scores'")
        object.__setattr__(self, "raw", raw)
        object.__setattr__(self, "returns", returns)
        object.__setattr__(self, "parsed", frozen)

    def to_dict(self) -> dict[str, object]:
        return {"raw": self.raw, "returns": self.returns, "parsed": thaw_json(self.parsed)}


@dataclass(frozen=True, slots=True, init=False)
class CombineFieldReading:
    """One merged field: the value each member gave, the rule applied, and the result."""

    field: str
    rule: str
    values: Mapping[str, object]
    result: object

    def __init__(
        self, *, field: str, rule: str, values: Mapping[str, object], result: object
    ) -> None:
        object.__setattr__(self, "field", _text(field, "Combine field reading field"))
        object.__setattr__(self, "rule", _text(rule, "Combine field reading rule"))
        object.__setattr__(self, "values", freeze_mapping(values, "Combine field reading values"))
        object.__setattr__(self, "result", freeze_json(result, "Combine field reading result"))

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "rule": self.rule,
            "values": thaw_mapping(self.values),
            "result": thaw_json(self.result),
        }


@dataclass(frozen=True, slots=True, init=False)
class CombineEvidence:
    """What one combine step read and decided for one Case. Never holds the ``output`` copies."""

    kind: CombineKind
    reducer: str
    operators: tuple[str, ...]
    members: tuple[CombineAnswerRow, ...]
    tally: tuple[CombineTallyRow, ...] | None
    judge: CombineJudgeReading | None
    fields: tuple[CombineFieldReading, ...] | None
    chosen: tuple[str, ...]
    built: bool
    agreement: float | None
    tie: bool
    median: str | None
    mean: str | None
    presentation_order: Literal["author"] | None
    separator_collision: bool | None
    signal: CombineSignal | None
    result: CombineResult
    dropped: int
    finish_reason: str

    def __init__(
        self,
        *,
        kind: CombineKind,
        reducer: str,
        operators: Sequence[str],
        members: Sequence[CombineAnswerRow],
        chosen: Sequence[str],
        built: bool,
        tie: bool,
        result: CombineResult,
        dropped: int,
        finish_reason: str,
        tally: Sequence[CombineTallyRow] | None = None,
        judge: CombineJudgeReading | None = None,
        fields: Sequence[CombineFieldReading] | None = None,
        agreement: float | None = None,
        median: str | None = None,
        mean: str | None = None,
        presentation_order: Literal["author"] | None = None,
        separator_collision: bool | None = None,
        signal: CombineSignal | None = None,
    ) -> None:
        _one_of(kind, REDUCER_KINDS, "Combine evidence kind")
        _one_of(reducer, REDUCER_NAMES, "Combine evidence reducer")
        selected_members = _typed_tuple(members, CombineAnswerRow, "Combine evidence members")
        member_ids = tuple(item.member_id for item in selected_members)
        if not member_ids or len(set(member_ids)) != len(member_ids):
            raise ValueError("Combine evidence members must be non-empty and unique")
        selected_tally = _optional_typed_tuple(tally, CombineTallyRow, "Combine evidence tally")
        selected_fields = _optional_typed_tuple(
            fields, CombineFieldReading, "Combine evidence fields"
        )
        _subset(chosen, member_ids, "Combine evidence chosen")
        for row in selected_tally or ():
            _subset(row.holders, member_ids, "Combine tally holders")
        selected_dropped = _dropped(dropped, selected_members)
        selected_result = _result(result, tuple(chosen), built)
        values = {
            "kind": kind,
            "reducer": reducer,
            "operators": _operator_ids(operators),
            "members": selected_members,
            "tally": selected_tally,
            "judge": _optional_instance(judge, CombineJudgeReading, "Combine evidence judge"),
            "fields": selected_fields,
            "chosen": tuple(chosen),
            "built": _flag(built, "Combine evidence built"),
            "agreement": _agreement(agreement),
            "tie": _flag(tie, "Combine evidence tie"),
            "median": _optional_text(median, "Combine evidence median"),
            "mean": _optional_text(mean, "Combine evidence mean"),
            "presentation_order": _presentation_order(presentation_order),
            "separator_collision": _optional_flag(
                separator_collision, "Combine evidence separator_collision"
            ),
            "signal": _optional_instance(signal, CombineSignal, "Combine evidence signal"),
            "result": selected_result,
            "dropped": selected_dropped,
            "finish_reason": _nonblank_text(finish_reason, "Combine evidence finish_reason"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": COMBINE_EVIDENCE_SCHEMA,
            "kind": self.kind,
            "reducer": self.reducer,
            "operators": list(self.operators),
            "members": [item.to_dict() for item in self.members],
            "tally": None if self.tally is None else [item.to_dict() for item in self.tally],
            "judge": None if self.judge is None else self.judge.to_dict(),
            "fields": None if self.fields is None else [item.to_dict() for item in self.fields],
            "chosen": list(self.chosen),
            "built": self.built,
            "agreement": self.agreement,
            "tie": self.tie,
            "median": self.median,
            # E4b P8: optional on the wire, only the mean reducer writes it
            **({} if self.mean is None else {"mean": self.mean}),
            "presentation_order": self.presentation_order,
            "separator_collision": self.separator_collision,
            "signal": None if self.signal is None else self.signal.to_dict(),
            "result": self.result.to_dict(),
            "dropped": self.dropped,
            "finish_reason": self.finish_reason,
        }


def _text(value: object, label: str) -> str:
    """Plain text as the Engine model carries it: any ``str``, blank included.

    WHY blank is allowed: a judge may reply with nothing, and one blank reading must not
    make the whole Report undecodable.
    """

    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _one_of(value: object, allowed: frozenset[str], label: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} must be one of {', '.join(sorted(allowed))}")


def _member_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _MEMBER_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must look like 'member_1'")
    return value


def _member_ids(values: object, label: str) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be an ordered sequence of member ids")
    selected = tuple(_member_id(value, label) for value in values)
    if len(set(selected)) != len(selected):
        raise ValueError(f"{label} must be unique")
    return selected


def _subset(values: Sequence[str], members: tuple[str, ...], label: str) -> None:
    selected = _member_ids(values, label)
    if unknown := [value for value in selected if value not in members]:
        raise ValueError(f"{label} names {unknown[0]!r}, which is not a member")


def _operator_ids(values: object) -> tuple[str, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError("Combine evidence operators must be an ordered sequence of ids")
    for value in values:
        if not isinstance(value, str) or _OPERATOR_ID.fullmatch(value) is None:
            raise ValueError("Combine evidence operators must be pinned ids like 'mode@1'")
    return tuple(values)


def _dropped(value: object, members: tuple[CombineAnswerRow, ...]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Combine evidence dropped must be an integer")
    if value < 0 or value != sum(row.status == "fail" for row in members):
        raise ValueError("Combine evidence dropped must count the failed members")
    return value


def _result(value: object, chosen: tuple[str, ...], built: object) -> CombineResult:
    if not isinstance(value, CombineResult):
        raise TypeError("Combine evidence result must be a CombineResult")
    if value.status == "abstain" and (chosen or built):
        raise ValueError("an abstained Combine evidence chooses and builds nothing")
    if value.member_id is not None and (built or chosen != (value.member_id,)):
        raise ValueError("a member Combine result must be the one chosen member and not built")
    return value


def _agreement(value: object) -> float | None:
    selected = _optional_number(value, "Combine evidence agreement")
    if selected is not None and not 0.0 <= selected <= 1.0:
        raise ValueError("Combine evidence agreement must be between 0 and 1")
    return selected


def _flag(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a bool")
    return value


def _optional_flag(value: object, label: str) -> bool | None:
    return None if value is None else _flag(value, label)


def _presentation_order(value: object) -> Literal["author"] | None:
    if value is None:
        return None
    if value != "author":
        raise ValueError("Combine evidence presentation_order must be 'author' or None")
    return "author"


def _typed_tuple[T](values: object, kind: type[T], label: str) -> tuple[T, ...]:
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise TypeError(f"{label} must be an ordered sequence")
    selected = tuple(values)
    if any(not isinstance(item, kind) for item in selected):
        raise TypeError(f"{label} must contain only {kind.__name__} values")
    return selected


def _optional_typed_tuple[T](values: object, kind: type[T], label: str) -> tuple[T, ...] | None:
    return None if values is None else _typed_tuple(values, kind, label)


def _optional_instance[T](value: object, kind: type[T], label: str) -> T | None:
    if value is not None and not isinstance(value, kind):
        raise TypeError(f"{label} must be a {kind.__name__} or None")
    return value


__all__ = [
    "COMBINE_EVIDENCE_SCHEMA",
    "CombineAnswerRow",
    "CombineEvidence",
    "CombineFieldReading",
    "CombineJudgeReading",
    "CombineResult",
    "CombineSignal",
    "CombineTallyRow",
]

"""What one deterministic combine step read and decided for one Case (OME-1289).

INVARIANT: evidence never holds member text. The text of each member is on that member's own
operation ``output``; the evidence holds only the readings, the tally or scores, and the choice.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from screamingface._immutable_json import freeze_json, freeze_mapping, thaw_json, thaw_mapping
from screamingface.reducer import REDUCER_NAMES

COMBINE_EVIDENCE_SCHEMA = "screamingface.combine-evidence.v1"

type CombineKind = Literal["answer", "selection", "projection"]
type ReadingStatus = Literal[
    "voted", "empty", "not_numeric", "not_json", "field_missing", "too_large"
]
type JudgeReturns = Literal["label", "scores"]

_KINDS = frozenset({"answer", "selection", "projection"})
_STATUSES = frozenset({"voted", "empty", "not_numeric", "not_json", "field_missing", "too_large"})
_RETURNS = frozenset({"label", "scores"})
_MEMBER_ID = re.compile(r"member_[1-9][0-9]*")
_OPERATOR_ID = re.compile(r"[a-z][a-z0-9_]*@[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class CombineMemberReading:
    """What the combine step read from one member's answer."""

    member: str
    raw: str | None
    value: str | None
    status: ReadingStatus
    weight: float | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        _member_id(self.member, "Combine member reading member")
        _optional_text(self.raw, "Combine member reading raw")
        _optional_text(self.value, "Combine member reading value")
        _one_of(self.status, _STATUSES, "Combine member reading status")
        object.__setattr__(self, "weight", _optional_number(self.weight, "reading weight"))
        object.__setattr__(self, "score", _optional_number(self.score, "reading score"))

    def to_dict(self) -> dict[str, object]:
        return {
            "member": self.member,
            "raw": self.raw,
            "value": self.value,
            "status": self.status,
            "weight": self.weight,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class CombineTallyRow:
    """One candidate value of a vote: its score and the members holding it."""

    value: str
    score: float
    holders: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.value, "Combine tally value")
        score = _optional_number(self.score, "tally score")
        if score is None:
            raise TypeError("Combine tally score must be a finite number")
        object.__setattr__(self, "score", score)
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
    """What one combine step read and decided for one Case. Never holds member text."""

    kind: CombineKind
    reducer: str
    operators: tuple[str, ...]
    members: tuple[CombineMemberReading, ...]
    tally: tuple[CombineTallyRow, ...] | None
    judge: CombineJudgeReading | None
    fields: tuple[CombineFieldReading, ...] | None
    chosen: tuple[str, ...]
    built: bool
    agreement: float | None
    tie: bool
    median: str | None
    presentation_order: Literal["author"] | None
    separator_collision: bool | None
    finish_reason: str

    def __init__(
        self,
        *,
        kind: CombineKind,
        reducer: str,
        operators: Sequence[str],
        members: Sequence[CombineMemberReading],
        chosen: Sequence[str],
        built: bool,
        tie: bool,
        finish_reason: str,
        tally: Sequence[CombineTallyRow] | None = None,
        judge: CombineJudgeReading | None = None,
        fields: Sequence[CombineFieldReading] | None = None,
        agreement: float | None = None,
        median: str | None = None,
        presentation_order: Literal["author"] | None = None,
        separator_collision: bool | None = None,
    ) -> None:
        _one_of(kind, _KINDS, "Combine evidence kind")
        _one_of(reducer, REDUCER_NAMES, "Combine evidence reducer")
        selected_members = _typed_tuple(members, CombineMemberReading, "Combine evidence members")
        member_ids = tuple(item.member for item in selected_members)
        if not member_ids or len(set(member_ids)) != len(member_ids):
            raise ValueError("Combine evidence members must be non-empty and unique")
        selected_tally = _optional_typed_tuple(tally, CombineTallyRow, "Combine evidence tally")
        selected_fields = _optional_typed_tuple(
            fields, CombineFieldReading, "Combine evidence fields"
        )
        _subset(chosen, member_ids, "Combine evidence chosen")
        for row in selected_tally or ():
            _subset(row.holders, member_ids, "Combine tally holders")
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
            "presentation_order": _presentation_order(presentation_order),
            "separator_collision": _optional_flag(
                separator_collision, "Combine evidence separator_collision"
            ),
            "finish_reason": _text(finish_reason, "Combine evidence finish_reason"),
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
            "presentation_order": self.presentation_order,
            "separator_collision": self.separator_collision,
            "finish_reason": self.finish_reason,
        }


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    if not value.strip():
        raise ValueError(f"{label} must not be blank")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{label} must be text or None")
    return value


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


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"Combine {label} must be a number or None")
    if not math.isfinite(value):
        raise ValueError(f"Combine {label} must be finite")
    return float(value)


def _agreement(value: object) -> float | None:
    selected = _optional_number(value, "evidence agreement")
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
    "CombineEvidence",
    "CombineFieldReading",
    "CombineJudgeReading",
    "CombineMemberReading",
    "CombineTallyRow",
]

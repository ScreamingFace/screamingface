"""Strict decoder for the Engine's per-operation combine evidence (OME-1289).

Follows the exemplar ``operation_accounting.py``: small typed helpers narrow each wire value
and the value classes validate their own invariants.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, cast

from screamingface._evaluation.operation_accounting import _exact_keys, _mapping
from screamingface.combine_evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    CombineEvidence,
    CombineFieldReading,
    CombineJudgeReading,
    CombineKind,
    CombineMemberReading,
    CombineTallyRow,
    JudgeReturns,
    ReadingStatus,
)
from screamingface.errors import ExecutionError

_EVIDENCE_KEYS = {
    "schema",
    "kind",
    "reducer",
    "operators",
    "members",
    "tally",
    "judge",
    "fields",
    "chosen",
    "built",
    "agreement",
    "tie",
    "median",
    "presentation_order",
    "separator_collision",
    "finish_reason",
}
_MEMBER_KEYS = {"member", "raw", "value", "status", "weight", "score"}
_TALLY_KEYS = {"value", "score", "holders"}
_JUDGE_KEYS = {"raw", "returns", "parsed"}
_FIELD_KEYS = {"field", "rule", "values", "result"}


def decode_combine_evidence(value: object, label: str) -> CombineEvidence | None:
    """Decode one evidence value, or preserve its absence; anything off-contract refuses.

    INVARIANT: strict. An unknown key, a missing key or a wrong schema id is an Engine/SDK
    version mismatch and fails loudly instead of dropping evidence the researcher relies on.
    """

    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _EVIDENCE_KEYS, label)
    if raw["schema"] != COMBINE_EVIDENCE_SCHEMA:
        raise ExecutionError(f"{label} schema must be {COMBINE_EVIDENCE_SCHEMA!r}")
    try:
        return CombineEvidence(
            kind=cast(CombineKind, _text(raw["kind"], f"{label} kind")),
            reducer=_text(raw["reducer"], f"{label} reducer"),
            operators=_texts(raw["operators"], f"{label} operators"),
            members=[
                _member_reading(item, f"{label} members[{index}]")
                for index, item in enumerate(_list(raw["members"], f"{label} members"))
            ],
            tally=_optional_list(raw["tally"], f"{label} tally", _tally_row),
            judge=_judge(raw["judge"], f"{label} judge"),
            fields=_optional_list(raw["fields"], f"{label} fields", _field_reading),
            chosen=_texts(raw["chosen"], f"{label} chosen"),
            built=_boolean(raw["built"], f"{label} built"),
            agreement=_optional_number(raw["agreement"], f"{label} agreement"),
            tie=_boolean(raw["tie"], f"{label} tie"),
            median=_optional_text(raw["median"], f"{label} median"),
            presentation_order=cast(
                Literal["author"] | None,
                _optional_text(raw["presentation_order"], f"{label} presentation_order"),
            ),
            separator_collision=_optional_boolean(
                raw["separator_collision"], f"{label} separator_collision"
            ),
            finish_reason=_text(raw["finish_reason"], f"{label} finish_reason"),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"{label} is invalid: {exc}") from exc


def _member_reading(value: object, label: str) -> CombineMemberReading:
    raw = _mapping(value, label)
    _exact_keys(raw, _MEMBER_KEYS, label)
    return CombineMemberReading(
        member=_text(raw["member"], f"{label} member"),
        raw=_optional_text(raw["raw"], f"{label} raw"),
        value=_optional_text(raw["value"], f"{label} value"),
        status=cast(ReadingStatus, _text(raw["status"], f"{label} status")),
        weight=_optional_number(raw["weight"], f"{label} weight"),
        score=_optional_number(raw["score"], f"{label} score"),
    )


def _tally_row(value: object, label: str) -> CombineTallyRow:
    raw = _mapping(value, label)
    _exact_keys(raw, _TALLY_KEYS, label)
    return CombineTallyRow(
        value=_text(raw["value"], f"{label} value"),
        score=_number(raw["score"], f"{label} score"),
        holders=_texts(raw["holders"], f"{label} holders"),
    )


def _judge(value: object, label: str) -> CombineJudgeReading | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _JUDGE_KEYS, label)
    return CombineJudgeReading(
        raw=_text(raw["raw"], f"{label} raw"),
        returns=cast(JudgeReturns, _text(raw["returns"], f"{label} returns")),
        parsed=raw["parsed"],
    )


def _field_reading(value: object, label: str) -> CombineFieldReading:
    raw = _mapping(value, label)
    _exact_keys(raw, _FIELD_KEYS, label)
    return CombineFieldReading(
        field=_text(raw["field"], f"{label} field"),
        rule=_text(raw["rule"], f"{label} rule"),
        values=_mapping(raw["values"], f"{label} values"),
        result=raw["result"],
    )


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ExecutionError(f"{label} must be a list")
    return value


def _optional_list[T](
    value: object, label: str, decode: Callable[[object, str], T]
) -> list[T] | None:
    if value is None:
        return None
    return [decode(item, f"{label}[{index}]") for index, item in enumerate(_list(value, label))]


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{label}[{index}]") for index, item in enumerate(_list(value, label)))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ExecutionError(f"{label} must be text")
    return value


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ExecutionError(f"{label} must be a boolean")
    return value


def _optional_boolean(value: object, label: str) -> bool | None:
    return None if value is None else _boolean(value, label)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExecutionError(f"{label} must be a number")
    return float(value)


def _optional_number(value: object, label: str) -> float | None:
    return None if value is None else _number(value, label)


__all__: list[str] = []

"""Strict decoder for the Engine's per-operation combine evidence (OME-1289).

Follows the exemplar ``operation_accounting.py``: small typed helpers narrow each wire value
and the value classes validate their own invariants.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, cast

from screamingface._evaluation.operation_accounting import _exact_keys, _mapping
from screamingface._signals import is_signal_key
from screamingface.answer import (
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
from screamingface.combine_evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    CombineAnswerRow,
    CombineCut,
    CombineEvidence,
    CombineFieldReading,
    CombineJudgeReading,
    CombineKind,
    CombineResult,
    CombineSignal,
    CombineTallyRow,
    JudgeReturns,
    ResultStatus,
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
    "signal",
    "result",
    "dropped",
    "finish_reason",
}
# E4b P8 mean (mean reducer only); E4b part 2 cut (top_k@1 only); E4b part 3 P11 declared
# (written only by a Fusion that declares signals).
_OPTIONAL_EVIDENCE_KEYS = frozenset({"mean", "cut", "declared"})
_MEMBER_KEYS = {"member_id", "raw", "value", "status", "reason", "signals", "weight", "score"}
_OPTIONAL_MEMBER_KEYS = frozenset({"rank"})  # E4b part 2: written only by a top_k@1 step
_CUT_KEYS = {"k", "order"}
_RESULT_KEYS = {"member_id", "value", "status", "reason"}
_SIGNAL_KEYS = {"key", "order"}
_RESULT_STATUSES = frozenset({"answered", "abstain"})
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
    _exact_keys(raw, _EVIDENCE_KEYS | {key for key in _OPTIONAL_EVIDENCE_KEYS if key in raw}, label)
    if raw["schema"] != COMBINE_EVIDENCE_SCHEMA:
        raise ExecutionError(f"{label} schema must be {COMBINE_EVIDENCE_SCHEMA!r}")
    declared = _declared(raw.get("declared"), f"{label} declared")
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
            mean=_optional_text(raw.get("mean"), f"{label} mean"),
            presentation_order=cast(
                Literal["author"] | None,
                _optional_text(raw["presentation_order"], f"{label} presentation_order"),
            ),
            separator_collision=_optional_boolean(
                raw["separator_collision"], f"{label} separator_collision"
            ),
            signal=_signal(raw["signal"], f"{label} signal", declared),
            cut=_cut(raw.get("cut"), f"{label} cut"),
            declared=declared,
            result=_result(raw["result"], f"{label} result"),
            dropped=_integer(raw["dropped"], f"{label} dropped"),
            finish_reason=_text(raw["finish_reason"], f"{label} finish_reason"),
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"{label} is invalid: {exc}") from exc


def _member_reading(value: object, label: str) -> CombineAnswerRow:
    raw = _mapping(value, label)
    _exact_keys(raw, _MEMBER_KEYS | {key for key in _OPTIONAL_MEMBER_KEYS if key in raw}, label)
    return CombineAnswerRow(
        member_id=_text(raw["member_id"], f"{label} member_id"),
        raw=_optional_text(raw["raw"], f"{label} raw"),
        value=_optional_text(raw["value"], f"{label} value"),
        status=cast(MemberStatus, _word(raw["status"], MEMBER_STATUSES, f"{label} status")),
        reason=cast(
            AnswerReason | None, _optional_word(raw["reason"], ANSWER_REASONS, f"{label} reason")
        ),
        signals=_signals(raw["signals"], f"{label} signals"),
        weight=_optional_number(raw["weight"], f"{label} weight"),
        score=_optional_number(raw["score"], f"{label} score"),
        rank=_optional_integer(raw.get("rank"), f"{label} rank"),
    )


def _result(value: object, label: str) -> CombineResult:
    raw = _mapping(value, label)
    _exact_keys(raw, _RESULT_KEYS, label)
    return CombineResult(
        member_id=_optional_text(raw["member_id"], f"{label} member_id"),
        value=_optional_text(raw["value"], f"{label} value"),
        status=cast(ResultStatus, _word(raw["status"], _RESULT_STATUSES, f"{label} status")),
        reason=cast(
            AbstainReason | None,
            _optional_word(raw["reason"], ABSTAIN_REASONS, f"{label} reason"),
        ),
    )


def _signal(
    value: object, label: str, declared: dict[str, dict[str, object]] | None
) -> CombineSignal | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _SIGNAL_KEYS, label)
    key = _text(raw["key"], f"{label} key")
    order = cast(SignalOrder | None, _optional_word(raw["order"], SIGNAL_ORDERS, f"{label} order"))
    if declared is not None and key in declared and not is_signal_key(key):
        return CombineSignal._declared(key, order)
    return CombineSignal(key=key, order=order)


def _declared(value: object, label: str) -> dict[str, dict[str, object]] | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    return {name: dict(_mapping(entry, f"{label} {name!r}")) for name, entry in raw.items()}


def _cut(value: object, label: str) -> CombineCut | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _CUT_KEYS, label)
    return CombineCut(
        k=_integer(raw["k"], f"{label} k"),
        order=cast(SignalOrder, _word(raw["order"], SIGNAL_ORDERS, f"{label} order")),
    )


def _signals(value: object, label: str) -> dict[str, float | None]:
    raw = _mapping(value, label)
    return dict(
        frozen_signals({key: _signal_number(item, label) for key, item in raw.items()}, label)
    )


def _signal_number(value: object, label: str) -> float | None:
    return None if value is None else _number(value, label)


def _word(value: object, allowed: frozenset[str], label: str) -> str:
    """A vocabulary word, checked here so the error names the field it came from."""

    selected = _text(value, label)
    if selected not in allowed:
        raise ExecutionError(f"{label} must be one of {', '.join(sorted(allowed))}")
    return selected


def _optional_word(value: object, allowed: frozenset[str], label: str) -> str | None:
    return None if value is None else _word(value, allowed, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutionError(f"{label} must be an integer")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


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

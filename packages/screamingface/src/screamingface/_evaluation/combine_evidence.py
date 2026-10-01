"""Strict decoder for the Engine's per-operation combine evidence (OME-1289)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from screamingface.combine_evidence import (
    COMBINE_EVIDENCE_SCHEMA,
    CombineEvidence,
    CombineFieldReading,
    CombineJudgeReading,
    CombineMemberReading,
    CombineTallyRow,
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
    members = [
        _reading(item, f"{label} members[{index}]")
        for index, item in enumerate(_sequence(raw["members"], f"{label} members"))
    ]
    try:
        return CombineEvidence(
            kind=raw["kind"],  # type: ignore[arg-type]
            reducer=raw["reducer"],  # type: ignore[arg-type]
            operators=_sequence(raw["operators"], f"{label} operators"),  # type: ignore[arg-type]
            members=[_build(CombineMemberReading, item) for item in members],
            tally=_optional_rows(raw["tally"], f"{label} tally", _tally_row),
            judge=_judge(raw["judge"], f"{label} judge"),
            fields=_optional_rows(raw["fields"], f"{label} fields", _field_reading),
            chosen=_sequence(raw["chosen"], f"{label} chosen"),  # type: ignore[arg-type]
            built=raw["built"],  # type: ignore[arg-type]
            agreement=raw["agreement"],  # type: ignore[arg-type]
            tie=raw["tie"],  # type: ignore[arg-type]
            median=raw["median"],  # type: ignore[arg-type]
            presentation_order=raw["presentation_order"],  # type: ignore[arg-type]
            separator_collision=raw["separator_collision"],  # type: ignore[arg-type]
            finish_reason=raw["finish_reason"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"{label} is invalid: {exc}") from exc


def _build[T](kind: Callable[..., T], keywords: Mapping[str, object]) -> T:
    return kind(**keywords)


def _reading(value: object, label: str) -> Mapping[str, object]:
    raw = _mapping(value, label)
    _exact_keys(raw, _MEMBER_KEYS, label)
    return raw


def _tally_row(value: object, label: str) -> CombineTallyRow:
    raw = _mapping(value, label)
    _exact_keys(raw, _TALLY_KEYS, label)
    return _wrapped(label, lambda: CombineTallyRow(**raw))  # type: ignore[arg-type]


def _field_reading(value: object, label: str) -> CombineFieldReading:
    raw = _mapping(value, label)
    _exact_keys(raw, _FIELD_KEYS, label)
    return _wrapped(label, lambda: CombineFieldReading(**raw))  # type: ignore[arg-type]


def _judge(value: object, label: str) -> CombineJudgeReading | None:
    if value is None:
        return None
    raw = _mapping(value, label)
    _exact_keys(raw, _JUDGE_KEYS, label)
    return _wrapped(label, lambda: CombineJudgeReading(**raw))  # type: ignore[arg-type]


def _optional_rows[T](
    value: object, label: str, decode: Callable[[object, str], T]
) -> list[T] | None:
    if value is None:
        return None
    return [decode(item, f"{label}[{index}]") for index, item in enumerate(_sequence(value, label))]


def _wrapped[T](label: str, build: Callable[[], T]) -> T:
    try:
        return build()
    except (TypeError, ValueError) as exc:
        raise ExecutionError(f"{label} is invalid: {exc}") from exc


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ExecutionError(f"{label} must be an object with text keys")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ExecutionError(f"{label} must be a list")
    return value


def _exact_keys(value: Mapping[str, object], required: set[str], label: str) -> None:
    present = set(value)
    if missing := sorted(required - present):
        raise ExecutionError(f"{label} is missing {missing[0]!r}")
    if unknown := sorted(present - required):
        raise ExecutionError(f"{label} contains unsupported field {unknown[0]!r}")


__all__: list[str] = []

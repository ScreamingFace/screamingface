"""The Answer vocabulary shared by combine evidence, Case views and the trace (OME-1289 gap).

INVARIANT: the Literals below are the E4a answer vocabulary of the Engine's combine/ports.py
(AnswerStatus, MemberStatus, AnswerReason, AbstainReason, SignalOrder); the sets are derived from
them so each vocabulary has one source.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, get_args

from screamingface._report_primitives import _optional_number

type AnswerStatus = Literal["answered", "abstain", "fail"]
type MemberStatus = Literal["answered", "fail"]
type AbstainReason = Literal["no_votes", "cut_not_met"]
type AnswerReason = Literal[
    "empty",
    "not_numeric",
    "not_json",
    "field_missing",
    "too_large",
    "no_match",
    "no_votes",
    "cut_not_met",
]
type SignalOrder = Literal["max", "min"]

ANSWER_STATUSES: frozenset[str] = frozenset(get_args(AnswerStatus.__value__))
MEMBER_STATUSES: frozenset[str] = frozenset(get_args(MemberStatus.__value__))
ANSWER_REASONS: frozenset[str] = frozenset(get_args(AnswerReason.__value__))
ABSTAIN_REASONS: frozenset[str] = frozenset(get_args(AbstainReason.__value__))
SIGNAL_ORDERS: frozenset[str] = frozenset(get_args(SignalOrder.__value__))
_MEMBER_ID = re.compile(r"member_[1-9][0-9]*")


def frozen_signals(value: object, label: str) -> Mapping[str, float | None]:
    """A frozen ``str -> finite float | None`` map (a missing signal is None, never an error)."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    frozen: dict[str, float | None] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{label} keys must be text")
        frozen[key] = _optional_number(item, f"{label} {key!r}")
    return MappingProxyType(frozen)


_ANSWER_KEYS = ("member_id", "text", "raw", "value", "status", "reason", "signals")


@dataclass(frozen=True, slots=True, kw_only=True)
class Answer:
    """What one member, or one combine step, answered (screamingface.answer.v1, erd s2).

    text is the member's original output joined through the Candidate operation DAG; None when the
    Engine could not attribute it. A computed Answer has member_id None unless a select chose one.
    """

    member_id: str | None
    text: str | None
    raw: str | None
    value: str | None
    status: AnswerStatus
    reason: AnswerReason | None
    signals: Mapping[str, float | None] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.member_id is not None and _MEMBER_ID.fullmatch(str(self.member_id)) is None:
            raise ValueError("Answer member_id must look like 'member_1' or be None")
        for name in ("text", "raw", "value"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                raise TypeError(f"Answer {name} must be text or None")
        _check_status(self)
        object.__setattr__(self, "signals", frozen_signals(self.signals, "Answer signals"))

    def __hash__(self) -> int:
        return hash(
            (
                self.member_id,
                self.text,
                self.raw,
                self.value,
                self.status,
                self.reason,
                tuple(sorted(self.signals.items())),
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "text": self.text,
            "raw": self.raw,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
            "signals": dict(self.signals),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> Answer:
        """Rebuild an Answer from its exact to_dict shape."""

        if not isinstance(value, Mapping):
            raise TypeError("an Answer is read from a mapping")
        if missing := [key for key in _ANSWER_KEYS if key not in value]:
            raise ValueError(f"Answer is missing {missing[0]!r}")
        if extra := sorted(set(value) - set(_ANSWER_KEYS)):
            raise ValueError(f"Answer has an unsupported field {extra[0]!r} (extra)")
        values = {key: value[key] for key in _ANSWER_KEYS}
        return cls(**values)  # type: ignore[arg-type]


def _check_status(answer: Answer) -> None:
    if answer.status not in ANSWER_STATUSES:
        raise ValueError(f"Answer status must be one of {', '.join(sorted(ANSWER_STATUSES))}")
    if answer.reason is not None and answer.reason not in ANSWER_REASONS:
        raise ValueError("Answer reason must be an answer reason")
    if (answer.reason is None) != (answer.status == "answered"):
        raise ValueError("Answer has a reason exactly when it did not answer")
    if answer.status != "answered" and answer.value is not None:
        raise ValueError("Answer has a value only when it answered")
    if answer.status == "abstain" and (
        answer.member_id is not None or answer.reason not in ABSTAIN_REASONS
    ):
        raise ValueError("an abstain Answer has no member and an abstain reason")
    if answer.status == "fail" and answer.reason in ABSTAIN_REASONS:
        raise ValueError("a failed Answer has a failure reason, not an abstain reason")


__all__ = ["Answer"]

"""The Answer vocabulary shared by combine evidence, Case views and the trace (OME-1289 gap).

INVARIANT: each Literal below is the one source of its words, and the sets are derived from it.
The words map to the Engine's combine/ports.py words (E4b part 2, review m8):

- SDK ``MemberStatus`` = Engine ``RecordStatus`` (the status of an evidence record), not the
  Engine ``MemberStatus`` (the status of the core ``Answer`` that an operator reads).
- SDK ``AnswerReason`` = Engine ``AnswerReason`` | Engine ``ExcludeReason``.
- SDK ``ExcludeReason`` = Engine ``ExcludeReason``.
- SDK ``AnswerStatus`` = Engine ``AnswerStatus`` | {"excluded"}: the Case view makes an
  ``Answer`` from an evidence record, so an excluded member keeps its status.
- SDK ``AbstainReason`` and ``SignalOrder`` = the Engine words of the same name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, get_args

from screamingface._report_primitives import _optional_number

# Not in ``__all__``: the schema id of the frozen field set, not public surface.
ANSWER_SCHEMA = "screamingface.answer.v1"
type AnswerStatus = Literal["answered", "abstain", "fail", "excluded"]
type MemberStatus = Literal["answered", "fail", "excluded"]
type AbstainReason = Literal["no_votes", "cut_not_met", "output_missing"]
type ExcludeReason = Literal["no_signal", "no_weight"]
type AnswerReason = Literal[
    "empty",
    "not_numeric",
    "not_json",
    "field_missing",
    "too_large",
    "no_match",
    # A quorum panel left the member out: it was optional and failed upstream (OME-1557).
    "missing",
    "no_votes",
    "cut_not_met",
    "output_missing",
    # A rule of the combine step left an answered member out (E4b part 2): no signal, no weight.
    "no_signal",
    "no_weight",
]
type SignalOrder = Literal["max", "min"]

ANSWER_STATUSES: frozenset[str] = frozenset(get_args(AnswerStatus.__value__))
MEMBER_STATUSES: frozenset[str] = frozenset(get_args(MemberStatus.__value__))
ANSWER_REASONS: frozenset[str] = frozenset(get_args(AnswerReason.__value__))
ABSTAIN_REASONS: frozenset[str] = frozenset(get_args(AbstainReason.__value__))
EXCLUDE_REASONS: frozenset[str] = frozenset(get_args(ExcludeReason.__value__))
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
    An excluded Answer (status "excluded") names its member, keeps its value, and has the reason
    no_signal or no_weight.
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
    if answer.status not in ("answered", "excluded") and answer.value is not None:
        raise ValueError("Answer has a value only when it answered or was excluded")
    if answer.status == "abstain" and (
        answer.member_id is not None or answer.reason not in ABSTAIN_REASONS
    ):
        raise ValueError("an abstain Answer has no member and an abstain reason")
    if answer.status == "fail" and answer.reason in ABSTAIN_REASONS:
        raise ValueError("a failed Answer has a failure reason, not an abstain reason")
    _check_excluded(answer)


def _check_excluded(answer: Answer) -> None:
    # WHY a helper: _check_status reached the complexity limit of ruff C901 and PLR0912.
    if (answer.status == "excluded") != (answer.reason in EXCLUDE_REASONS):
        raise ValueError("Answer has an exclude reason exactly when it was excluded")
    if answer.status == "excluded" and answer.member_id is None:
        raise ValueError("an excluded Answer names its member")


__all__ = ["Answer"]

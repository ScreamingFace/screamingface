"""The Answer vocabulary shared by combine evidence, Case views and the trace (OME-1289 gap).

INVARIANT: the Literals below are the E4a answer vocabulary of the Engine's combine/ports.py
(AnswerStatus, MemberStatus, AnswerReason, AbstainReason, SignalOrder); the sets are derived from
them so each vocabulary has one source.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
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


__all__: list[str] = []

"""Answer signal keys and the sf.signal seam (OME-1289 gap, signals I-S1, BU-E2).

INVARIANT: FIELD_PATH is the Engine's combine/ports.py field-path grammar, copied line for line;
STU/test_signal_key_conformance.py binds the copy. E4b adds declared signals through this seam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType

_FIELD_KEY = r"[A-Za-z_][A-Za-z0-9_]*"  # verbatim E/combine/ports.py
_FIELD_INDEX = r"\[(?:0|[1-9][0-9]*)\]"
FIELD_PATH = re.compile(rf"(?:{_FIELD_KEY}|{_FIELD_INDEX})(?:\.{_FIELD_KEY}|{_FIELD_INDEX})*")
ACCOUNTING_SIGNALS: tuple[str, ...] = ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
FIELD_SIGNAL_PREFIX = "field:"
JUDGE_SIGNAL = "score:judge"


def is_signal_key(key: object) -> bool:
    """I-S1: an accounting key, score:judge, or field:<FIELD_PATH>."""

    if not isinstance(key, str):
        return False
    if key in ACCOUNTING_SIGNALS or key == JUDGE_SIGNAL:
        return True
    return key.startswith(FIELD_SIGNAL_PREFIX) and (
        FIELD_PATH.fullmatch(key[len(FIELD_SIGNAL_PREFIX) :]) is not None
    )


_RESERVED = MappingProxyType(
    {
        "budget.remaining": (
            "budget.remaining is a request-level Budget value that E4c compares read; "
            "it is not an Answer signal"
        )
    }
)
_E4A_KEYS = "cost_usd, latency_ms, tokens_in, tokens_out, score:judge and field:<path>"


@dataclass(frozen=True, slots=True)
class Signal:
    """A named number on a member Answer, read by a reducer."""

    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("a signal key must be text")
        if self.key in _RESERVED:
            raise ValueError(_RESERVED[self.key])
        if not is_signal_key(self.key):
            raise ValueError(_rejection(self.key))

    def __repr__(self) -> str:
        return f"signal({self.key!r})"

    def _python(self) -> str:
        return f"sf.signal({self.key!r})"


def _rejection(key: str) -> str:
    if key.startswith(FIELD_SIGNAL_PREFIX):
        return "field signal path must be a JSON path like 'a', 'a.b' or 'a[0].b'"
    if key.startswith("logprob"):
        return f"{key!r} comes with E4b (declared signals); E4a signal keys are {_E4A_KEYS}"
    return (
        f"unknown signal key {key!r}; E4a signal keys are {_E4A_KEYS}; "
        "logprob and other declared signals come with E4b"
    )


def signal(key: str) -> Signal:
    """A named number on a member Answer, read by a reducer: cost_usd, latency_ms, tokens_in,
    tokens_out, score:judge, or field:<path>. A missing value is None, never an error."""

    return Signal(key)


__all__: list[str] = []

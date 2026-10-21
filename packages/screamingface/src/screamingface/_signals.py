"""Answer signal keys and the sf.signal seam (OME-1289 gap, signals I-S1, BU-E2).

INVARIANT: FIELD_PATH is the Engine's combine/ports.py field-path grammar, copied line for line;
STU/test_signal_key_conformance.py binds the copy. E4b part 3 adds declared signals
(`is_signal_name`) through this seam.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from screamingface._surface.refs import GateRef

_FIELD_KEY = r"[A-Za-z_][A-Za-z0-9_]*"  # verbatim E/combine/ports.py
_FIELD_INDEX = r"\[(?:0|[1-9][0-9]*)\]"
FIELD_PATH = re.compile(rf"(?:{_FIELD_KEY}|{_FIELD_INDEX})(?:\.{_FIELD_KEY}|{_FIELD_INDEX})*")
ACCOUNTING_SIGNALS: tuple[str, ...] = ("cost_usd", "latency_ms", "tokens_in", "tokens_out")
FIELD_SIGNAL_PREFIX = "field:"
JUDGE_SIGNAL = "score:judge"
DECLARED_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
RESERVED_NAME_PREFIXES: tuple[str, ...] = ("logprob", "entropy", "verbalized", "consistency")
MAX_DECLARED_SIGNALS = 8


def is_signal_key(key: object) -> bool:
    """I-S1: an accounting key, score:judge, or field:<FIELD_PATH>."""

    if not isinstance(key, str):
        return False
    if key in ACCOUNTING_SIGNALS or key == JUDGE_SIGNAL:
        return True
    return key.startswith(FIELD_SIGNAL_PREFIX) and (
        FIELD_PATH.fullmatch(key[len(FIELD_SIGNAL_PREFIX) :]) is not None
    )


def is_signal_name(key: object) -> bool:
    """E4b P1: a declared name: [a-z][a-z0-9_]{0,31}, not an E4a key, no reserved prefix."""

    return (
        isinstance(key, str)
        and DECLARED_NAME.fullmatch(key) is not None
        and key not in ACCOUNTING_SIGNALS
        and not key.startswith(RESERVED_NAME_PREFIXES)
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


@dataclass(frozen=True, slots=True, eq=False)
class Signal:
    """A named number on a member Answer, read by a reducer."""

    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str):
            raise TypeError("a signal key must be text")
        if self.key in _RESERVED:
            raise ValueError(_RESERVED[self.key])
        if not is_signal_key(self.key) and not is_signal_name(self.key):
            raise ValueError(_rejection(self.key))

    def __repr__(self) -> str:
        return f"signal({self.key!r})"

    def _python(self) -> str:
        return f"sf.signal({self.key!r})"

    # AIDEV-NOTE: ``x in seq`` and ``seq.index(x)`` raise TypeError when ``seq`` holds a Signal and
    # ``x`` is a number or a bool (``1 in [s]``): the equality returns a predicate, and its truth
    # value is refused. No SDK path does this (every option validator type-checks first).
    # WHY the operators build predicates (unit 4 F13, FL-D2): ``sf.signal(key) >= 0.6`` is an
    # sf.Filter predicate. ``Signal == Signal`` stays a plain bool (BK-D4), so equality and the hash
    # are explicit and the dataclass eq is off. The overrides return a predicate, not a bool, on
    # purpose (numpy and SQLAlchemy do the same), hence the Any return types.
    def __eq__(self, other: object) -> Any:
        if isinstance(other, Signal):
            return self.key == other.key
        if isinstance(other, bool | int | float):
            return _comparison(self, "eq", other)
        return NotImplemented

    def __ne__(self, other: object) -> Any:
        if isinstance(other, Signal):
            return self.key != other.key
        if isinstance(other, bool | int | float):
            raise TypeError("sf.Filter has no != predicate; compare with ==, <, <=, > or >=")
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.key)

    def __gt__(self, other: object) -> Any:
        return _ordered(self, "gt", other)

    def __ge__(self, other: object) -> Any:
        return _ordered(self, "ge", other)

    def __lt__(self, other: object) -> Any:
        return _ordered(self, "lt", other)

    def __le__(self, other: object) -> Any:
        return _ordered(self, "le", other)

    def chosen(self) -> GateRef:
        """The declared signal of the member that the vote chose: a gate reference."""

        return _gate_ref("chosen", self._declared("chosen"))

    def mean(self) -> GateRef:
        """The mean of the declared signal over the members: a gate reference."""

        return _gate_ref("mean", self._declared("mean"))

    def _declared(self, method: str) -> str:
        if is_signal_key(self.key):
            raise ValueError(  # SI-1
                f"sf.signal({self.key!r}).{method}() reads a declared signal; an E4a key such as "
                "cost_usd is not a gate input"
            )
        return self.key


def _gate_ref(method: str, name: str) -> GateRef:
    # WHY lazy: the gate references live with the gate step (S/_surface/refs.py imports this module)
    from screamingface._surface.refs import GateRef

    return GateRef(f"{method}:{name}")


def _ordered(signal: Signal, cmp: _Cmp, other: object) -> Any:
    """``signal < 3`` and friends: a predicate for a number, NotImplemented (a TypeError) else."""

    if isinstance(other, bool | int | float):
        return _comparison(signal, cmp, other)
    return NotImplemented


type _Cmp = Literal["gt", "ge", "lt", "le", "eq"]
_SYMBOLS = MappingProxyType({"gt": ">", "ge": ">=", "lt": "<", "le": "<=", "eq": "=="})


@dataclass(frozen=True, slots=True, eq=False)
class _Comparison:
    """A signal compared with a number (or, for ``==``, a bool): the predicate of ``sf.Filter``.

    INVARIANT (GE21): equality and the hash go over a typed key, because Python's True == 1 == 1.0
    but a bool and a number compile to different JSON, so they are different predicates.
    """

    signal: Signal
    cmp: _Cmp
    value: float | bool

    def _key(self) -> tuple[object, ...]:
        return (self.signal.key, self.cmp, type(self.value) is bool, self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Comparison) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __bool__(self) -> bool:
        raise TypeError("a signal comparison is an sf.Filter predicate, not a bool")

    def __repr__(self) -> str:
        return f"signal({self.signal.key!r}) {_SYMBOLS[self.cmp]} {self.value!r}"

    def _python(self) -> str:
        return f"sf.signal({self.signal.key!r}) {_SYMBOLS[self.cmp]} {self.value!r}"

    def _args(self) -> dict[str, object]:
        return {"key": self.signal.key, "cmp": self.cmp, "value": self.value}


def _comparison(signal: Signal, cmp: str, value: object) -> _Comparison:
    """The one place a comparison is built and checked: the Signal operators and the url4 decode.

    A number must be finite (the Engine refuses anything else, after the member calls are paid);
    it is stored as a float. A bool is a threshold for ``==`` only.
    """

    if cmp not in _SYMBOLS:
        raise ValueError(f"unknown signal comparison {cmp!r}")
    if isinstance(value, bool):
        if cmp != "eq":
            raise ValueError("a boolean threshold compares with == only")
        return _Comparison(signal, "eq", value)
    if not isinstance(value, int | float):
        raise TypeError("sf.signal comparison value must be a number")
    return _Comparison(signal, cast("_Cmp", cmp), _finite(value))


def _finite(value: float) -> float:
    try:
        number = float(value)
    except OverflowError:  # an int too large for a float
        number = math.inf
    if not math.isfinite(number):
        raise ValueError("sf.signal comparison value must be finite")
    # WHY + 0.0: -0.0 == 0.0 in Python but they render as different JSON, so they must be one value
    return number + 0.0


def _finite_number(value: object, type_message: str, finite_message: str) -> float:
    """A number that is not a bool, as a finite float (an int becomes a float).

    TypeError(type_message) for any other value; ValueError(finite_message) for NaN, an infinity
    or an int beyond the float range. The caller gives both messages.

    WHY ``_finite`` (``_comparison``) stays separate: there a bool is a valid ``==`` threshold,
    ``+ 0.0`` turns -0.0 into 0.0, and its message differs (one fixed sf.signal text).
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(type_message)
    try:
        number = float(value)
    except OverflowError:  # an int beyond the float range
        raise ValueError(finite_message) from None
    if not math.isfinite(number):
        raise ValueError(finite_message)
    return number


def _rejection(key: str) -> str:
    if key.startswith(FIELD_SIGNAL_PREFIX):
        return "field signal path must be a JSON path like 'a', 'a.b' or 'a[0].b'"
    if key.startswith(RESERVED_NAME_PREFIXES):
        return (
            f"{key!r} is reserved: names that start with logprob, entropy, verbalized or "
            "consistency belong to E4b declared sources; declare a name such as "
            "signals={'lp': sf.Logprob('mean')} and read sf.signal('lp'); "
            f"E4a signal keys are {_E4A_KEYS}"
        )
    return (
        f"{key!r} is not a signal key or a declared name; E4a signal keys are {_E4A_KEYS}; "
        "an E4b declared name matches [a-z][a-z0-9_]{0,31}"
    )


def signal(key: str) -> Signal:
    """A named number on a member Answer, read by a reducer: cost_usd, latency_ms, tokens_in,
    tokens_out, score:judge, field:<path>, or a name that the ``sf.Fanout`` declares in
    ``signals=``. A missing value is None, never an error."""

    return Signal(key)


__all__: list[str] = []

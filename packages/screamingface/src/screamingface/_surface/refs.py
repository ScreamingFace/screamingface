"""The references of the new surface: the ``over=`` extractors and the ``weights=`` keys (§9).

FEATURE (E4b surface, surface §9): ``over=`` takes a rule name (``"last_line"``), the same name
with a pinned version (``"last_line@1"``, which the url4 rebuild writes), ``"field:<path>"`` (the
JSON field text) or an ``sf.Extract(...)`` value. Any other string is refused with the list of
rule names (EX-1). ``weights=`` takes a signal key string; it goes through ``sf.signal(key)``, so
it has the same check and the same messages.
INVARIANT: ``"field:<path>"`` in ``over=`` is an extractor, not a signal: it reads the field text
as the answer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from screamingface._signals import (
    FIELD_SIGNAL_PREFIX,
    Signal,
    _finite_number,
    signal,
)
from screamingface.blocks import _RULES, Extract, ExtractRule, NormalizeRule
from screamingface.combine_evidence import GateCmp
from screamingface.fields import _FIELD_NAME, FieldNormalizer, _normalizer, _target_text
from screamingface.reducer import BENCHMARK_EXTRACT, _weights_option
from screamingface.reducer import _field_path as _checked_field_path

# The rule names over= takes: every sf.Extract rule with no required argument (EX-1). A rule with
# arguments ("field", "regex") is written as "field:<path>" or as sf.Extract(...).
RULE_NAMES: tuple[str, ...] = tuple(
    rule for rule, (_, required, _) in _RULES.items() if not required
)
_AGREEMENT = "agreement"
_BAND_TYPE = "between(lo, hi) takes two numbers"
_BAND_FINITE = "between(lo, hi) needs finite numbers"
_PINNED = re.compile(r"([a-z][a-z0-9_]*)@([1-9][0-9]*)")
_EX1 = (
    f"over= must be a rule name ({', '.join(RULE_NAMES)}), a rule name with a version such as "
    "'last_line@1', 'field:<path>', or sf.Extract(...), not {value!r}"
)

type Extractor = str | Extract
type Weights = tuple[float, ...] | Signal


@dataclass(frozen=True, slots=True)
class GateRef:
    """A number a gate reads: ``sf.agreement()``, ``sf.signal(x).chosen()`` or ``.mean()``.

    Compare it with a finite number (``>=``, ``>``, ``<=``, ``<``) for ``sf.Gate(when=...)``, and
    give ``.between(lo, hi)`` to ``sf.Gate(abstain_if=...)``.
    """

    observe: str

    def __ge__(self, other: object) -> GateCondition:
        return _condition(self, ">=", other)

    def __gt__(self, other: object) -> GateCondition:
        return _condition(self, ">", other)

    def __le__(self, other: object) -> GateCondition:
        return _condition(self, "<=", other)

    def __lt__(self, other: object) -> GateCondition:
        return _condition(self, "<", other)

    def between(self, lo: float, hi: float) -> GateBand:
        """The closed band [lo, hi] of this number: inside it, the gate abstains (part 6)."""

        # WHY both types first: a pair such as (inf, "a") is a TypeError, not a ValueError.
        if any(isinstance(item, bool) or not isinstance(item, int | float) for item in (lo, hi)):
            raise TypeError(_BAND_TYPE)
        low, high = (_finite_number(item, _BAND_TYPE, _BAND_FINITE) + 0.0 for item in (lo, hi))
        if low > high:
            raise ValueError("between(lo, hi) needs lo <= hi")
        self._check_share(low, high)
        return GateBand(self, low, high)

    def _check_share(self, *numbers: float) -> None:
        """An agreement is a share in [0, 1], so a threshold or a band outside it never holds."""

        if self.observe == _AGREEMENT and not all(0.0 <= number <= 1.0 for number in numbers):
            raise ValueError("sf.agreement() is a share: compare it with numbers between 0 and 1")

    def __repr__(self) -> str:
        if self.observe == _AGREEMENT:
            return "agreement()"
        method, _, name = self.observe.partition(":")
        return f"signal({name!r}).{method}()"


@dataclass(frozen=True, slots=True)
class GateCondition:
    """``ref <cmp> threshold``: the condition that keeps the vote's answer (part 5, P4)."""

    ref: GateRef
    cmp: GateCmp
    threshold: float

    def __repr__(self) -> str:
        return f"{self.ref!r} {self.cmp} {self.threshold!r}"


@dataclass(frozen=True, slots=True)
class GateBand:
    """``ref.between(lo, hi)``: the closed band where the gate abstains (part 6)."""

    ref: GateRef
    lo: float
    hi: float

    def __repr__(self) -> str:
        return f"{self.ref!r}.between({self.lo!r}, {self.hi!r})"


def agreement() -> GateRef:
    """The share of the members that hold the vote's answer: a gate reference in [0, 1]."""

    return GateRef(_AGREEMENT)


def _condition(ref: GateRef, cmp: GateCmp, value: object) -> GateCondition:
    # WHY a bool is refused: it is not a threshold, and True == 1 would hide the mistake.
    # WHY + 0.0: -0.0 == 0.0 in Python but they render as different JSON (as _signals._finite).
    threshold = (
        _finite_number(
            value,
            f"a gate condition compares with a number, not {value!r}",
            "a gate condition compares with a finite number",
        )
        + 0.0
    )
    ref._check_share(threshold)
    return GateCondition(ref, cmp, threshold)


def extractor(value: object) -> Extractor:
    """``value`` if it is a valid ``over=`` value, else TypeError or ValueError (EX-1)."""

    if isinstance(value, Extract):
        return value
    if not isinstance(value, str):
        raise TypeError("over= must be a rule name or sf.Extract(...)")
    if value.startswith(FIELD_SIGNAL_PREFIX):  # the path rule of sf.field()
        _checked_field_path(value.removeprefix(FIELD_SIGNAL_PREFIX), "over= field path")
    elif _rule_name(value) not in RULE_NAMES:
        raise ValueError(_EX1.format(value=value))
    elif _rule_name(value) == BENCHMARK_EXTRACT != value:
        # WHY: "benchmark" has no operator id, so the url4 rebuild never writes a pinned form.
        raise ValueError(
            f"over={BENCHMARK_EXTRACT!r} names the benchmark's answer rule and takes no version"
        )
    return value


def is_rule_name(over: Extractor) -> bool:
    """Whether ``over`` names a rule (pinned or not): it lowers to the named reducer node."""

    return isinstance(over, str) and not over.startswith(FIELD_SIGNAL_PREFIX)


def engine_op(rule: str) -> str:
    """The operator a rule name compiles to, with its pin: ``"json@1"`` is ``"json_object@1"``.

    WHY: a named reducer stores an Engine operator name, and the Extract rule "json" is the
    operator "json_object" (S/blocks.py). Every other rule name is its operator name;
    "benchmark" has no operator and stays as it is.
    """

    name, at, version = rule.partition("@")
    operator = _RULES[name][0]
    return rule if operator is None else f"{operator}{at}{version}"


def field_extract(over: str, normalize: str | None) -> Extract:
    """The ``sf.Extract("field", ...)`` of an ``over="field:<path>"`` value."""

    path = over.removeprefix(FIELD_SIGNAL_PREFIX)
    rule = None if normalize is None else cast("NormalizeRule", str(normalize))
    return Extract("field", rule, path=path)


def with_normalizer(extract: Extract, normalize: str | None) -> Extract:
    """``extract`` with ``normalize`` in place of its own normalizer."""

    rule = None if normalize is None else cast("NormalizeRule", str(normalize))
    return Extract(cast("ExtractRule", extract.rule), rule, **extract.args)


def weights(value: object, label: str) -> Weights | None:
    """The checked ``weights=`` value: a key string becomes ``sf.signal(key)``."""

    if value is None:
        return None
    if isinstance(value, str | Signal):
        return signal_key(value, label)
    return _weights_option(value, label)


def output_field(value: object, label: str) -> str | None:
    """An ``output=`` value: None or one top-level field name of the winner's JSON reply."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} output= must be a string")
    if _FIELD_NAME.fullmatch(value) is None:
        raise ValueError(
            f"{label} output={value!r} must be a top-level field name like 'answer' "
            "(a letter or _, then letters, digits or _; at most 64 characters)"
        )
    return value


def signal_key(value: object, label: str) -> Signal:
    """A ``by=`` or ``weights=`` key: one signal, as a key string or ``sf.signal(key)`` (RA-1).

    A key string goes through ``sf.signal(key)``, so it has the same check and the same messages.
    """

    if isinstance(value, str):
        value = signal(value)
    if not isinstance(value, Signal):
        raise TypeError(
            f"{label} by= must be one signal: a key string such as 'cost_usd' or sf.signal(key)"
        )
    if value.key.startswith(FIELD_SIGNAL_PREFIX):  # the path rule of sf.field() (gap c)
        _checked_field_path(value.key.removeprefix(FIELD_SIGNAL_PREFIX), f"{label} field path")
    return value


_SI2 = "sf.field compares with == only; use sf.signal('field:...') for numbers"


@dataclass(frozen=True, slots=True, eq=False)
class FieldEquals:
    """``sf.field(path) == value``: the condition of ``sf.First``."""

    path: str
    normalize: FieldNormalizer | None
    value: str | int | float | bool

    def _key(self) -> tuple[object, ...]:
        # WHY the JSON text: the value compares as that text (the PickNode), so == 7 and == "7"
        # are one condition with one url4, and == 1 and == True are two.
        return (self.path, self.normalize, _target_text(self.value))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FieldEquals) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


@dataclass(frozen=True, slots=True, eq=False)
class FieldRef:
    """A JSON field of each member, for ``sf.First(where=sf.field(path) == value)``.

    It compares with ``==`` only (SI-2): the value compares as text. For a number, use
    ``sf.signal("field:<path>")``.
    """

    path: str
    normalize: FieldNormalizer | None

    def __eq__(self, other: object) -> Any:
        return FieldEquals(self.path, self.normalize, _field_value(other, self.normalize))

    def __ne__(self, other: object) -> Any:
        raise TypeError(_SI2)

    def __lt__(self, other: object) -> Any:
        raise TypeError(_SI2)

    def __le__(self, other: object) -> Any:
        raise TypeError(_SI2)

    def __gt__(self, other: object) -> Any:
        raise TypeError(_SI2)

    def __ge__(self, other: object) -> Any:
        raise TypeError(_SI2)

    __hash__: ClassVar[Any] = None


def _field_value(value: object, normalize: FieldNormalizer | None) -> str | int | float | bool:
    """The value of ``sf.field(path) == value``, checked with the rules of the field pick node."""

    if not isinstance(value, str | int | float | bool):
        raise TypeError(f"sf.field compares with a string, a number or a bool, not {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"sf.field == {value!r} must be finite")
    if isinstance(value, bool) and normalize == "numeric":
        raise ValueError("sf.field == True or False cannot be compared with normalize='numeric'")
    if not _target_text(value).strip():
        raise ValueError(f"sf.field == {value!r} must not be blank")
    return value


def field(path: str, *, normalize: FieldNormalizer | None = None) -> FieldRef:
    """A JSON field reference for ``sf.First``: ``sf.field("answer") == "yes"`` (surface §9).

    ``normalize``: None (the value compares as JSON text, so ``== 7`` also matches ``"7"``),
    ``"text"`` or ``"numeric"``.
    """

    return FieldRef(_checked_field_path(path, "sf.field path"), _normalizer(normalize, "sf.field"))


def _rule_name(value: str) -> str:
    pinned = _PINNED.fullmatch(value)
    return value if pinned is None else pinned.group(1)


__all__ = ["Extract", "agreement", "field"]

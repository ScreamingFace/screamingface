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

from screamingface._signals import FIELD_PATH, FIELD_SIGNAL_PREFIX, Signal, signal
from screamingface.blocks import _RULES, Extract, ExtractRule, NormalizeRule
from screamingface.fields import _FIELD_NAME, FieldNormalizer, _normalizer, _target_text
from screamingface.reducer import BENCHMARK_EXTRACT, _weights_option
from screamingface.reducer import _field_path as _checked_field_path

# The rule names over= takes: every sf.Extract rule with no required argument (EX-1). A rule with
# arguments ("field", "regex") is written as "field:<path>" or as sf.Extract(...).
RULE_NAMES: tuple[str, ...] = tuple(
    rule for rule, (_, required, _) in _RULES.items() if not required
)
_PINNED = re.compile(r"([a-z][a-z0-9_]*)@([1-9][0-9]*)")
_EX1 = (
    f"over= must be a rule name ({', '.join(RULE_NAMES)}), a rule name with a version such as "
    "'last_line@1', 'field:<path>', or sf.Extract(...), not {value!r}"
)

type Extractor = str | Extract
type Weights = tuple[float, ...] | Signal


def extractor(value: object) -> Extractor:
    """``value`` if it is a valid ``over=`` value, else TypeError or ValueError (EX-1)."""

    if isinstance(value, Extract):
        return value
    if not isinstance(value, str):
        raise TypeError("over= must be a rule name or sf.Extract(...)")
    if value.startswith(FIELD_SIGNAL_PREFIX):
        _field_path(value)
    elif _rule_name(value) not in RULE_NAMES:
        raise ValueError(_EX1.format(value=value))
    elif _rule_name(value) == BENCHMARK_EXTRACT != value:
        # WHY: "benchmark" has no operator id, so the url4 rebuild never writes a pinned form.
        raise ValueError(
            f"over={BENCHMARK_EXTRACT!r} names the benchmark's answer rule and takes no version"
        )
    return value


def is_rule_name(over: Extractor) -> bool:
    """Whether ``over`` names a rule (pinned or not): it lowers to today's named reducer."""

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
    return _weights_option(signal(value) if isinstance(value, str) else value, label)


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
    """A ``by=`` value: one signal, as a key string or ``sf.signal(key)`` (RA-1).

    A key string goes through ``sf.signal(key)``, so it has the same check and the same messages.
    """

    if isinstance(value, str):
        return signal(value)
    if not isinstance(value, Signal):
        raise TypeError(
            f"{label} by= must be one signal: a key string such as 'cost_usd' or sf.signal(key)"
        )
    return value


_SI2 = "sf.field compares with == only; use sf.signal('field:...') for numbers"


@dataclass(frozen=True, slots=True, eq=False)
class FieldEquals:
    """``sf.field(path) == value``: the condition of ``sf.First``."""

    path: str
    normalize: FieldNormalizer | None
    value: str | int | float | bool

    def _key(self) -> tuple[object, ...]:
        # WHY the JSON text: the value compares as that text (today's Pick), so == 7 and == "7"
        # are one condition with one url4, and == 1 and == True are two.
        return (self.path, self.normalize, _target_text(self.value))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FieldEquals) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


@dataclass(frozen=True, slots=True, eq=False)
class FieldRef:
    """A JSON field of each member, for ``sf.First(where=sf.field(path) == value)``.

    It compares with ``==`` only (SI-2): the value compares as text, with today's
    ``Pick(equals=)`` rules. For a number, use ``sf.signal("field:<path>")``.
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
    """The value of ``sf.field(path) == value``, checked with today's ``Pick(equals=)`` rules."""

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


def _field_path(value: str) -> None:
    if FIELD_PATH.fullmatch(value.removeprefix(FIELD_SIGNAL_PREFIX)) is None:
        raise ValueError(
            f"over={value!r} must name a JSON path after 'field:', like 'field:a.b' or "
            "'field:a[0].b'"
        )


__all__ = ["Extract", "field", "signal"]

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

import re
from typing import cast

from screamingface._signals import FIELD_PATH, FIELD_SIGNAL_PREFIX, Signal, signal
from screamingface.blocks import _RULES, Extract, ExtractRule, NormalizeRule
from screamingface.reducer import BENCHMARK_EXTRACT, _weights_option

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


def _rule_name(value: str) -> str:
    pinned = _PINNED.fullmatch(value)
    return value if pinned is None else pinned.group(1)


def _field_path(value: str) -> None:
    if FIELD_PATH.fullmatch(value.removeprefix(FIELD_SIGNAL_PREFIX)) is None:
        raise ValueError(
            f"over={value!r} must name a JSON path after 'field:', like 'field:a.b' or "
            "'field:a[0].b'"
        )


__all__ = ["Extract", "signal"]

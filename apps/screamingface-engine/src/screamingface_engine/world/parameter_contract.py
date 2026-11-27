"""One Model parameter value against its published Gateway row (C4 ADMIT, Unit 5.2).

FEATURE: Router Recipe extension. Router ADMIT checks each Model's parameter contract before any
I/O of the occurrence, as the SDK's E4c preflight does for a Gate member
(`_evaluation/model_parameters._validate_parameter`), in the same four stages: the row exists,
the Gateway forwards it, the provider does not refuse it, and the value fits the schema the
Gateway enforces (`aigateway/core/chat_parameters/_schema.py`, `validate_value`).

WHY the fixed profile does not use this: its `max_tokens` check (`routing_core._admits`) is a
shipped behavior that reads no provider evidence, and a fixed profile's errors stay unchanged.

INVARIANT: strict and pure. A row that cannot be read misfits; nothing is repaired, defaulted or
read as permissive. No HTTP, url4, configuration or recorder import.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from typing import Any

_TYPES: Mapping[str, Callable[[object], bool]] = {
    "number": lambda value: isinstance(value, int | float) and not isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, list),
    "object": lambda value: isinstance(value, dict),
}
_PROVIDER_ADMITS = frozenset({"supported", "conditional", "unknown"})
"""The Gateway's closed provider-support vocabulary (`ProviderSupport`) less its one refusal.

INVARIANT: as the SDK's stage 3, only ``unsupported`` refuses among the published values; a value
outside the vocabulary, or not a string, is unreadable evidence and misfits.
"""
_SCHEMA_KEYS = frozenset({"type", "minimum", "maximum", "enum", "items", "pattern", "maxLength"})
"""The keys the Gateway renders (`ParameterSchema.to_json_schema`); an item schema renders `type`.

INVARIANT: any other key is unreadable. The Gateway forbids it and the SDK would skip it, so an
unknown constraint (`exclusiveMaximum`, an item `maxLength`) would read as absent protection.
"""


def value_fits(rule: object, value: object) -> bool:
    """Whether a published parameter row admits ``value``, typed as the call sends it."""
    if not isinstance(rule, dict):
        return False
    gateway, provider, schema = rule.get("gateway"), rule.get("provider"), rule.get("schema")
    return (
        isinstance(gateway, dict)
        and gateway.get("status") == "enabled"
        and isinstance(provider, dict)
        and _support_admits(provider.get("support"))
        and isinstance(schema, dict)
        and _schema_fits(schema, value)
    )


def _support_admits(support: object) -> bool:
    # WHY the type first: an unhashable value cannot be looked up in the vocabulary.
    return isinstance(support, str) and support in _PROVIDER_ADMITS


def _schema_fits(schema: dict[str, Any], value: object) -> bool:
    kinds = _kinds(schema.get("type"))
    if not kinds or not _constraints_readable(schema, kinds):
        return False
    return (
        any(_TYPES[kind](value) for kind in kinds)
        and _finite(value)
        and _in_bounds(value, schema.get("minimum"), schema.get("maximum"))
        and _string_fits(value, schema.get("maxLength"), schema.get("pattern"))
        and (schema.get("enum") is None or value in schema["enum"])
        and _items_fit(value, schema.get("items"))
    )


def _kinds(declared: object) -> tuple[str, ...]:
    """The schema's type names, or none when any is not a known name or a name repeats."""
    declared_kinds = declared if isinstance(declared, list) else [declared]
    known = tuple(kind for kind in declared_kinds if isinstance(kind, str) and kind in _TYPES)
    return known if known and len(known) == len(declared_kinds) == len(set(known)) else ()


def _constraints_readable(schema: dict[str, Any], kinds: tuple[str, ...]) -> bool:
    """Whether every constraint lies where the Gateway publishes and the SDK decodes alike.

    INVARIANT: as the Gateway and the SDK, `pattern` and `maxLength` stand only on a top-level
    type list holding ``string``; on any other they could never fire and would read as absent
    protection, so the row is unreadable.
    WHY the stricter reader wins where they differ (an unknown key, a repeated type name,
    inverted bounds, a blank, padded or repeated enum member): a row either refuses never leads
    to a paid call here.
    """
    low, high, length = schema.get("minimum"), schema.get("maximum"), schema.get("maxLength")
    pattern, enum, items = schema.get("pattern"), schema.get("enum"), schema.get("items")
    floor, ceiling = _bound(low), _bound(high)
    return (
        schema.keys() <= _SCHEMA_KEYS
        and (low is None or floor is not None)
        and (high is None or ceiling is not None)
        and (floor is None or ceiling is None or floor <= ceiling)
        and ((length is None and pattern is None) or "string" in kinds)
        and (length is None or (_TYPES["integer"](length) and length >= 1))
        and (pattern is None or _pattern_readable(pattern))
        and (enum is None or _enum_readable(enum))
        and (items is None or _items_readable(items))
    )


def _items_readable(items: object) -> bool:
    """An item schema of ``type`` alone, naming one type but ``array``: the readers' item rule."""
    if not (isinstance(items, dict) and items.keys() == {"type"}):
        return False
    declared = items["type"]
    return isinstance(declared, str) and declared in _TYPES and declared != "array"


def _enum_readable(enum: object) -> bool:
    """Distinct non-blank strings without surrounding blanks.

    WHY strings only: ``True == 1`` in Python, so a number or a boolean member would let a value
    of another type pass. WHY unpadded: the SDK strips a member and the Gateway does not, so a
    padded member names a different value to each.
    """
    return (
        isinstance(enum, list)
        and all(isinstance(member, str) and member == member.strip() != "" for member in enum)
        and len(set(enum)) == len(enum)
    )


def _pattern_readable(pattern: object) -> bool:
    """A string anchored with ``^`` and ``$`` that compiles.

    WHY anchored although `_string_fits` full-matches: the Gateway publishes the pattern and
    refuses an unanchored one, which a JSON Schema reader would match partially.
    WHY the wider catch: the compiler recurses once per nesting level and raises `OverflowError`
    for a repetition count past its limit; such a pattern is unreadable, never an exception out
    of ADMIT.
    """
    if not (isinstance(pattern, str) and pattern.startswith("^") and pattern.endswith("$")):
        return False
    try:
        re.compile(pattern)
    except (re.error, RecursionError, OverflowError):
        return False
    return True


def _bound(value: object) -> float | None:
    """A bound as the Gateway stores it and the SDK reads it, a finite float; none if unreadable.

    WHY the float: both convert a bound to a float and compare the sent value with that float,
    so a bound no float holds exactly (``2**53 + 1``) bounds at its nearest float there, and here.
    WHY the catch: JSON carries an integer of any size; one past every float is unreadable here,
    never an `OverflowError` out of ADMIT.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        bound = float(value)
    except OverflowError:
        return None
    return bound if math.isfinite(bound) else None


def _finite(value: object) -> bool:
    return not (isinstance(value, float) and not math.isfinite(value))


def _in_bounds(value: object, low: object, high: object) -> bool:
    """Whether a number meets each bound as the float both readers compare it with."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return True
    floor, ceiling = _bound(low), _bound(high)
    return (floor is None or floor <= value) and (ceiling is None or value <= ceiling)


def _string_fits(value: object, length: object, pattern: object) -> bool:
    if not isinstance(value, str):
        return True
    # WHY length first: as the Gateway, a long value is bounded before the regex engine sees it.
    if isinstance(length, int) and len(value) > length:
        return False
    return not isinstance(pattern, str) or re.fullmatch(pattern, value) is not None


def _items_fit(value: object, items: object) -> bool:
    if not isinstance(value, list) or not isinstance(items, dict):
        return True
    check = _TYPES[items["type"]]
    return all(check(item) and _finite(item) for item in value)


__all__ = ["value_fits"]

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
    if not kinds or not _constraints_readable(schema):
        return False
    return (
        any(_TYPES[kind](value) for kind in kinds)
        and _finite(value)
        and _in_bounds(value, schema.get("minimum"), schema.get("maximum"))
        and _string_fits(value, schema.get("maxLength"), schema.get("pattern"))
        and (schema.get("enum") is None or value in schema["enum"])
        and _items_fit(value, schema.get("items"))
    )


def _kinds(declared: object, *, list_ok: bool = True) -> tuple[str, ...]:
    """The schema's type names, or none when any is not a known name.

    WHY ``list_ok``: an item schema names one type, as the Gateway publishes it.
    """
    declared_kinds = declared if list_ok and isinstance(declared, list) else [declared]
    known = tuple(kind for kind in declared_kinds if isinstance(kind, str) and kind in _TYPES)
    return known if known and len(known) == len(declared_kinds) else ()


def _constraints_readable(schema: dict[str, Any]) -> bool:
    low, high, length = schema.get("minimum"), schema.get("maximum"), schema.get("maxLength")
    pattern, enum, items = schema.get("pattern"), schema.get("enum"), schema.get("items")
    return (
        (low is None or _number(low))
        and (high is None or _number(high))
        and (length is None or (_TYPES["integer"](length) and length >= 1))
        and (pattern is None or _compiles(pattern))
        and (enum is None or isinstance(enum, list))
        and (
            items is None
            or (isinstance(items, dict) and bool(_kinds(items.get("type"), list_ok=False)))
        )
    )


def _compiles(pattern: object) -> bool:
    if not isinstance(pattern, str):
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _finite(value: object) -> bool:
    return not (isinstance(value, float) and not math.isfinite(value))


def _in_bounds(value: object, low: object, high: object) -> bool:
    """Whether a number is within the bounds; `_constraints_readable` admitted each as a number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return True
    return (not isinstance(low, int | float) or low <= value) and (
        not isinstance(high, int | float) or value <= high
    )


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

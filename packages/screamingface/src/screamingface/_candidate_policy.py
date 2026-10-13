"""Validated immutable Candidate generation overrides."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType

from screamingface._operation_bindings import OPERATION_BINDING_PARAM

type GenerationScalar = str | int | float | bool
type GenerationParams = Mapping[str, GenerationScalar]

_EXECUTION_OWNED_PARAMS = frozenset(
    {
        # WHY (OME-1289): the Engine reads this name for attribution and never forwards it
        OPERATION_BINDING_PARAM,
        "input",
        "messages",
        "model",
        "plugins",
        "provider",
        "q",
        "stream",
        "tool_choice",
        "tools",
        "web_search",
        "web_search_exclude",
        "web_search_excluded_domains",
        "web_search_policy",
    }
)
"""Transport, routing, tool, and Benchmark protocol fields users cannot override."""


def prompt(value: object | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string or None")
    if not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


def params(value: object | None, label: str) -> GenerationParams:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping or None")
    selected: dict[str, GenerationScalar] = {}
    for name, item in value.items():
        selected_name = _parameter_name(name, label)
        selected[selected_name] = _parameter_value(selected_name, item, label)
    return MappingProxyType(selected)


def _parameter_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} names must be non-empty strings")
    if not value.isascii() or not all(
        character.isalnum() or character in "._" for character in value
    ):
        raise ValueError(f"{label} parameter {value!r} cannot be encoded")
    if value in _EXECUTION_OWNED_PARAMS:
        raise ValueError(
            f"{label} parameter {value!r} is reserved for Benchmark and Engine execution"
        )
    return value


def _parameter_value(name: str, value: object, label: str) -> GenerationScalar:
    if not isinstance(value, str | int | float | bool):
        raise TypeError(f"{label} value {name!r} must be a scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} value {name!r} must be finite")
    if isinstance(value, str) and any(
        character in "';(),&" or ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError(f"{label} value {name!r} cannot be encoded")
    return value


__all__: list[str] = []

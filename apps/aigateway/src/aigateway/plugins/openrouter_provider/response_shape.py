"""Shape checks shared by the OpenRouter zero proofs (`zero_insurance`, `pre_output_refusal`).

INVARIANT: each check is total and fail closed. It answers only "is this shape known and well
typed"; what a proof needs on top of that stays in the proof.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def optional_string(value: Mapping[str, Any], field: str, *, nullable: bool = False) -> bool:
    """An absent field, or a string (or ``None`` when ``nullable``)."""
    if field not in value:
        return True
    item = value[field]
    return (nullable and item is None) or type(item) is str


def optional_count(value: Mapping[str, Any], field: str) -> bool:
    """An absent field, or a non-negative ``int`` (``bool`` is refused)."""
    if field not in value:
        return True
    item = value[field]
    return type(item) is int and item >= 0


def response_scalars_are_valid(
    raw_response: Mapping[str, Any],
    *,
    strings: Iterable[str],
    nullable_strings: Iterable[str],
) -> bool:
    """The top-level identity scalars, plus ``created`` as a non-negative ``int``."""
    return (
        all(optional_string(raw_response, field) for field in strings)
        and all(optional_string(raw_response, field, nullable=True) for field in nullable_strings)
        and optional_count(raw_response, "created")
    )


def endpoints_are_valid(value: object) -> bool:
    """Router ``endpoints``: absent, or ``{total, available: [{provider, model, selected}]}``."""
    if value is None:
        return True
    endpoints = mapping(value)
    if endpoints is None or not {"total", "available"}.issuperset(endpoints):
        return False
    total = endpoints.get("total")
    available = endpoints.get("available")
    if type(total) is not int or total < 0 or not isinstance(available, list):
        return False
    for item_value in available:
        item = mapping(item_value)
        if item is None or set(item) != {"provider", "model", "selected"}:
            return False
        if type(item["provider"]) is not str or type(item["model"]) is not str:
            return False
        if type(item["selected"]) is not bool:
            return False
    return True


__all__ = [
    "endpoints_are_valid",
    "mapping",
    "optional_count",
    "optional_string",
    "response_scalars_are_valid",
]

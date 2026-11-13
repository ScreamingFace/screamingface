"""Shared validation for provider identifiers crossing the AI Gateway seam."""

from __future__ import annotations

from typing import TypeGuard

_INITIAL = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_REST = _INITIAL | {"_", "-"}


def is_provider_id(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and bool(value)
        and value[0] in _INITIAL
        and all(char in _REST for char in value[1:])
    )


__all__ = ["is_provider_id"]

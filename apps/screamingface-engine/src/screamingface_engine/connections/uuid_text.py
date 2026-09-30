"""Shared validation for UUID text crossing the AI Gateway seam."""

from __future__ import annotations

from uuid import UUID


def is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


__all__ = ["is_uuid"]

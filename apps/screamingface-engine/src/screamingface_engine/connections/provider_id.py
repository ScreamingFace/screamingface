"""Shared validation for provider identifiers crossing the AI Gateway seam."""

from __future__ import annotations

import re
from typing import TypeGuard

_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]*\Z", re.ASCII)


def is_provider_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _PROVIDER_ID.fullmatch(value) is not None


__all__ = ["is_provider_id"]

"""The shapes of `authors_metadata` and `paper_metadata` the SDK sends (OME-1613 S9, OME-1596).

FEATURE: OME-1613 S9 — `submit(..., authors_metadata=, paper_metadata=)` and
`leaderboards.edit(...)` send open metadata about the credited authors and the paper.
WHY only shapes: the board (`apps/scoreboard/.../scores/credit_metadata.py`) is the one authority
on keys, bounds, email matching and the paper link rules, and answers each problem by name. The SDK
refuses only what the board's validator can never accept (a non-object, a non-text key, a nested
or null value), so a typo fails before the request and the board's rules are never copied here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


def _scalar(value: object, label: str) -> object:
    # The board accepts text, finite numbers and booleans; never null, a list or an object.
    if isinstance(value, str | bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError(f"{label} must be text, a finite number or a boolean")


def _flat(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    selected: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{label} keys must be strings")
        selected[key] = _scalar(item, f"{label}[{key!r}]")
    return selected


def paper_metadata_value(value: object) -> dict[str, object]:
    """`paper_metadata`: one flat object (`title`, `url`, `citation`, any other key)."""

    return _flat(value, "paper_metadata")


def authors_metadata_value(value: object) -> dict[str, dict[str, object]]:
    """`authors_metadata`: one flat object per author, keyed by the author's email."""

    if not isinstance(value, Mapping):
        raise TypeError("authors_metadata must be a mapping of author email to a mapping")
    selected: dict[str, dict[str, object]] = {}
    for author, entry in value.items():
        if not isinstance(author, str):
            raise TypeError("authors_metadata keys must be author email strings")
        selected[author] = _flat(entry, f"authors_metadata[{author!r}]")
    return selected


__all__ = ["authors_metadata_value", "paper_metadata_value"]

"""The shapes of `authors_metadata` and `paper_metadata` the SDK sends (OME-1613 S9, OME-1596).

FEATURE: OME-1613 S9 — `submit(..., authors_metadata=, paper_metadata=)` and
`leaderboards.edit(...)` send open metadata about the credited authors and the paper.
WHY only shapes: the board (`apps/scoreboard/.../scores/credit_metadata.py`) is the one authority
on keys, bounds, email matching and the paper link rules, and answers each problem by name. The SDK
refuses only what the board's validator can never accept (a non-object, a non-text key, a nested
or null value), so a typo fails before the request and the board's rules are never copied here.

FEATURE: OME-2041 — one named exception to "only shapes" above: within an author's entry,
`website` is validated as an http(s) link (`validate_author_website`) rather than passed through
as an arbitrary scalar, and `display_name` is accepted as an alias for the known `full_name` key.
This is a first-class ergonomic/validation improvement on the client only — the Scoreboard side
(OME-2015) already accepts both as ordinary `authors_metadata` keys today.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from urllib.parse import urlsplit

_DISPLAY_NAME_KEY = "display_name"
_FULL_NAME_KEY = "full_name"
_WEBSITE_KEY = "website"
# WHY 2048 (OME-2041): matches `_MAX_PAPER_URL_LENGTH` (`_scoreboard/leaderboards.py`) and the
# Scoreboard's own `PAPER_URL_MAX_CHARS` — the length cap this codebase already uses for an
# http(s) link field, so `website` carries no new, unreviewed number.
_MAX_WEBSITE_LENGTH = 2048
_WEBSITE_SCHEMES = frozenset({"http", "https"})


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


def validate_author_website(value: object, label: str = "website") -> str:
    """An author's personal site as the board's own `paper_url`-shaped rules would accept it.

    FEATURE: OME-2041 — `submit(authors_metadata=...)` accepts a first-class, validated
    `website` per author rather than an arbitrary, unvalidated dict key.
    WHY these exact rules (http/https only, a host, no user info, no control characters or
    whitespace, length capped): mirrors `_paper_url` in `_scoreboard/leaderboards.py`, the SDK's
    standing model for what "validated" means for one http(s) link field, which itself mirrors
    the Scoreboard's `validate_paper_url` (`apps/scoreboard/.../scores/credit_metadata.py`). The
    link is returned UNCHANGED — never lower-cased, trimmed or reformatted.
    """
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not 1 <= len(value) <= _MAX_WEBSITE_LENGTH:
        raise ValueError(f"{label} must be 1 to {_MAX_WEBSITE_LENGTH} characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{label} must not contain control characters")
    if any(char.isspace() for char in value):
        raise ValueError(f"{label} must not contain whitespace")
    parts = urlsplit(value)
    if parts.scheme.lower() not in _WEBSITE_SCHEMES:
        raise ValueError(f"{label} must use the http or https scheme")
    if not parts.hostname:
        raise ValueError(f"{label} must name a host")
    # WHY `is not None`: `username` is "" (not None) for a bare `@`.
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{label} must not contain user info")
    return value


def _author_profile(value: object, label: str) -> dict[str, object]:
    """One author's `authors_metadata` entry: like `_flat`, but `display_name` is renamed onto
    `full_name` and `website` is validated instead of treated as an opaque scalar (OME-2041).

    INVARIANT: `display_name` and `full_name` name the same stored field — sending both is
    ambiguous (which one would the board keep?) and is refused rather than silently resolved.
    """
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    if _DISPLAY_NAME_KEY in value and _FULL_NAME_KEY in value:
        raise ValueError(f"{label} must not set both display_name and full_name")
    selected: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{label} keys must be strings")
        target_key = _FULL_NAME_KEY if key == _DISPLAY_NAME_KEY else key
        if target_key == _WEBSITE_KEY:
            selected[target_key] = validate_author_website(item, f"{label}[{key!r}]")
        else:
            selected[target_key] = _scalar(item, f"{label}[{key!r}]")
    return selected


def paper_metadata_value(value: object) -> dict[str, object]:
    """`paper_metadata`: one flat object (`title`, `url`, `citation`, any other key)."""

    return _flat(value, "paper_metadata")


def authors_metadata_value(value: object) -> dict[str, dict[str, object]]:
    """`authors_metadata`: one flat object per author, keyed by the author's email.

    FEATURE (OME-2041): within one author's entry, `display_name` is accepted as an alias for
    the known `full_name` field, and `website` is validated as an http(s) link
    (`validate_author_website`) rather than passed through as an arbitrary, unvalidated key.
    """

    if not isinstance(value, Mapping):
        raise TypeError("authors_metadata must be a mapping of author email to a mapping")
    selected: dict[str, dict[str, object]] = {}
    for author, entry in value.items():
        if not isinstance(author, str):
            raise TypeError("authors_metadata keys must be author email strings")
        selected[author] = _author_profile(entry, f"authors_metadata[{author!r}]")
    return selected


__all__ = ["authors_metadata_value", "paper_metadata_value", "validate_author_website"]

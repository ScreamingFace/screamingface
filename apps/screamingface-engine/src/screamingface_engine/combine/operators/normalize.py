"""Normalize operators: one raw value -> one comparable value, or a status (OME-1289, E4a).

FEATURE: members that write the same answer in different shapes vote together.
STORY: as an author of a majority-vote Candidate, `9`, `9.0` and `$9.` count as one answer.

Mental model: a stamp that writes every answer in one house style before the count. The numeric
stamp writes plain digits; the text stamp writes small, single-spaced words.

INVARIANT: each operator is pure; this module holds no mutable state (ports.py).
WHY ``set`` has a trailing-underscore function: the name ``set`` would shadow the builtin; the
operator's own name stays ``"set"``.
WHY ASCII digits only: ``[0-9]``, never ``\\d`` -- full-width digits are ``not_numeric`` in v1.
"""

from __future__ import annotations

import re
from decimal import Decimal

from screamingface_engine.combine.ports import (
    OpArgs,
    OperatorDescriptor,
    StageResult,
    accepted,
    canonical_decimal,
    canonical_json,
    loads_bounded,
    rejected,
)

_UNICODE_MINUS = "\u2212"
_CURRENCY = re.compile(r"[$\u20ac\u00a3]")
# AIDEV-NOTE: a 64-char cap and a 2-digit exponent keep the canonical form bounded (golden-pinned).
_MAX_NUMERIC_CHARS = 64
_GROUPED = re.compile(r"[-+]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")
_PLAIN = re.compile(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]{1,2})?")


def numeric(raw: str, args: OpArgs, /) -> StageResult:
    """Canonical decimal: currency and group commas removed, one trailing period dropped."""
    text = _CURRENCY.sub("", raw.strip().replace(_UNICODE_MINUS, "-")).strip()
    text = text.removesuffix(".")
    if len(text) > _MAX_NUMERIC_CHARS:
        return rejected("not_numeric")
    if _GROUPED.fullmatch(text):
        text = text.replace(",", "")
    if not _PLAIN.fullmatch(text):
        return rejected("not_numeric")
    return accepted(canonical_decimal(Decimal(text)))


def text(raw: str, args: OpArgs, /) -> StageResult:
    """Trim, collapse whitespace, casefold, then strip one trailing period."""
    value = " ".join(raw.split()).casefold()
    if value.endswith("."):
        value = value[:-1].rstrip()
    return accepted(value) if value else rejected("empty")


_SET_MAX_ITEMS = 256


def _item_text(item: object) -> str | None:
    """A list item as text: a str as is, a bool or a finite number in canonical JSON, else None."""
    if isinstance(item, str):
        return item
    try:
        return canonical_json(item) if isinstance(item, (bool, int, float)) else None
    except ValueError:
        return None  # a JSON number too big for a float (1e999) has no canonical form


def _listed(raw: str) -> list[str] | None:
    """The items of a JSON list answer, or None when it is not a flat list of scalars."""
    try:
        decoded = loads_bounded(raw)
    except ValueError:
        return None
    if not isinstance(decoded, list):
        return None
    items = [_item_text(item) for item in decoded]
    return None if None in items else [item for item in items if item is not None]


def set_(raw: str, args: OpArgs, /) -> StageResult:
    """A JSON list (or comma text) as its sorted, casefolded, distinct items in canonical JSON."""
    items = _listed(raw) if raw.lstrip().startswith("[") else raw.split(",")
    if items is None:
        return rejected("not_json")
    distinct = {" ".join(item.split()).casefold() for item in items} - {""}
    if len(distinct) > _SET_MAX_ITEMS:
        return rejected("too_large")
    return accepted(canonical_json(sorted(distinct))) if distinct else rejected("empty")


def identity(raw: str, args: OpArgs, /) -> StageResult:
    """No change."""
    return accepted(raw)


OPERATORS: tuple[OperatorDescriptor, ...] = (
    OperatorDescriptor("numeric", 1, "normalize", "Canonical decimal number.", numeric),
    OperatorDescriptor(
        "text",
        1,
        "normalize",
        "Trimmed, collapsed, casefolded text without one trailing period.",
        text,
    ),
    OperatorDescriptor("identity", 1, "normalize", "No change.", identity),
    OperatorDescriptor(
        "set",
        1,
        "normalize",
        "Sorted, casefolded, distinct list items as canonical JSON.",
        set_,
    ),
)

__all__ = ["OPERATORS"]

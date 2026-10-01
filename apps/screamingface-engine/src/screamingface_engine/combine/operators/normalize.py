"""Normalize operators: one raw value -> one comparable value, or a status (OME-1289, E4a).

FEATURE: members that write the same answer in different shapes vote together.
STORY: as an author of a majority-vote Candidate, `9`, `9.0` and `$9.` count as one answer.

Mental model: a stamp that writes every answer in one house style before the count. The numeric
stamp writes plain digits; the text stamp writes small, single-spaced words.

INVARIANT: each operator is pure; this module holds no mutable state (ports.py).
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
    rejected,
)

_UNICODE_MINUS = "−"
_CURRENCY = re.compile("[$\u20ac\u00a3]")
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
)

__all__ = ["OPERATORS"]

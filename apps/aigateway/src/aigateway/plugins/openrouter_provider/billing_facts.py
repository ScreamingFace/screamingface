"""Billing facts shared by the OpenRouter zero proofs (`zero_insurance`, `pre_output_refusal`).

FEATURE: cost of intelligence (OME-1287). A zero proof asks one question: did OpenRouter bill
this call? These helpers read money and work wherever they are in the reply, so the answer does
not depend on the reply format (owner decision 2026-10-27, OME-1746).

INVARIANT: a non-zero amount found anywhere keeps the cost unknown. A field that carries no money
never does.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

# WHY these words: OpenRouter names every money field with one of them (`cost`, `cost_usd`,
# `cost_details`, `server_tool_cost`, `amount_usd`). A new money field will likely do the same.
_MONEY_WORDS = ("cost", "amount")
# WHY: reading the prompt is not billed on a rejection or a refusal (Zero Completion Insurance),
# so input counts are not a sign of billed work.
_PROMPT_SIDE_USAGE_FIELDS = frozenset({"prompt_tokens", "total_tokens", "prompt_tokens_details"})


def is_zero(value: object) -> bool:
    """Absent or ``None`` (nothing reported), or a number equal to zero."""
    return value is None or (
        isinstance(value, int | float | Decimal) and not isinstance(value, bool) and value == 0
    )


def _as_count(value: object) -> object:
    """A count in ``usage``: text that is a number ("50") is still that number; other text (a
    label, a flag written as "false") is not a count."""
    if not isinstance(value, str):
        return value
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _leaves(value: object) -> Iterator[object]:
    """Every scalar inside ``value``. A flag (``bool``) is not an amount or a count, so it is
    skipped; text is kept for the caller to judge."""
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    elif not isinstance(value, bool):
        yield value


def _is_money_key(key: object) -> bool:
    return isinstance(key, str) and any(word in key.lower() for word in _MONEY_WORDS)


def _money_values(value: object) -> Iterator[object]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_money_key(key):
                # WHY: a money value that is not a number (for example "0.25") is not a zero.
                yield from _leaves(item)
            else:
                yield from _money_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _money_values(item)


def reports_a_charge(raw_response: Mapping[str, Any]) -> bool:
    """Whether any money field anywhere in the reply holds a non-zero (or non-numeric) value."""
    return any(not is_zero(amount) for amount in _money_values(raw_response))


def usage_shows_billed_work(raw_response: Mapping[str, Any]) -> bool:
    """Whether ``usage`` reports any work beyond reading the prompt (output, tools, a cost).
    ``usage`` that is not an object cannot show that no work was done."""
    usage = raw_response.get("usage")
    if usage is None:
        return False
    if not isinstance(usage, Mapping):
        return True
    return any(
        not is_zero(_as_count(leaf))
        for field, item in usage.items()
        if field not in _PROMPT_SIDE_USAGE_FIELDS
        for leaf in _leaves(item)
    )


__all__ = ["reports_a_charge", "usage_shows_billed_work"]

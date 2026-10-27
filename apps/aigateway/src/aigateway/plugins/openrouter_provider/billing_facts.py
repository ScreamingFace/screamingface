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


# WHY: these stages run a paid plugin or server tool. A prepared request without plugins or tools
# should never show one, but if it does, the stage can be billed.
_PAID_STAGE_TYPES = frozenset({"plugin", "server_tools"})
_TOP_LEVEL_OUTPUT_FIELDS = ("output", "content")
# WHY a list and not "every field": a new message field that is not output (a label, a flag)
# must not make every refusal unknown. Billed output normally also comes with `usage.cost`.
_MESSAGE_OUTPUT_FIELDS = (
    "content",
    "refusal",
    "reasoning",
    "reasoning_details",
    "tool_calls",
    "function_call",
    "audio",
    "images",
)


def is_zero(value: object) -> bool:
    """Absent or ``None`` (nothing reported), or a number equal to zero.

    INVARIANT: never raises. ``Decimal("sNaN") == 0`` raises, so a ``Decimal`` is tested with
    ``is_zero()``, which is false for every NaN.
    """
    if value is None:
        return True
    if isinstance(value, Decimal):
        return value.is_zero()
    return isinstance(value, int | float) and not isinstance(value, bool) and value == 0


def is_empty(value: object) -> bool:
    """Absent or ``None``, or an empty text, list or object: it carries no output."""
    return value is None or (isinstance(value, str | list | tuple | Mapping) and not value)


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


def has_no_output(raw_response: Mapping[str, Any], message: Mapping[str, Any]) -> bool:
    """Whether the message output fields and the top-level output fields are all empty."""
    return all(is_empty(message.get(field)) for field in _MESSAGE_OUTPUT_FIELDS) and all(
        is_empty(raw_response.get(field)) for field in _TOP_LEVEL_OUTPUT_FIELDS
    )


def pipeline_has_paid_stage(raw_response: Mapping[str, Any]) -> bool:
    """Whether ``openrouter_metadata.pipeline`` names a ``plugin`` or ``server_tools`` stage.

    The stage ``type`` is read as text wherever it is (a string, or text inside a list or object),
    so a ``type`` of any shape gives a result and never raises.
    """
    router = raw_response.get("openrouter_metadata")
    pipeline = router.get("pipeline") if isinstance(router, Mapping) else None
    if not isinstance(pipeline, list):
        return False
    return any(
        isinstance(stage, Mapping)
        and any(
            isinstance(name, str) and name in _PAID_STAGE_TYPES
            for name in _leaves(stage.get("type"))
        )
        for stage in pipeline
    )


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


__all__ = [
    "has_no_output",
    "is_empty",
    "pipeline_has_paid_stage",
    "reports_a_charge",
    "usage_shows_billed_work",
]

"""Proof for an OpenRouter refusal before output (spec 2026-10-26, P1' in §8).

FEATURE: cost of intelligence (OME-1287). Anthropic refuses some requests before the model writes
output. Through OpenRouter that reply is HTTP 200 with ``native_finish_reason: "refusal"``, no
output and no ``usage``, and OpenRouter keeps no generation record for it (live calls, 2026-10-26
and 2026-10-27). Nothing is billed, so the attempt's covered cost is zero.

INVARIANT: the proof reads only the facts that tell if OpenRouter billed the call: the refusal
signal, no output, no ``usage`` and no non-zero money field. Every other field of the reply,
``openrouter_metadata`` included, is ignored, so a new or changed field never makes the cost
unknown (owner decision 2026-10-27, spec §8).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .billing_facts import reports_a_charge

# WHY each is listed: any one of them carries model output, and output after a refusal starts is
# billed (a mid-stream refusal reports its `usage.cost`).
_EMPTY_TEXT_FIELDS = ("content", "refusal", "reasoning")
_EMPTY_LIST_FIELDS = ("reasoning_details", "tool_calls")


def _message_has_no_output(message: Mapping[str, Any]) -> bool:
    return all(message.get(field) in (None, "") for field in _EMPTY_TEXT_FIELDS) and all(
        message.get(field) in (None, []) for field in _EMPTY_LIST_FIELDS
    )


def proves_pre_output_refusal(
    raw_response: Mapping[str, Any],
    *,
    http_status: int | None,
    request_has_potential_auxiliary_charge: bool | None,
) -> bool:
    """Whether the raw body proves a refusal before output that OpenRouter did not bill."""
    if (
        http_status != 200
        or request_has_potential_auxiliary_charge is not False
        # WHY: a billed call carries `usage` with its cost; an embedded error is not a refusal.
        or raw_response.get("usage") is not None
        or raw_response.get("error") is not None
        or reports_a_charge(raw_response)
    ):
        return False
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return False
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return False
    message = choice.get("message")
    return (
        choice.get("finish_reason") == "content_filter"
        and choice.get("native_finish_reason") == "refusal"
        and isinstance(message, Mapping)
        and _message_has_no_output(message)
    )


__all__ = ["proves_pre_output_refusal"]

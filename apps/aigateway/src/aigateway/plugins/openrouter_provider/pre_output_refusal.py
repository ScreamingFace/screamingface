"""Fail-closed proof for an OpenRouter refusal before output (spec 2026-10-26, P1).

FEATURE: cost of intelligence (OME-1287). Anthropic refuses some requests before the model writes
output. Through OpenRouter that reply is HTTP 200 with ``native_finish_reason: "refusal"``, no
output and no ``usage``, and OpenRouter keeps no generation record for it (live call, 2026-10-26).
Nothing is billed, so the attempt's covered cost is zero.

INVARIANT: every condition must hold. A field this proof does not know, any output, or any usage
object keeps the evidence as the base mapper gave it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_RESPONSE_FIELDS = frozenset(
    {
        "id",
        "object",
        "created",
        "model",
        "provider",
        "system_fingerprint",
        "service_tier",
        "choices",
        "usage",
    }
)
_CHOICE_FIELDS = frozenset(
    {"index", "logprobs", "finish_reason", "native_finish_reason", "message"}
)
_MESSAGE_FIELDS = frozenset(
    {"role", "content", "refusal", "reasoning", "reasoning_details", "tool_calls"}
)
# WHY each is listed: any one of them carries model output, and output after a refusal starts is
# billed (a mid-stream refusal reports its `usage.cost`).
_EMPTY_TEXT_FIELDS = ("content", "refusal", "reasoning")
_EMPTY_LIST_FIELDS = ("reasoning_details", "tool_calls")


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _scalars_are_valid(raw_response: Mapping[str, Any]) -> bool:
    strings = ("id", "object", "model", "provider")
    nullable_strings = ("system_fingerprint", "service_tier")
    created = raw_response.get("created")
    return (
        all(field not in raw_response or type(raw_response[field]) is str for field in strings)
        and all(
            raw_response.get(field) is None or type(raw_response[field]) is str
            for field in nullable_strings
        )
        and ("created" not in raw_response or (type(created) is int and created >= 0))
    )


def _message_has_no_output(message: Mapping[str, Any]) -> bool:
    return (
        _MESSAGE_FIELDS.issuperset(message)
        and message.get("role", "assistant") == "assistant"
        and all(message.get(field) in (None, "") for field in _EMPTY_TEXT_FIELDS)
        and all(message.get(field) in (None, []) for field in _EMPTY_LIST_FIELDS)
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
        or not _RESPONSE_FIELDS.issuperset(raw_response)
        or raw_response.get("usage") is not None
        or not _scalars_are_valid(raw_response)
    ):
        return False
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return False
    choice = _mapping(choices[0])
    if choice is None or not _CHOICE_FIELDS.issuperset(choice):
        return False
    message = _mapping(choice.get("message"))
    return (
        choice.get("finish_reason") == "content_filter"
        and choice.get("native_finish_reason") == "refusal"
        and message is not None
        and _message_has_no_output(message)
    )


__all__ = ["proves_pre_output_refusal"]

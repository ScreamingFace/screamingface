"""Fail-closed proof for an OpenRouter refusal before output (spec 2026-10-26, P1).

FEATURE: cost of intelligence (OME-1287). Anthropic refuses some requests before the model writes
output. Through OpenRouter that reply is HTTP 200 with ``native_finish_reason: "refusal"``, no
output and no ``usage``, and OpenRouter keeps no generation record for it (live call, 2026-10-26).
Nothing is billed, so the attempt's covered cost is zero.

INVARIANT: every condition must hold. A field this proof does not know, any output, or any usage
object keeps the evidence as the base mapper gave it.

AIDEV-NOTE (spec §8): the gateway sends `X-OpenRouter-Metadata: enabled` on every call, so a prod
refusal always carries `openrouter_metadata`. A test body without it is not the prod shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .response_shape import (
    endpoints_are_valid,
    mapping,
    optional_count,
    optional_string,
    response_scalars_are_valid,
)

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
        "openrouter_metadata",
    }
)
# WHY no `pipeline` and no `attempts`: either can name a paid stage or a fallback attempt, and the
# live refusal (2026-10-27) carried neither. An unseen field keeps the cost unknown.
_ROUTER_FIELDS = frozenset(
    {
        "requested",
        "strategy",
        "region",
        "summary",
        "attempt",
        "is_byok",
        "endpoints",
        "generation_time",
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


def _router_metadata_is_plain(raw_response: Mapping[str, Any]) -> bool:
    """Absent, or a non-BYOK route whose every field is known and well typed (spec §8, 4a)."""
    if "openrouter_metadata" not in raw_response:
        return True
    router = mapping(raw_response["openrouter_metadata"])
    return (
        router is not None
        and _ROUTER_FIELDS.issuperset(router)
        # WHY: with BYOK the upstream bills our own key, so OpenRouter's missing record proves
        # nothing about what was charged.
        and router.get("is_byok") is False
        and all(
            optional_string(router, field)
            for field in ("requested", "strategy", "region", "summary")
        )
        and optional_count(router, "attempt")
        and optional_count(router, "generation_time")
        and endpoints_are_valid(router.get("endpoints"))
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
        or not response_scalars_are_valid(
            raw_response,
            strings=("id", "object", "model", "provider"),
            nullable_strings=("system_fingerprint", "service_tier"),
        )
        or not _router_metadata_is_plain(raw_response)
    ):
        return False
    choices = raw_response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return False
    choice = mapping(choices[0])
    if choice is None or not _CHOICE_FIELDS.issuperset(choice):
        return False
    message = mapping(choice.get("message"))
    return (
        choice.get("finish_reason") == "content_filter"
        and choice.get("native_finish_reason") == "refusal"
        and message is not None
        and _message_has_no_output(message)
    )


__all__ = ["proves_pre_output_refusal"]

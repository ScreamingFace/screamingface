"""Provider-neutral policy for bounded accounting mapper inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .types import MAX_TOKEN_COUNT, UsageSource

_MAPPER_HIDDEN_FIELDS: Final = frozenset(
    {"api_key", "messages", "system", "headers", "extra_headers", "client", "metadata"}
)


def bounded_count(value: object) -> int | None:
    """Return an exact JSON-safe nonnegative integer, never bool or coercion."""
    if type(value) is int and 0 <= value <= MAX_TOKEN_COUNT:
        return value
    return None


def mapping_or_none(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def safe_request_view(body: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return only scalar request fields that cannot carry prompts or credentials.

    INVARIANT: mappers never receive credentials or prompt content. The value-shape filter
    also drops structured values under future field names, so least privilege is structural.
    """
    return {
        key: value
        for key, value in body.items()
        if key not in _MAPPER_HIDDEN_FIELDS and not isinstance(value, (list, dict))
    }


def has_potential_auxiliary_charge(body: Mapping[str, Any]) -> bool:
    """Derive one bounded risk fact without retaining request content."""
    # WHY: provider error metadata is intentionally optional and may omit a paid stage. The
    # prepared request is authoritative about services the gateway itself asked to run.
    plugins = body.get("plugins")
    if plugins not in (None, []):
        return True

    tools = body.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            return True
        for tool in tools:
            if not isinstance(tool, Mapping):
                return True
            tool_type = tool.get("type")
            if isinstance(tool_type, str) and tool_type.startswith("openrouter:"):
                return True

    messages = body.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            # INVARIANT: inspect only the discriminator; never retain or return file/prompt data.
            if isinstance(part, Mapping) and part.get("type") == "file":
                return True
    return False


def final_detail_or_none(value: object, source: UsageSource) -> int | None:
    """Suppress synthetic zero details on converted/cache fallback evidence."""
    token_count = bounded_count(value)
    if source != "provider_raw_response" and token_count == 0:
        return None
    return token_count


def cache_write_tokens(prompt_details: Mapping[str, Any], source: UsageSource) -> int | None:
    """Read raw then converted cache-write aliases by presence, never truthiness."""
    for key in ("cache_write_tokens", "cache_creation_tokens"):
        if key in prompt_details:
            return final_detail_or_none(prompt_details[key], source)
    return None


def usage_and_source(
    raw_response: Mapping[str, Any] | None,
    final_response: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, UsageSource]:
    """Prefer raw provider evidence over the converted response fallback."""
    raw_usage = mapping_or_none((raw_response or {}).get("usage"))
    if raw_usage is not None:
        return raw_usage, "provider_raw_response"
    final_usage = mapping_or_none((final_response or {}).get("usage"))
    if final_usage is not None:
        return final_usage, "provider_converted_response"
    return None, "provider_raw_response"


def response_string(
    raw_response: Mapping[str, Any] | None,
    final_response: Mapping[str, Any] | None,
    *,
    field: str,
) -> str | None:
    """Return one non-empty response identifier, preferring raw evidence."""
    for candidate in (raw_response, final_response):
        value = (candidate or {}).get(field)
        if isinstance(value, str) and value:
            return value
    return None

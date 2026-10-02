from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aigateway.core.http_status import valid_http_error_status
from aigateway.core.provider_error_text import message_from_error_object

_ERROR_TYPES = frozenset(
    {
        "authentication",
        "permission_denied",
        "payment_required",
        "rate_limit_exceeded",
        "provider_overloaded",
        "provider_unavailable",
        "invalid_request",
        "not_found",
        "server",
        "timeout",
        "unmapped",
    }
)


@dataclass(frozen=True, slots=True)
class EmbeddedOpenRouterError:
    found: bool = False
    status: int | None = None
    error_type: str | None = None
    # OME-1136: the allowlisted, UN-sanitized provider text (`error.message`, or one level of
    # `metadata.raw`). Only `_embedded_error_exception` may render it, through the screen.
    # WHY repr=False: a repr lands in logs and assertion output; the text is unscreened here.
    message: str | None = field(default=None, repr=False)


def _embedded_error_status(error: Any) -> int | None:
    if not isinstance(error, dict):
        return None
    for key in ("status", "status_code", "code"):
        status = valid_http_error_status(error.get(key))
        if status is not None:
            return status
    return None


def _top_level_error_is_meaningful(error: Any) -> bool:
    """Match LiteLLM's benign top-level error exception without weakening status checks."""
    if error is None:
        return False
    if isinstance(error, dict):
        return (
            bool(error.get("message", ""))
            or error.get("code") is not None
            or error.get("status") is not None
            or error.get("status_code") is not None
        )
    if isinstance(error, str):
        return bool(error)
    return True


def _error_type(error: Any) -> str | None:
    metadata = error.get("metadata") if isinstance(error, dict) else None
    value = metadata.get("error_type") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) and value in _ERROR_TYPES else None


def _with_error(current: EmbeddedOpenRouterError, error: Any) -> EmbeddedOpenRouterError:
    return EmbeddedOpenRouterError(
        found=True,
        status=current.status if current.status is not None else _embedded_error_status(error),
        error_type=current.error_type if current.error_type is not None else _error_type(error),
        message=current.message
        if current.message is not None
        else message_from_error_object(error),
    )


def _with_first_raw_error(
    current: EmbeddedOpenRouterError,
    error: Any,
) -> EmbeddedOpenRouterError:
    if current.found:
        return current
    return EmbeddedOpenRouterError(
        found=True,
        status=_embedded_error_status(error),
        error_type=_error_type(error),
        message=message_from_error_object(error),
    )


def find_converted_error(payload: dict[str, Any]) -> EmbeddedOpenRouterError:
    """Inspect the LiteLLM-converted response shape used by normal chat dispatch."""
    result = EmbeddedOpenRouterError()
    top_level_error = payload.get("error")
    if _top_level_error_is_meaningful(top_level_error):
        result = _with_error(result, top_level_error)

    choices = payload.get("choices")
    for choice in choices if isinstance(choices, list) else []:
        if not isinstance(choice, dict):
            continue
        if choice.get("error") is not None:
            result = _with_error(result, choice.get("error"))
        for holder in (choice, choice.get("message")):
            if not isinstance(holder, dict):
                continue
            fields = holder.get("provider_specific_fields")
            if not isinstance(fields, dict):
                continue
            if fields.get("error") is not None:
                result = _with_error(result, fields.get("error"))
            if fields.get("native_finish_reason") == "error":
                result = EmbeddedOpenRouterError(
                    found=True,
                    status=result.status,
                    error_type=result.error_type,
                    message=result.message,
                )
    return result


def find_raw_error(payload: dict[str, Any]) -> EmbeddedOpenRouterError:
    """Inspect direct OpenRouter HTTP JSON before LiteLLM conversion."""
    result = EmbeddedOpenRouterError()
    top_level_error = payload.get("error")
    if _top_level_error_is_meaningful(top_level_error):
        result = _with_first_raw_error(result, top_level_error)

    choices = payload.get("choices")
    for choice in choices if isinstance(choices, list) else []:
        if not isinstance(choice, dict):
            continue
        if choice.get("error") is not None:
            result = _with_first_raw_error(result, choice.get("error"))
        if choice.get("finish_reason") == "error":
            result = EmbeddedOpenRouterError(
                found=True,
                status=result.status,
                error_type=result.error_type,
                message=result.message,
            )
    return result


def _find_embedded_error(payload: dict[str, Any]) -> tuple[bool, int | None]:
    """Compatibility shape retained for existing OpenRouter chat handling."""
    result = find_converted_error(payload)
    return result.found, result.status

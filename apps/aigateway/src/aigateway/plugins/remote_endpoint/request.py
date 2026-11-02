"""The one chat request a configured endpoint receives, and the text contract it carries.

# FEATURE: hosted BYOM — the `openai-chat-basic-v1` request is text messages plus an optional
# `max_tokens`: no tools, images, other content parts or other roles.
# INVARIANT: readiness and dispatch both build the upstream body with `chat_request`, so the probe
# that publishes a key is the request an ordinary chat later sends: it differs only in messages,
# and in `max_tokens` when a caller sets one.
# INVARIANT: `check_text_messages` runs in `prepare_chat_body`, before the route reads a key, so a
# request outside the contract costs no credential read and no upstream I/O.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import ParameterProjectionRule
from aigateway.core.content_parts import check_messages
from aigateway.core.standard_parameters import MAX_TOKENS_SCHEMA, direct_rule

from .definitions import ChatTarget

_ROLES = frozenset({"system", "user", "assistant"})
_MESSAGE_FIELDS = frozenset({"role", "content"})
_AUTH: tuple[AuthMode, ...] = ("api_key",)
# WHY only max_tokens: it is the one optional field the contract names. WHY `keyed`: it changes
# the answer, so two chats that differ only in it must not share a stored row.
CHAT_PARAMETER_RULES: tuple[ParameterProjectionRule, ...] = (
    direct_rule(
        "max_tokens",
        auth_modes=_AUTH,
        schema=MAX_TOKENS_SCHEMA,
        cache_behavior="keyed",
        projection_revision="remote-endpoint-openai-chat-basic-v1",
    ),
)


def chat_parameter_rules(auth_type: AuthMode | None) -> tuple[ParameterProjectionRule, ...]:
    return CHAT_PARAMETER_RULES if auth_type in (None, *_AUTH) else ()


def chat_request(target: ChatTarget, messages: Any, *, max_tokens: Any = None) -> dict[str, Any]:
    request = {"model": target.upstream_model, "messages": messages}
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
    return request


def check_text_messages(messages: Any, *, provider: str) -> None:
    """Refuse, with a 422, any ``messages`` value outside the text contract."""
    if not isinstance(messages, list) or not messages:
        raise _unsupported_message(provider)
    # WHY the shared check first: media and unknown typed parts get the gateway's one typed
    # refusal, `unsupported_content_part`, exactly as every other provider reports them.
    check_messages(messages, provider=provider, media_roles=frozenset(), allow_remote_images=False)
    if not is_text_contract(messages):
        raise _unsupported_message(provider)


def is_text_contract(messages: Any) -> bool:
    """Whether ``messages`` is a non-empty list of text messages; never raises."""
    return isinstance(messages, list) and bool(messages) and all(map(_is_text_message, messages))


def _is_text_message(message: Any) -> bool:
    if not isinstance(message, dict) or not message.keys() <= _MESSAGE_FIELDS:
        return False
    # WHY isinstance before membership: `role` is untrusted JSON, and a list is unhashable.
    role = message.get("role")
    return isinstance(role, str) and role in _ROLES and isinstance(message.get("content"), str)


def _unsupported_message(provider: str) -> HTTPException:
    # INVARIANT: the refusal echoes no caller value.
    return HTTPException(
        status_code=422,
        detail={
            "code": "unsupported_message",
            "provider": provider,
            "message": (
                f"{provider} accepts a non-empty list of system, user and assistant messages, "
                "each with only a role and a text content"
            ),
        },
    )

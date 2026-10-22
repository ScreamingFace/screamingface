"""The HTTP 200 response the `openai-chat-basic-v1` contract promises, and its one decoder.

# INVARIANT: readiness and dispatch both call `decode_completion` on the raw response, so a key is
# published only after the endpoint answered exactly what a later chat call will be held to:
# a JSON media type, strict finite JSON within the structure bounds, and the completion shape.
# Readiness may be stricter only in its size and time budget, which its session enforces first.
# WHY text is not required: an empty or null `content` is a legal assistant answer; the contract
# fixes the structure of `choices` and each `message`, not that the model said something.
# WHY `role` may be absent: some compatible servers omit it; when present it must be the
# assistant's. `content` itself must be present, so an empty `message` is not an answer.
# INVARIANT: the metadata a caller reads is what it claims to be: each `finish_reason` is text or
# null, and `usage`, when present, is an object whose three token counts, when present, are
# integers from 0 to 2**53 - 1. Other usage fields are provider detail and pass as sent.
# INVARIANT: a response that also reports an error, as a non-null `error` on the envelope or on
# any choice, is not a completion: the caller would read a failure as a success.
"""

from __future__ import annotations

import json
from typing import Any

from aigateway.core.json_bounds import assert_bounded_json

_MAX_JSON_DEPTH = 16
_MAX_JSON_NODES = 50_000
_TOKEN_COUNTS = ("prompt_tokens", "completion_tokens", "total_tokens")
# WHY 2**53 - 1: the largest integer a JSON number keeps exactly in JavaScript, and the bound the
# gateway's usage accounting already applies. Local because plugins never import each other.
_MAX_TOKEN_COUNT = 2**53 - 1


def decode_completion(content_type: str | None, body: bytes) -> dict[str, Any] | None:
    """The completion carried by a 200 response, or None when the response breaks the contract."""
    if (content_type or "").split(";", 1)[0].strip().lower() != "application/json":
        return None
    try:
        value = json.loads(body, parse_constant=_reject_non_finite)
        assert_bounded_json(
            value, max_depth=_MAX_JSON_DEPTH, max_nodes=_MAX_JSON_NODES, require_finite=True
        )
    except (ValueError, RecursionError):
        return None
    return value if _is_chat_completion(value) else None


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _is_chat_completion(value: Any) -> bool:
    """Whether ``value`` is an error-free object with well-formed choices and usage."""
    if not isinstance(value, dict) or value.get("error") is not None:
        return False
    if not _is_usage(value.get("usage")):
        return False
    choices = value.get("choices")
    return isinstance(choices, list) and bool(choices) and all(map(_is_choice, choices))


def _is_usage(usage: Any) -> bool:
    if usage is None:
        return True
    return isinstance(usage, dict) and all(
        name not in usage or _is_count(usage[name]) for name in _TOKEN_COUNTS
    )


def _is_count(value: Any) -> bool:
    # WHY `type(...) is int`: a JSON `true` decodes to a bool, which isinstance counts as an int.
    return type(value) is int and 0 <= value <= _MAX_TOKEN_COUNT


def _is_choice(choice: Any) -> bool:
    if not isinstance(choice, dict) or choice.get("error") is not None:
        return False
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        return False
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
        return False
    return "content" in message and (
        message["content"] is None or isinstance(message["content"], str)
    )

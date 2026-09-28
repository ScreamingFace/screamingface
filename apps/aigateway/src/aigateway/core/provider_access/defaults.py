"""Merging stored request defaults into a chat body (OME-1200, spec §3.4 row 3).

Relocated verbatim from `routes/chat_credentials.py::_apply_defaults`; the shim re-exports it.
"""

from __future__ import annotations

from typing import Any

from .types import RequestDefaults

_BUCKET_A_FIELDS = (
    "model",
    "max_tokens",
    "temperature",
    "timeout_seconds",
    "reasoning_effort",
)


def _has_system_message(body: dict[str, Any]) -> bool:
    return any(m.get("role") == "system" for m in body.get("messages", []))


def _should_apply_default(plugin: Any, field: str) -> bool:
    checker = getattr(plugin, "should_apply_profile_default", None)
    return bool(checker(field)) if callable(checker) else True


def apply_defaults(
    body: dict[str, Any], defaults: RequestDefaults, plugin: Any
) -> tuple[dict[str, Any], frozenset[str]]:
    """Body wins per field. Fields the body omits get the stored default.

    Returns the merged body together with the CLASSIFIER REQUEST PATHS this call wrote, so a
    later parameter rejection can be attributed to the stored defaults instead of to the
    request (OME-638).

    # INVARIANT: the reported paths are request paths, NOT `RequestDefaults` field names —
    # `timeout_seconds` is reported as `timeout`, the name the classifier sees. A set keyed by
    # the field name could never match a rejected path, so every stored-default fault would be
    # silently blamed on the caller.
    # INVARIANT: a default only ever occupies a path the body omitted. That is what makes the
    # returned set a sound attribution rather than a guess, and it is why the caller-supplied
    # paths and these paths are always disjoint.
    # AIDEV-NOTE: the `model` default is unreachable from /v1/chat/completions — the route
    # rejects a body whose `model` is missing or not provider-prefixed well before this runs.
    # It stays because this helper merges the defaults as a whole.
    """
    written: set[str] = set()
    if (
        defaults.system_prompt
        and not _has_system_message(body)
        and _should_apply_default(plugin, "system_prompt")
    ):
        body.setdefault("messages", [])
        body["messages"] = [
            {"role": "system", "content": defaults.system_prompt},
            *body["messages"],
        ]
        written.add("messages")
    for field in _BUCKET_A_FIELDS:
        gateway_field = "timeout" if field == "timeout_seconds" else field
        if not _should_apply_default(plugin, field):
            continue
        value = getattr(defaults, field)
        if value is not None and gateway_field not in body:
            body[gateway_field] = value
            written.add(gateway_field)
    return body, frozenset(written)

"""Small, policy-free primitives for decoding external wire values."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import NoReturn, cast

type _Invalid = Callable[[str], NoReturn]

# httpx request-extension key marking a request as safe to re-send after an interactive
# Cloudflare Access login.
# INVARIANT: default-deny. Replay safety is a property of the REQUEST, not of the response
# status, so a call site that forgets the marker pays one extra round trip — never an extra
# paid Run. "GET /?q=" starts billable work despite being a GET and is never marked.
# WHY here: this module has no dependencies, so marking a call site never drags the Access
# stack (and its native crypto) into an import path that must stay cheap.
_REPLAY_SAFE = "screamingface_replay_safe"
# httpx request-extension key marking a request that may not start an interactive Cloudflare
# Access login (E5 P2 spec D15): a follow's result fetch. A challenge then raises
# `LOGIN_NOT_STARTED` instead of opening a browser, and the follow ends with how to resume.
_NO_LOGIN = "screamingface_no_login"
LOGIN_NOT_STARTED = "access_login_not_started"


def mapping(value: object, label: str, invalid: _Invalid) -> Mapping[str, object]:
    """Return a JSON-like mapping or delegate the domain-specific failure."""

    if not isinstance(value, Mapping):
        invalid(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def text(value: object, label: str, invalid: _Invalid) -> str:
    """Return stripped non-blank wire text or delegate failure policy."""

    if not isinstance(value, str) or not value.strip():
        invalid(f"{label} must be non-blank text")
    return cast(str, value).strip()


def text_tuple(value: object, label: str, invalid: _Invalid) -> tuple[str, ...]:
    """Return a JSON array of non-blank texts as a tuple, or delegate failure policy."""

    if not isinstance(value, list):
        invalid(f"{label} must be an array")
    return tuple(text(item, label, invalid) for item in cast(list[object], value))


__all__: list[str] = []

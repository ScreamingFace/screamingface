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


def detail_code(body: object) -> str | None:
    """Return the stripped, non-blank `detail.code` of a coded error body, else None (D7 X-8)."""

    detail = body.get("detail") if isinstance(body, Mapping) else None
    code = detail.get("code") if isinstance(detail, Mapping) else None
    return code.strip() if isinstance(code, str) and code.strip() else None


__all__: list[str] = []

"""OME-1323 Stage C (D2): refuse a write that still carries saved Profile `defaults`.

FEATURE: the Profile write surface — tenant/admin API-key PUT, OAuth start, tenant/admin PATCH.

STORY: as an old client that still sends `defaults`, I get an explicit `422` naming the field,
not a silent accept and not a silent ignore: request parameters now travel with each chat
request, and system instructions as system-role messages.

INVARIANT: a PRESENT `defaults` member — even `null` — is refused before any side effect and
before the request model is validated; an OMITTED member changes nothing. The refusal names the
field and nothing else: no key, prompt or submitted value is echoed or logged.

AIDEV-NOTE: the refusal runs as a DEPENDENCY that itself depends on authentication, never from
inside the handler. FastAPI solves sub-dependencies before it validates body parameters, and it
calls no handler once the body fails — so a handler-side check would let an incomplete body
(`defaults` plus a missing `api_key` or `name`) fall through to the generic validation 422.
Nesting it under the auth dependency keeps authentication first: FastAPI does not call a
dependency whose own dependencies failed.

AIDEV-NOTE: the request models no longer declare `defaults`, and Pydantic ignores an unknown
member by default — so the refusal reads the raw JSON body instead. Do not switch the models to
`extra="forbid"` to get the same effect: that would widen the contract to every unknown field,
and its validation error would echo the submitted input.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import Depends, HTTPException, Request

from ..core.auth.middleware import CurrentAccount
from ..core.auth.models import BaseAccount

DEFAULTS_NOT_ACCEPTED: Final = "defaults_not_accepted"
_FIELD: Final = "defaults"
_MESSAGE: Final = (
    "saved profile defaults are no longer accepted; send model parameters with each "
    "chat request and system instructions as system-role messages"
)


async def refuse_saved_defaults(request: Request) -> None:
    """Raise `422 defaults_not_accepted` when the JSON body carries a `defaults` member at all.

    WHY presence, not value: `null` used to mean "keep the stored values", so accepting it would
    let an old client believe it still controls them.
    """
    # WHY no re-parse cost: FastAPI read this body before solving dependencies, and Starlette
    # caches the parsed JSON on the request.
    try:
        body = await request.json()
    except (ValueError, RecursionError):
        # WHY let it through: a body that is not JSON carries no `defaults` member, and FastAPI's
        # own (app-wide redacted) validation answer is the right one for it — never a 500.
        # `RecursionError` is what `json.loads` raises on input nested too deeply to parse.
        return
    if isinstance(body, dict) and _FIELD in body:
        raise HTTPException(
            status_code=422,
            detail={"code": DEFAULTS_NOT_ACCEPTED, "field": _FIELD, "message": _MESSAGE},
        )


async def _account_refusing_saved_defaults(
    request: Request, current: CurrentAccount
) -> BaseAccount:
    """The tenant caller, once authenticated, with a `defaults`-carrying body refused."""
    await refuse_saved_defaults(request)
    return current


AccountRefusingSavedDefaults = Annotated[BaseAccount, Depends(_account_refusing_saved_defaults)]

"""OME-1323 Stage C (D2): refuse a write that still carries saved Profile `defaults`.

FEATURE: the D18 admin API-key PUT (`routes/admin_connections.py`).

STORY: as an old client that still sends `defaults`, I get an explicit `422` naming the field,
not a silent accept and not a silent ignore: request parameters now travel with each chat
request, and system instructions as system-role messages.

INVARIANT: a PRESENT `defaults` member — even `null` — is refused before any side effect and
before the request model is validated; an OMITTED member changes nothing. The refusal names the
field and nothing else: no key, prompt or submitted value is echoed or logged.

WHY a helper the caller awaits: the PUT reads its raw body in a dependency that runs after
authentication, and it calls this before its generic unknown-member refusal — so authentication
still answers first and an old client still learns why.

AIDEV-NOTE: the request models no longer declare `defaults`, and Pydantic ignores an unknown
member by default — so the refusal reads the raw JSON body instead. Do not switch the models to
`extra="forbid"` to get the same effect: that would widen the contract to every unknown field,
and its validation error would echo the submitted input.
"""

from __future__ import annotations

from typing import Final

from fastapi import HTTPException, Request

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
    # WHY no re-parse cost: the caller already parsed this body, and Starlette caches the parsed
    # JSON on the request.
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

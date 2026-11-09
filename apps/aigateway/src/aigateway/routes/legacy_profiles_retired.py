"""The 13 retired legacy Profile routes (OME-1209 Stage E, E3, spec R1).

# FEATURE: Stage E route retirement — a caller still on the Profile API learns which Connection-era
# route replaces the one it called, instead of an empty list or a silently skipped operation.
# INVARIANT: every retired route answers 410 from the static table below, before reading the body
# and before any authentication, storage or audit I/O. It has no dependency to run and no schema
# to validate, so a malformed body or an unknown caller gets the same answer as anyone else.
# WHY no caller identity: the answer carries nothing but a public route name, and asking for an
# identity would put a session lookup in front of a refusal that must touch no storage.
# WHY the `detail` envelope: every gateway refusal is `{"detail": {"code": ...}}`, which is what
# the SDK and the Admin UI decode (owner decision 2026-10-18).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

RETIRED_CODE = "legacy_profile_api_retired"

# (method, retired path template) → successor "<method> <path template>", per spec §2.1. Where the
# spec lists two successors, the first is the one named here.
# WHY None: a D18 pair has no name or label to edit, so the admin PATCH has no successor.
RETIRED_ROUTES: dict[tuple[str, str], str | None] = {
    ("GET", "/v1/auth/profiles"): "GET /v1/provider-access",
    ("GET", "/v1/auth/{provider}/profiles"): "GET /v1/provider-access",
    ("POST", "/v1/auth/{provider}/profiles"): "POST /v1/oauth/connections",
    ("GET", "/v1/auth/{provider}/profiles/{name}"): "GET /v1/oauth/connections/{connection_id}",
    (
        "GET",
        "/v1/auth/{provider}/profiles/{name}/status",
    ): "GET /v1/oauth/connections/{connection_id}",
    (
        "PATCH",
        "/v1/auth/{provider}/profiles/{name}",
    ): "PATCH /v1/oauth/connections/{connection_id}",
    (
        "PUT",
        "/v1/auth/{provider}/profiles/{name}/api-key",
    ): "POST /v1/oauth/connections/api-key",
    (
        "DELETE",
        "/v1/auth/{provider}/profiles/{name}",
    ): "DELETE /v1/oauth/connections/{connection_id}",
    (
        "POST",
        "/v1/auth/{provider}/profiles/{name}/refresh",
    ): "POST /v1/oauth/connections/{connection_id}/refresh",
    (
        "GET",
        "/v1/admin/accounts/{account_id}/profiles",
    ): "GET /v1/admin/accounts/{account_id}/connections",
    ("PATCH", "/v1/admin/accounts/{account_id}/profiles/{provider}/{name}"): None,
    (
        "PUT",
        "/v1/admin/accounts/{account_id}/profiles/{provider}/{name}/api-key",
    ): "PUT /v1/admin/accounts/{account_id}/connections/{provider}/api-key",
    (
        "DELETE",
        "/v1/admin/accounts/{account_id}/profiles/{provider}/{name}",
    ): "DELETE /v1/admin/accounts/{account_id}/connections/{provider}",
}

# WHY a plain APIRouter: the admin paths must not inherit the admin audit route class — a retired
# route writes no audit record.
router = APIRouter()


def _retired_endpoint(
    method: str, path: str, successor: str | None
) -> Callable[[], Awaitable[JSONResponse]]:
    message = (
        f"{method} {path} is retired; use {successor}"
        if successor is not None
        else f"{method} {path} is retired and has no successor"
    )

    async def retired() -> JSONResponse:
        return JSONResponse(
            status_code=410,
            content={"detail": {"code": RETIRED_CODE, "message": message, "successor": successor}},
            headers={"Cache-Control": "private, no-store"},
        )

    return retired


for (_method, _path), _successor in RETIRED_ROUTES.items():
    router.add_api_route(
        _path,
        _retired_endpoint(_method, _path, _successor),
        methods=[_method],
        include_in_schema=False,
    )

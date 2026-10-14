"""The D18 successor admin surface: pair-addressed Connections (OME-1497, G1).

# FEATURE: OME-1138 D18 (contract §2, §6.1) — `/v1/admin/accounts/{account_id}/connections`
# addresses the one credential of an `(account, provider)` pair; no Profile name, selector,
# defaults or public Connection id. A thin shell over `core.provider_access.pair_admin`.
# INVARIANT: every response of these routes — success, auth refusal, 4xx and 503 — carries
# `Cache-Control: private, no-store`, and the audit line records the authenticated actor and the
# FINAL status (refusals are rendered before `AdminAuditRoute` records it).
# INVARIANT: a nonblank `X-Profile` is refused after authentication with the existing
# `x_profile_unsupported` body; unrelated admin routes get no new selector policy.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from ..core.admin_connection_schemas import (
    AdminConnectionConflictOut,
    AdminConnectionList,
    AdminConnectionOut,
)
from ..core.auth.admin import AdminPrincipal, CurrentAdmin
from ..core.provider_access import SelectorUnsupported, pair_inventory, store_reads
from ..unhandled_errors import unhandled_exception_handler
from .admin import AdminAuditRoute, _note_actor, _require_account
from .provider_access_http import (
    pair_conflict_detail,
    render_refusal,
    successor_refusals_as_http,
)

NO_STORE = "private, no-store"
_UNSUPPORTED_METHODS = ["CONNECT", "DELETE", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"]


class AdminConnectionsRoute(AdminAuditRoute):
    """`AdminAuditRoute` plus `Cache-Control: private, no-store` on every response (§6.1)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        audited_handler = super().get_route_handler()

        async def no_store_handler(request: Request) -> Response:
            try:
                response = await audited_handler(request)
            except StarletteHTTPException as exc:
                # WHY mutate and re-raise: the app's HTTP handlers render `exc.headers`, so the
                # body and status stay exactly what the refusal said.
                exc.headers = {**(exc.headers or {}), "Cache-Control": NO_STORE}
                raise
            except RequestValidationError as exc:
                # WHY render here: a validation error carries no headers; the app's own (redacted)
                # handler renders the body, and this route adds the header to it.
                handler = request.app.exception_handlers.get(
                    RequestValidationError, request_validation_exception_handler
                )
                response = await handler(request, exc)
            except Exception as exc:
                # INVARIANT: the route's mandatory no-store policy includes an unexpected 500.
                # Reuse the app's fixed, sanitized handler; never render exception text here.
                response = await unhandled_exception_handler(request, exc)
            response.headers["Cache-Control"] = NO_STORE
            return response

        return no_store_handler


router = APIRouter(prefix="/v1/admin", tags=["Admin"], route_class=AdminConnectionsRoute)


async def _successor_admin(request: Request, admin: CurrentAdmin) -> AdminPrincipal:
    """The authenticated admin, with a nonblank `X-Profile` refused (§6.1).

    # WHY a dependency: it runs after authentication and before any handler I/O, and the audit
    # line still names who was refused.
    # INVARIANT: every repeated field is judged — a blank first value cannot hide a later one;
    # blank or whitespace-only counts as absent. The value is never echoed.
    """
    _note_actor(request, admin)
    if any(value.strip() for value in request.headers.getlist("X-Profile")):
        raise render_refusal(SelectorUnsupported())
    return admin


SuccessorAdmin = Annotated[AdminPrincipal, Depends(_successor_admin)]


@router.get(
    "/accounts/{account_id}/connections",
    response_model=AdminConnectionList,
    operation_id="list_admin_account_connections",
)
async def list_admin_account_connections(
    request: Request, admin: SuccessorAdmin, account_id: UUID
) -> AdminConnectionList:
    """List one tenant's provider credentials: one Connection or one conflict per provider."""
    with successor_refusals_as_http():
        with store_reads():
            await _require_account(account_id)
        inventory = await pair_inventory(request.app, str(account_id))
    return AdminConnectionList(
        connections=[
            AdminConnectionOut(
                provider=credential.provider,
                auth_type=credential.auth_type,
                credential_state=credential.credential_state,
                masked_key_hint=None,
                last_refreshed_at=credential.last_refreshed_at,
            )
            for credential in inventory.credentials
        ],
        conflicts=[
            AdminConnectionConflictOut.model_validate(pair_conflict_detail(conflict))
            for conflict in inventory.conflicts
        ],
    )


@router.api_route(
    "/accounts/{account_id}/connections",
    methods=_UNSUPPORTED_METHODS,
    include_in_schema=False,
)
async def reject_admin_connections_method(
    request: Request, admin: SuccessorAdmin, account_id: UUID
) -> None:
    """Authenticate and audit an unsupported method instead of Starlette's unaudited 405."""
    del request, admin, account_id
    raise HTTPException(status_code=405, headers={"Allow": "GET"})


@router.api_route(
    "/accounts/{account_id}/connections/",
    methods=["GET", *_UNSUPPORTED_METHODS],
    include_in_schema=False,
)
async def redirect_admin_connections_trailing_slash(
    request: Request, admin: SuccessorAdmin, account_id: UUID
) -> None:
    """Authenticate and audit the canonical-path redirect."""
    del admin, account_id
    location = str(request.url.replace(path=request.url.path.rstrip("/")))
    raise HTTPException(status_code=307, headers={"Location": location})

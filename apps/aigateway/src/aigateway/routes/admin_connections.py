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

import email.message
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from ..core.admin_connection_schemas import (
    AdminConnectionConflictOut,
    AdminConnectionList,
    AdminConnectionOut,
    SetAdminConnectionApiKeyRequest,
)
from ..core.auth.admin import AdminPrincipal, CurrentAdmin
from ..core.provider_access import (
    PairCredential,
    PairMutation,
    ProviderUnknown,
    SelectorUnsupported,
    delete_pair,
    pair_inventory,
    set_pair_api_key,
    store_reads,
)
from ..unhandled_errors import unhandled_exception_handler
from .admin import AdminAuditRoute, _note_actor, _require_account
from .api_key_validation import normalize_api_key, require_valid_api_key
from .auth import _close_loopback_callback
from .provider_access_http import (
    pair_conflict_detail,
    render_refusal,
    successor_refusals_as_http,
)
from .saved_defaults_refusal import refuse_saved_defaults

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

_INVALID_REQUEST = {
    "code": "invalid_credential_request",
    "message": "A valid API-key request body is required.",
}
_UNSUPPORTED_FIELDS = {
    "code": "unsupported_credential_fields",
    "message": "Only api_key is accepted.",
}


async def _api_key_body(request: Request, admin: SuccessorAdmin) -> SecretStr:
    """The PUT body's key, once authenticated; every other shape is a secret-safe 422 (§6.1).

    # WHY read the raw body here and declare no body parameter: FastAPI parses a declared body
    # BEFORE it solves dependencies, so a malformed body would answer 422 ahead of the 401/403,
    # and its validation error would carry the input. Here authentication runs first, and each
    # refusal is a static `{code, message}` — no field name, value or parser text.
    # INVARIANT: `defaults` (even `null`) keeps its existing refusal; it is judged before the
    # generic unknown-member refusal so an old client still learns why.
    """
    del admin
    if not _is_json(request.headers.get("content-type")):
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST)
    try:
        body = await request.json()
    except (ValueError, RecursionError):
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST) from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST)
    if "defaults" in body:
        await refuse_saved_defaults(request)
    if set(body) - {"api_key"}:
        raise HTTPException(status_code=422, detail=_UNSUPPORTED_FIELDS)
    api_key = body.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise HTTPException(status_code=422, detail=_INVALID_REQUEST)
    return SecretStr(api_key)


def _is_json(content_type: str | None) -> bool:
    """FastAPI's strict Content-Type rule (default since 0.132), kept for the raw-body read.

    # INVARIANT: an absent or non-JSON Content-Type is never parsed as JSON. A browser sends such
    # a body cross-site without a CORS preflight; with `auth_mode=disabled` nothing else stops it.
    # WHY `email.message`: the same parser FastAPI uses, so parameters (`; charset=utf-8`) and the
    # `+json` suffix are judged exactly as on every declared-body route.
    """
    if not content_type:
        return False
    message = email.message.Message()
    message["content-type"] = content_type
    if message.get_content_maintype() != "application":
        return False
    subtype = message.get_content_subtype()
    return subtype == "json" or subtype.endswith("+json")


ApiKeyBody = Annotated[SecretStr, Depends(_api_key_body)]
_PUT_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": SetAdminConnectionApiKeyRequest.model_json_schema()}
        },
    }
}


def _connection_out(credential: PairCredential) -> AdminConnectionOut:
    return AdminConnectionOut(
        provider=credential.provider,
        auth_type=credential.auth_type,
        credential_state=credential.credential_state,
        masked_key_hint=None,
        last_refreshed_at=credential.last_refreshed_at,
    )


async def _drop_pending_flows(
    request: Request, account_id: str, provider: str, mutation: PairMutation
) -> None:
    """After commit: end the pair's pending OAuth flows — only those naming its captured targets.

    # WHY after commit: a flow dropped before a rolled-back mutation would strand the user's
    # sign-in for nothing; a late callback is still fenced by the generation this write advanced.
    """
    states = request.app.state.pending_auth.pop_for_pair(
        account_id,
        provider,
        profile_names=mutation.profile_names,
        connection_ids=mutation.connection_ids,
    )
    for state in states:
        await _close_loopback_callback(request.app, state)


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
        connections=[_connection_out(credential) for credential in inventory.credentials],
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


@router.put(
    "/accounts/{account_id}/connections/{provider}/api-key",
    response_model=AdminConnectionOut,
    operation_id="set_admin_account_connection_api_key",
    openapi_extra=_PUT_BODY,
)
async def set_admin_account_connection_api_key(
    request: Request, api_key: ApiKeyBody, account_id: UUID, provider: str
) -> AdminConnectionOut:
    """Attach or replace a tenant's provider API key; the pair's one credential becomes it."""
    with successor_refusals_as_http():
        with store_reads():
            await _require_account(account_id)
        raw_api_key = normalize_api_key(api_key)
        plugin = request.app.state.providers.get(provider)
        if plugin is None:
            raise ProviderUnknown(provider)

        async def validate() -> None:
            await require_valid_api_key(request, plugin, provider, raw_api_key)

        mutation = await set_pair_api_key(
            request.app, str(account_id), provider, raw_api_key, validate=validate
        )
    await _drop_pending_flows(request, str(account_id), provider, mutation)
    assert mutation.credential is not None, "a committed PUT always has a credential"
    return _connection_out(mutation.credential)


@router.delete(
    "/accounts/{account_id}/connections/{provider}",
    status_code=204,
    operation_id="delete_admin_account_connection",
)
async def delete_admin_account_connection(
    request: Request, admin: SuccessorAdmin, account_id: UUID, provider: str
) -> Response:
    """Disconnect a tenant's provider; repeating it on a disconnected provider also answers 204."""
    del admin
    with successor_refusals_as_http():
        with store_reads():
            await _require_account(account_id)
        mutation = await delete_pair(request.app, str(account_id), provider)
    await _drop_pending_flows(request, str(account_id), provider, mutation)
    return Response(status_code=204)


_STANDARD_METHODS = ["CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"]


def _guard_mutation_path(path: str, allowed: str) -> None:
    """Authenticate and audit every other method and the trailing-slash form of a mutation path.

    # INVARIANT: as for LIST, no response of a successor path escapes authentication, the audit
    # line or `no-store` — Starlette's own 405 and slash redirect would bypass all three.
    """

    async def reject(admin: SuccessorAdmin, account_id: UUID, provider: str) -> None:
        del admin, account_id, provider
        raise HTTPException(status_code=405, headers={"Allow": allowed})

    async def redirect(
        request: Request, admin: SuccessorAdmin, account_id: UUID, provider: str
    ) -> None:
        del admin, account_id, provider
        location = str(request.url.replace(path=request.url.path.rstrip("/")))
        raise HTTPException(status_code=307, headers={"Location": location})

    others = [method for method in _STANDARD_METHODS if method != allowed]
    router.add_api_route(path, reject, methods=others, include_in_schema=False)
    router.add_api_route(path + "/", redirect, methods=_STANDARD_METHODS, include_in_schema=False)


_guard_mutation_path("/accounts/{account_id}/connections/{provider}/api-key", "PUT")
_guard_mutation_path("/accounts/{account_id}/connections/{provider}", "DELETE")

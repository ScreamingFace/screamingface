"""The ``/v1/admin`` surface — operator management of tenants and their provider API keys.

WHY this exists: `OME-684` made every caller who clears Cloudflare Access an ordinary `Account`,
but nothing provisions credentials for one. A new caller therefore authenticates successfully and
immediately gets `404 profile_not_found`. This is the operator-managed answer to that gap — an
allowlisted administrator attaches a static provider key so the tenant's first request finds a
profile.

Scope, deliberately: **API keys only.** aigateway's OAuth profile and connection endpoints are
untouched and not mirrored here. An OAuth profile reaches AUTHENTICATED only through an interactive
consent the tenant themselves must give, so an "admin creates it" flow would either be a lie or
would bind the admin's own provider identity to someone else's account.

Every route is guarded by :data:`CurrentAdmin`, which does NOT create an account — see
:mod:`aigateway.core.auth.admin`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import Response
from tortoise.expressions import Q

from ..core.admin_schemas import (
    AdminAccountList,
    AdminAccountOut,
    AdminProfileList,
    AdminProfileOut,
    CreateAdminAccountRequest,
    PatchAdminAccountRequest,
    PatchAdminProfileRequest,
    SetAdminApiKeyRequest,
)
from ..core.auth.admin import CurrentAdmin
from ..core.auth.cloudflare_identity import (
    HEADER_USER_EMAIL,
    CloudflareIdentity,
    account_for_identity,
)
from ..core.auth.models import Account
from ..core.profile_index import ProfileIndexStore
from .auth import upsert_api_key_profile
from .profile_routes import delete_profile_for_account

logger = logging.getLogger(__name__)


def _audit(request: Request, status_code: int) -> None:
    """Record every administrative attempt, successful or not.

    Mirrors `ProvisioningAuditRoute`. The 4xx/5xx paths matter as much as the success path: a run
    of 403s is what an attempt to reach this surface from outside the allowlist looks like, and it
    is invisible if only successes are logged.

    The actor is read from `request.state`, set by the dependency's caller — on a 401/403 there may
    be no actor yet, which is itself the useful signal.
    """
    actor = getattr(request.state, "admin_actor", None)
    logger.info(
        "admin_action actor=%s method=%s path=%s status_code=%d",
        actor if actor is not None else "<unidentified>",
        request.method,
        request.url.path,
        status_code,
    )


class AdminAuditRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def audited_handler(request: Request) -> Response:
            try:
                response = await original_handler(request)
            except HTTPException as exc:
                _audit(request, exc.status_code)
                raise
            except RequestValidationError:
                _audit(request, 422)
                raise
            except Exception:
                _audit(request, 500)
                raise
            _audit(request, response.status_code)
            return response

        return audited_handler


router = APIRouter(prefix="/v1/admin", tags=["Admin"], route_class=AdminAuditRoute)

ADMIN_SECURITY_SCHEME_NAME = "CloudflareUserEmail"

ADMIN_SECURITY_SCHEME = {
    "type": "apiKey",
    "in": "header",
    "name": HEADER_USER_EMAIL,
    "description": (
        "The address Cloudflare Access verified at the edge, re-injected by Envoy after it "
        "re-verifies the assertion against Cloudflare's JWKS. A client cannot set this: Envoy "
        "clears any inbound copy first. The gateway additionally refuses it from outside "
        "AIGW_ALLOWED_NETWORKS, and admits only addresses listed in AIGATEWAY_ADMIN_EMAILS."
    ),
}


def describe_admin_security(schema: dict[str, Any]) -> dict[str, Any]:
    """Declare the identity header on every admin operation in an OpenAPI document.

    WHY this is worth doing rather than leaving the surface undocumented: a TypeScript client is
    generated from this schema, and an operation with no declared security generates a call that
    silently omits the header — which fails at runtime as a 401 rather than at compile time. It
    also tells a reader of `/docs` what to send, which is otherwise guessable only from the source.
    """
    components = schema.setdefault("components", {})
    schemes = components.setdefault("securitySchemes", {})
    schemes[ADMIN_SECURITY_SCHEME_NAME] = ADMIN_SECURITY_SCHEME
    requirement = [{ADMIN_SECURITY_SCHEME_NAME: []}]
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/v1/admin"):
            continue
        for operation in operations.values():
            if isinstance(operation, dict):
                operation["security"] = requirement
    return schema


def _index_store(request: Request) -> ProfileIndexStore:
    return request.app.state.profile_index


def _note_actor(request: Request, admin: CurrentAdmin) -> None:
    """Name the actor for the audit line. Called first in every handler."""
    request.state.admin_actor = admin.username


async def _require_account(account_id: UUID) -> Account:
    account = await Account.get_or_none(id=account_id)
    if account is None:
        raise HTTPException(status_code=404, detail={"code": "account_not_found"})
    return account


# --- accounts ---------------------------------------------------------------------------------


@router.get("/accounts", response_model=AdminAccountList)
async def list_accounts(
    request: Request,
    admin: CurrentAdmin,
    q: str | None = Query(default=None, description="Substring match on address or display name"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminAccountList:
    _note_actor(request, admin)
    query = Account.all()
    if q:
        query = query.filter(Q(username__icontains=q) | Q(display_name__icontains=q))
    # Counted before slicing: the console pages on the total, not on the page length.
    total = await query.count()
    accounts = await query.order_by("username").offset(offset).limit(limit)
    return AdminAccountList(
        accounts=[AdminAccountOut.model_validate(a) for a in accounts], total=total
    )


@router.post("/accounts", status_code=201, response_model=AdminAccountOut)
async def create_account(
    request: Request,
    admin: CurrentAdmin,
    body: CreateAdminAccountRequest,
) -> AdminAccountOut:
    """Provision a tenant ahead of their first request.

    Delegates to `account_for_identity`, the SAME function `current_account` uses when a caller
    arrives unprovisioned. One code path means an admin-created account and an auto-created one are
    byte-identical, the address normalisation cannot drift between them, and the get-or-create race
    handling comes for free.

    Consequently this is idempotent: creating an account that exists returns it rather than 409.
    That is the honest contract — the account WILL exist the moment its owner sends a request, so
    there is no state in which "already exists" is an error the operator can act on.
    """
    _note_actor(request, admin)
    identity = CloudflareIdentity(email=str(body.email))
    account = await account_for_identity(identity)
    if account is None:
        # The address maps to an existing, deactivated account. Reactivating silently would undo a
        # deliberate lockout; the operator must say so explicitly via PATCH.
        raise HTTPException(
            status_code=409,
            detail={"code": "account_deactivated", "message": "Account exists but is deactivated."},
        )
    if body.display_name is not None and account.display_name != body.display_name:
        account.display_name = body.display_name
        await account.save(update_fields=["display_name"])
    return AdminAccountOut.model_validate(account)


@router.get("/accounts/{account_id}", response_model=AdminAccountOut)
async def get_account(request: Request, admin: CurrentAdmin, account_id: UUID) -> AdminAccountOut:
    _note_actor(request, admin)
    return AdminAccountOut.model_validate(await _require_account(account_id))


@router.patch("/accounts/{account_id}", response_model=AdminAccountOut)
async def patch_account(
    request: Request,
    admin: CurrentAdmin,
    account_id: UUID,
    body: PatchAdminAccountRequest,
) -> AdminAccountOut:
    """Rename or deactivate a tenant.

    There is no DELETE. `oauth_connections.account_id` cascades on delete, and the account's
    `credential_blobs` have no foreign key at all — so a real delete would take the connections
    with it and leave the encrypted blobs orphaned. Deactivation is the reversible equivalent:
    `account_for_identity` returns None for an inactive account, so the next request 401s.
    """
    _note_actor(request, admin)
    account = await _require_account(account_id)
    changed: list[str] = []
    if body.display_name is not None:
        account.display_name = body.display_name
        changed.append("display_name")
    if body.is_active is not None:
        account.is_active = body.is_active
        changed.append("is_active")
    if changed:
        await account.save(update_fields=changed)
    return AdminAccountOut.model_validate(account)


# --- profiles ---------------------------------------------------------------------------------


@router.get("/accounts/{account_id}/profiles", response_model=AdminProfileList)
async def list_account_profiles(
    request: Request, admin: CurrentAdmin, account_id: UUID
) -> AdminProfileList:
    """List one tenant's credential profiles.

    No new store code was needed: `ProfileIndexStore.list` has always taken the account as an
    argument — the tenant-facing route simply always passes the caller's own id. Cross-account
    access is a different argument, not a different store.
    """
    _note_actor(request, admin)
    await _require_account(account_id)
    profiles = await _index_store(request).list(str(account_id))
    return AdminProfileList(
        profiles=[AdminProfileOut.model_validate(p, from_attributes=True) for p in profiles]
    )


@router.patch("/accounts/{account_id}/profiles/{provider}/{name}", response_model=AdminProfileOut)
async def patch_account_profile(
    request: Request,
    admin: CurrentAdmin,
    account_id: UUID,
    provider: str,
    name: str,
    body: PatchAdminProfileRequest,
) -> AdminProfileOut:
    _note_actor(request, admin)
    await _require_account(account_id)
    idx = _index_store(request)
    profile = await idx.get(str(account_id), provider, name)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "profile_not_found", "provider": provider, "name": name},
        )
    updated = await idx.update_metadata(
        profile.id, defaults=body.defaults, account_label=body.account_label
    )
    return AdminProfileOut.model_validate(updated, from_attributes=True)


@router.put(
    "/accounts/{account_id}/profiles/{provider}/{name}/api-key",
    response_model=AdminProfileOut,
)
async def set_account_api_key(
    request: Request,
    admin: CurrentAdmin,
    account_id: UUID,
    provider: str,
    name: str,
    body: SetAdminApiKeyRequest,
) -> AdminProfileOut:
    """Attach or replace a tenant's provider API key. This is the point of the whole console.

    Delegates to `upsert_api_key_profile`, the SAME implementation the tenant-facing route uses.
    That function carries the OME-307 transaction-ordering invariants (index CAS first, credential
    write second, rollback as the sole atomicity mechanism); a second copy written for this path
    would be a second place for them to rot.

    The raw key is never echoed back — the response carries only the masked `account_label`.
    """
    _note_actor(request, admin)
    await _require_account(account_id)
    profile = await upsert_api_key_profile(
        request,
        provider=provider,
        name=name,
        account_id=str(account_id),
        raw_api_key=body.api_key,
        defaults=body.defaults,
    )
    return AdminProfileOut.model_validate(profile)


@router.delete("/accounts/{account_id}/profiles/{provider}/{name}", status_code=204)
async def delete_account_profile(
    request: Request,
    admin: CurrentAdmin,
    account_id: UUID,
    provider: str,
    name: str,
) -> None:
    """Remove a tenant's profile and its stored credential.

    Delegates to the same implementation as the tenant-facing delete, which publishes the index
    removal and the credential deletion in one transaction so a committed delete never leaves an
    orphaned blob.
    """
    _note_actor(request, admin)
    await _require_account(account_id)
    await delete_profile_for_account(
        request, provider=provider, name=name, account_id=str(account_id)
    )

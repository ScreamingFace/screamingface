"""Profile READ and credential-lifecycle endpoints.

The endpoints that list, describe, patch, delete, key and refresh a profile. The OAuth
FLOW endpoints (start, callback) and the api-key publication implementation they share
live in :mod:`aigateway.routes.auth`; this module is the HTTP surface around them.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr
from tortoise.transactions import in_transaction

from ..core.auth.middleware import CurrentAccount
from ..core.credential_ownership_fence import (
    BufferedRefreshCredentialStore,
    ExpectedOwnership,
)
from ..core.profile_index import (
    ProfileTransitionConflict,
)
from ..core.profile_models import (
    ProfileDefaults,
)
from ._auth_context import (
    _credential_store_for_app,
    _index_store,
    _registry,
)
from .auth import _credential_strategy_for_app, upsert_api_key_profile
from .profile_credential_lifecycle import (
    _invalidate_profile_session,
    _profile_refresh_lifecycle,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/auth/profiles")
async def list_profiles(request: Request, current: CurrentAccount) -> dict:
    profiles = await _index_store(request).list(str(current.id))
    return {"profiles": [p.model_dump(mode="json") for p in profiles]}


@router.get("/v1/auth/{provider}/profiles")
async def list_provider_profiles(provider: str, request: Request, current: CurrentAccount) -> dict:
    profiles = await _index_store(request).list(str(current.id), provider)
    return {"profiles": [p.model_dump(mode="json") for p in profiles]}


@router.get("/v1/auth/{provider}/profiles/{name}")
async def get_profile(provider: str, name: str, request: Request, current: CurrentAccount) -> dict:
    p = await _index_store(request).get(str(current.id), provider, name)
    if p is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "profile_not_found", "provider": provider, "name": name},
        )
    return p.model_dump(mode="json")


@router.get("/v1/auth/{provider}/profiles/{name}/status")
async def profile_status(
    provider: str, name: str, request: Request, current: CurrentAccount
) -> dict:
    p = await _index_store(request).get(str(current.id), provider, name)
    if p is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "profile_not_found", "provider": provider, "name": name},
        )
    return {
        "state": p.state.value,
        "auth_type": p.auth_type,
        "account_label": p.account_label,
        "last_refreshed_at": p.last_refreshed_at.isoformat() if p.last_refreshed_at else None,
    }


class PatchProfileRequest(BaseModel):
    defaults: ProfileDefaults | None = None
    account_label: str | None = None


@router.patch("/v1/auth/{provider}/profiles/{name}")
async def patch_profile(
    provider: str,
    name: str,
    body: PatchProfileRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    idx = _index_store(request)
    p = await idx.get(str(current.id), provider, name)
    if p is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    try:
        p = await idx.update_metadata(
            p.id,
            defaults=body.defaults,
            account_label=body.account_label,
        )
    except ProfileTransitionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "profile_conflict", "provider": provider, "profile": name},
        ) from exc
    return p.model_dump(mode="json")


class SetApiKeyRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr
    defaults: ProfileDefaults | None = None


@router.put("/v1/auth/{provider}/profiles/{name}/api-key")
async def set_profile_api_key(
    provider: str,
    name: str,
    body: SetApiKeyRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    """Create or update the CALLER's own API-key profile.

    A thin wrapper over :func:`upsert_api_key_profile`; the tenant-facing contract is simply
    "whatever that does, to my own account".
    """
    return await upsert_api_key_profile(
        request,
        provider=provider,
        name=name,
        account_id=str(current.id),
        raw_api_key=body.api_key,
        defaults=body.defaults,
    )


@router.delete("/v1/auth/{provider}/profiles/{name}", status_code=204)
async def delete_profile(provider: str, name: str, request: Request, current: CurrentAccount):
    """Delete the CALLER's own profile. Thin wrapper over the shared implementation."""
    await delete_profile_for_account(
        request, provider=provider, name=name, account_id=str(current.id)
    )


async def delete_profile_for_account(
    request: Request, *, provider: str, name: str, account_id: str
) -> None:
    """Remove one profile and its credential.

    WHY `account_id` is a parameter: the admin console deletes on a tenant's behalf (`OME-706`).
    The transaction-ordering invariants below are the reason both paths must share this rather
    than each writing their own delete.
    """
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_provider"})
    idx = _index_store(request)
    p = await idx.get(account_id, provider, name)
    if p is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    strategy = _credential_strategy_for_app(
        request.app, plugin, provider, account_id, name, auth_type=p.auth_type
    )
    # INVARIANT (OME-307 Unit 3 + Blocker 3): publish the profile-index removal and the
    # credential deletion in ONE transaction so a committed delete never leaves an orphan
    # credential (a blob with no profile). The index-row CAS runs FIRST: it is the sole
    # ALWAYS-PRESENT row, so it is the only row that serializes a concurrent api-key set. The
    # credential row may be ABSENT (e.g. a pending/errored OAuth profile), and a missing-row
    # DELETE takes NO lock under READ COMMITTED — so serializing on it would let a racing set
    # slip an INSERT past this delete and orphan a credential. Rollback keeps blob + index
    # coherent on any failure.
    async with in_transaction():
        await idx.remove(p.id)
        if strategy is not None:
            await strategy.delete_credentials()
    # Cache invalidation follows the durable boundary so it reflects the committed delete.
    _invalidate_profile_session(request.app, plugin, account_id, name)


@router.post("/v1/auth/{provider}/profiles/{name}/refresh")
async def refresh_profile(
    provider: str, name: str, request: Request, current: CurrentAccount
) -> dict:
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_provider"})
    account_id = str(current.id)
    # INVARIANT (OME-1026 adversarial B2): capture the ownership generation in the SAME read
    # that resolves the profile, BEFORE any provider call. This is the value the publication
    # is conditional on, so reading it later — or re-reading it after the refresh — would
    # fence against whatever the replacement had already committed.
    found = await _index_store(request).get_with_credential_generation(account_id, provider, name)
    if found is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    p, credential_generation = found
    expected = ExpectedOwnership(
        profile_id=p.id,
        account_id=account_id,
        provider=provider,
        profile_name=name,
        auth_type=p.auth_type,
        credential_generation=credential_generation,
    )
    fence = BufferedRefreshCredentialStore(_credential_store_for_app(request.app))
    strategy = _credential_strategy_for_app(
        request.app,
        plugin,
        provider,
        account_id,
        name,
        auth_type=p.auth_type,
        credential_store=fence,
    )
    if strategy is None:
        raise HTTPException(status_code=400, detail={"code": "provider_does_not_use_oauth"})

    async with _profile_refresh_lifecycle(
        request, plugin, p, provider, account_id, name, expected=expected, fence=fence
    ):
        await strategy.refresh_credentials()
    return p.model_dump(mode="json")

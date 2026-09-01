"""OME-1026 — the profile credential lifecycle around a provider refresh.

FEATURE: profile-scoped live model discovery, wired to the credential lifecycle. A
credential publication retires the previous owner's private catalog and warms the new
one; a refresh keeps a catalog that is still exactly correct.

This module owns what happens AROUND a credential change: which in-memory state is
dropped, which private listing is retired or kept, when discovery starts, and the
ownership fence that decides whether a finished refresh may publish at all. The routes
that call it own the HTTP contract; the stores it fences own durability.

INVARIANT (adversarial B2): presence is not ownership. The refresh publication is one
transaction holding two conditional writes — the profile-index CAS (presence, expected
generation, expected auth type) and the buffered credential CAS (bytes unchanged since
before the provider call). Either refusal rolls back both, so a replacement published
while a refresh was in flight wins in BOTH durable stores.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from tortoise.transactions import in_transaction

from ..core.credential_ownership_fence import (
    BufferedRefreshCredentialStore,
    CredentialOwnerChanged,
    ExpectedOwnership,
)
from ..core.credential_strategy_cache import credential_strategy_cache
from ..core.errors import AuthError, CredentialNotFoundError
from ..core.profile_index import (
    CredentialOwnershipConflict,
    ProfileTransitionConflict,
)
from ..core.profile_models import (
    Profile,
    ProfileState,
    credential_name_for,
)
from .auth_context import _index_store
from .profile_models import auth_provider_for as profile_models_auth_provider

logger = logging.getLogger(__name__)
router = APIRouter()


def _invalidate_profile_session(
    app, plugin, account_id: str, name: str, *, retire_private_catalog: bool = True
) -> None:
    """Drop this profile's cached in-memory credential state.

    ``retire_private_catalog=False`` keeps the profile's PRIVATE model listing — for a
    boundary that rotates the same owner's token rather than replacing the owner
    (OME-1026 F3). It defaults to retiring, so a new lifecycle boundary that forgets to
    think about it releases memory it might not have needed to rather than holding a
    catalog it should have dropped.
    """
    credential_name = credential_name_for(account_id, name)
    invalidator = getattr(plugin, "invalidate_profile_session", None)
    if callable(invalidator):
        invalidator(credential_name)
    # Drop the shared cached strategy so re-auth / api-key change / delete / refresh
    # never serve a stale in-memory token from a prior credential (SF-282).
    credential_strategy_cache(app).evict(credential_name)
    # OME-1026: retire this profile's PRIVATE model listing too — drop its snapshots
    # and supersede any in-flight refresh. Every caller of this function is already a
    # post-commit credential-lifecycle boundary (api-key publication, delete, OAuth
    # completion, manual refresh), which is exactly when a credential-derived catalog
    # stops describing its owner.
    # INVARIANT (why forgetting a call site cannot leak): the private cache identity
    # carries the credential generation, so a snapshot from the previous generation is
    # unreadable under the new one even with no invalidation at all. This call makes
    # the memory release prompt and stops a doomed upstream request; it is not the
    # thing that makes the isolation correct.
    catalog = getattr(app.state, "profile_model_catalog", None)
    if catalog is not None and retire_private_catalog:
        catalog.invalidate(
            account_id=account_id, provider=plugin.custom_llm_provider, profile_name=name
        )


async def _trigger_profile_discovery(request: Request, plugin, account_id: str, profile: Profile):
    """Start this profile's private model discovery WITHOUT waiting for it (OME-1026).

    Called post-commit, after ``_invalidate_profile_session`` has retired the previous
    generation — so the refresh this starts belongs to the credential that was just
    published.

    # WHY a zero wait rather than a fire-and-forget task of our own: reusing
    # ``snapshot_for`` keeps ONE implementation of the refusal gates, the cache
    # identity, the single-flight dedup and the capacity limit. A budget of zero means
    # the work starts and this request does not wait on it — ``asyncio.wait`` never
    # cancels what it waits on, so the refresh runs to completion in the background.
    # INVARIANT: publishing a credential must not inherit the upstream catalog's
    # latency or its failures, so the outcome is deliberately ignored here.
    """
    catalog = getattr(request.app.state, "profile_model_catalog", None)
    runtime = request.app.state.discovery_runtime
    if catalog is None or runtime is None:
        return
    # INVARIANT (OME-1026 F3): read the generation back from the COMMITTED index rather
    # than assuming it. The refresh this starts must be filed under the generation the
    # transaction actually published, not one this request guessed before committing.
    found = await _index_store(request).get_with_credential_generation(
        account_id, plugin.custom_llm_provider, profile.name
    )
    if found is None:
        # A concurrent delete won the race. Nothing to discover for.
        return
    committed, credential_generation = found
    await catalog.snapshot_for(
        plugin,
        account_id=account_id,
        profile=committed,
        client=runtime.client,
        limits=runtime.limits,
        auth_provider=profile_models_auth_provider(request.app, plugin, account_id, committed),
        credential_generation=credential_generation,
        wait_budget_s=0.0,
    )


@asynccontextmanager
async def _profile_refresh_lifecycle(
    request: Request,
    plugin,
    profile: Profile,
    provider: str,
    account_id: str,
    name: str,
    *,
    expected: ExpectedOwnership,
    fence: BufferedRefreshCredentialStore,
) -> AsyncIterator[None]:
    """Shared profile state updates around provider-owned credential refresh."""
    # INVARIANT (OME-307 H-1): a manual refresh reads the profile, runs the provider network call,
    # then publishes the result. A delete that commits during that network window must WIN — a
    # deleted profile is never resurrected. The success branch publishes only while the profile
    # remains PRESENT (require_present); the error branch additionally fences on the snapshot below
    # (auth_type + last_refreshed_at) so a deleted/superseded profile is not recreated as a ghost
    # ERROR row.
    # INVARIANT (OME-1026 adversarial B2): presence is NOT ownership. ``require_present`` is
    # satisfied by a profile a DIFFERENT owner now holds, which is how a stale refresh restored
    # the previous owner over a committed replacement. The success branch below therefore
    # publishes the profile row and the buffered credential in ONE transaction, each conditional:
    # the index CAS on presence + ``expected`` generation + ``expected`` auth type, the credential
    # CAS on the bytes read before the provider call. Nothing was persisted during the refresh, so
    # a refusal — or a cancellation — leaves both durable stores exactly as the new owner left them.
    expected_auth_type = profile.auth_type
    expected_last_refreshed_at = profile.last_refreshed_at
    try:
        yield
    except (CredentialNotFoundError, AuthError) as exc:
        # Error branch: fence on ownership and swallow a lost race (mirrors
        # chat_credentials._mark_profile_error_fresh) so a profile deleted or superseded during the
        # network window is never recreated as a ghost ERROR row.
        try:
            await _index_store(request).mark_authenticated_error(
                profile.id,
                expected_auth_type=expected_auth_type,
                expected_last_refreshed_at=expected_last_refreshed_at,
            )
        except ProfileTransitionConflict:
            pass
        _invalidate_profile_session(request.app, plugin, account_id, name)
        raise HTTPException(
            status_code=401,
            detail={
                "code": "auth_required",
                "message": str(exc),
                "reauth_url": f"/v1/auth/{provider}/profiles/{name}",
            },
        ) from exc
    else:
        # Success branch: publish only while the profile still exists (require_present). A profile
        # deleted during the network window makes this raise -> 409 instead of resurrecting it as
        # an AUTHENTICATED row.
        profile.state = ProfileState.AUTHENTICATED
        profile.last_refreshed_at = datetime.now(UTC)
        try:
            # ONE transaction, and the OME-307 lock order is unchanged: the index row (the
            # sole always-present row, so the only cross-worker serializer) first, the
            # credential row second. Reversing them to fence the credential write in place
            # would deadlock against the api-key and delete paths, which take them this way.
            async with in_transaction():
                # INVARIANT (OME-1026 F3): a refresh rotates the SAME owner's token, so it is
                # not a credential-generation event. Bumping here would (a) discard a private
                # model catalog that is still exactly correct — an api-key "refresh" only
                # re-reads the stored key, so the credential is byte-identical afterwards —
                # and (b) require this bump to be atomic with a credential write the provider
                # strategy already committed above, which it cannot be. Ownership changes
                # (key replacement, re-authentication, auth-type switch) bump at their own
                # publication sites, inside the transaction that writes the credential.
                await _index_store(request).upsert(
                    profile,
                    require_present=True,
                    credential_owner_unchanged=True,
                    expected_credential_generation=expected.credential_generation,
                    expected_auth_type=expected.auth_type,
                )
                await fence.publish()
        except (CredentialOwnershipConflict, CredentialOwnerChanged) as exc:
            # The owner changed under us. Report it as its own code so an operator can tell
            # "someone replaced this credential" from "someone deleted this profile", and
            # KEEP the new owner's private listing: it is not ours to retire.
            _invalidate_profile_session(
                request.app, plugin, account_id, name, retire_private_catalog=False
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "credential_owner_changed",
                    "provider": provider,
                    "profile": name,
                },
            ) from exc
        except ProfileTransitionConflict as exc:
            _invalidate_profile_session(
                request.app, plugin, account_id, name, retire_private_catalog=False
            )
            raise HTTPException(
                status_code=409,
                detail={"code": "profile_conflict", "provider": provider, "profile": name},
            ) from exc
        # INVARIANT (OME-1026 F3): the cached STRATEGY must go — it may hold the token
        # this refresh just replaced (SF-282) — but the private model catalog must NOT.
        # A refresh keeps the same authenticated owner, so its snapshot still describes
        # exactly the right entitlements; retiring it here forced a fresh upstream dial
        # with a byte-identical credential on every refresh.
        _invalidate_profile_session(
            request.app, plugin, account_id, name, retire_private_catalog=False
        )

"""Completing a profile OAuth flow: the pending-state fence and its publication.

This module owns the steps between "a provider handed us a code" and "the profile is
AUTHENTICATED": validating the pending entry that owns the flow, exchanging the code,
publishing the profile under its OAuth generation, and marking the failure paths. The
coordinator that sequences them lives with the routes in :mod:`aigateway.routes.auth`.

INVARIANT: every publication here is fenced on the OAuth generation claimed when the
flow began, so a superseded flow loses even while the profile is still PENDING.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from ..core.oauth.store import (
    credential_key_for,
)
from ..core.pending_auth import PendingAuthEntry
from ..core.plugin_base import (
    OAuthCodeExchangeRequest,
)
from ..core.profile_index import (
    ProfileTransitionConflict,
)
from ..core.profile_models import (
    ProfileState,
    credential_name_for,
)
from ._auth_context import _index_store_for_app
from .oauth_connection_completion import _mark_connection_error
from .oauth_loopback import _close_loopback_callback

logger = logging.getLogger(__name__)
router = APIRouter()


def _pending_or_unknown(pending: PendingAuthEntry | None) -> PendingAuthEntry:
    if pending is not None:
        return pending
    raise HTTPException(
        status_code=400,
        detail={"code": "unknown_state", "message": "OAuth state not recognized or expired"},
    )


def _validate_pending_oauth(
    pending: PendingAuthEntry,
    provider: str,
    current_account_id: str | None,
) -> None:
    if pending.provider != provider:
        raise HTTPException(status_code=400, detail={"code": "provider_mismatch"})
    if current_account_id is not None and current_account_id != pending.account_id:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})


async def _exchange_oauth_code_for_pending(
    app,
    plugin,
    provider: str,
    code: str,
    state: str,
    pending: PendingAuthEntry,
) -> dict:
    return await plugin.exchange_oauth_code(
        OAuthCodeExchangeRequest(
            code=code,
            code_verifier=pending.code_verifier,
            redirect_uri=pending.redirect_uri,
            state=state,
            http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
        )
    )


async def _mark_oauth_completion_error(
    app,
    pending: PendingAuthEntry,
    connection_message: str,
    state: str,
) -> None:
    # INVARIANT (OME-307 Blocker 2): only a PROFILE flow that claimed an ownership generation
    # can own a pending profile. Mark its error CONDITIONALLY on that generation so a stale
    # failure cannot clobber a newer owner, overwrite a committed API-key profile, or resurrect
    # a deleted profile. Connection flows are handled separately by _mark_connection_error.
    if pending.connection_id is None and pending.oauth_generation is not None:
        await _mark_profile_error(app, pending.profile_id, pending.oauth_generation)
    await _mark_connection_error(app, pending, connection_message)
    await _close_loopback_callback(app, state)


async def _mark_profile_authenticated(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
    *,
    require_pending: bool = False,
) -> None:
    index = _index_store_for_app(app)
    profile = await index.get(
        pending.account_id,
        pending.provider,
        pending.profile_name,
    )
    if profile is None:
        if require_pending:
            raise ProfileTransitionConflict("profile no longer exists")
        return
    if require_pending and profile.state is not ProfileState.PENDING:
        raise ProfileTransitionConflict("profile is no longer pending")
    profile.state = ProfileState.AUTHENTICATED
    # A completed OAuth round-trip overwrites the credential slot, so the
    # discriminator must flip back even if the profile was api_key before.
    profile.auth_type = "oauth"
    profile.last_refreshed_at = datetime.now(UTC)
    label = plugin.account_label_from_credentials(creds)
    if label is not None:
        profile.account_label = label
    if require_pending:
        # INVARIANT (OME-307 Blocker 1): bind publication to THIS OAuth operation by presenting
        # the ownership generation this flow claimed at begin_pending. Ownership is decided
        # INSIDE authenticate_pending's atomic durable CAS — a superseded flow loses even though
        # the row is still PENDING — closing the check-then-act TOCTOU that a separate in-memory
        # precheck left open. The state==PENDING guard inside the CAS remains defense in depth
        # for a newer flow (or API-key write) that has already committed a non-pending state.
        await index.authenticate_pending(
            profile,
            expected_generation=pending.oauth_generation,
            account_label=label,
        )
    else:
        await index.upsert(profile)


def _credential_name_for_pending(pending: PendingAuthEntry) -> str:
    if pending.connection_id is not None:
        return credential_key_for(pending.account_id, pending.connection_id)
    return credential_name_for(pending.account_id, pending.profile_name)


async def _mark_profile_error(app, profile_id: str, expected_generation: int) -> None:
    # INVARIANT (OME-307 Blocker 2): a stale OAuth failure marks ERROR only while it still owns
    # the pending profile (same generation, still present, still PENDING). If ownership moved
    # on — newer flow, committed api_key, or delete — mark_pending_error raises and we do
    # nothing rather than corrupt the newer state or recreate a deleted profile.
    try:
        await _index_store_for_app(app).mark_pending_error(
            profile_id, expected_generation=expected_generation
        )
    except ProfileTransitionConflict:
        pass

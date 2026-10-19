"""Open a Profile-era OAuth flow without the retired start route (OME-1209 Stage E, E3).

# FEATURE: Stage E route retirement — `POST /v1/auth/{provider}/profiles` answers 410 since E3,
# but the callback branches it fed (legacy pending, migrated-pair facade) ship until E4 and still
# complete flows that were in flight at deploy. Their tests open the flow here instead.
# INVARIANT: this reproduces exactly the storage effects of the retired `start_oauth`, in its
# order — the pair observed, `begin_connection_oauth` for a migrated pair or an in-place
# `begin_pending` for every other pair, the pending entry, then the older flows of the same name
# superseded. No HTTP, no PKCE, no loopback listener: the callback reads only the pending entry.
# WHY in-place for the legacy document: an api_key Profile keeps its auth_type, label and
# defaults until the flow COMPLETES (SF-244 audit F08), exactly as the retired route left it.
"""

from __future__ import annotations

import secrets
from typing import Any

from aigateway.core.credential_names import profile_id_for
from aigateway.core.pending_auth import PendingAuthEntry
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.core.provider_access import PairAuthorityStore, begin_connection_oauth

DEFAULT_REDIRECT_URI = "http://localhost:1455/callback"


async def open_oauth_flow(
    app: Any,
    *,
    account_id: str,
    provider: str,
    name: str = "default",
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    code_verifier: str = "test-verifier",
    state: str | None = None,
) -> str:
    """Publish one OAuth flow the way the retired start route did; returns its `state`."""
    plugin = app.state.providers.get(provider)
    cfg = plugin.oauth_config()
    profile_id = profile_id_for(account_id, provider, name)
    state = state or secrets.token_urlsafe(16)

    observed = await PairAuthorityStore().read(account_id, provider)
    flow = await begin_connection_oauth(
        app,
        plugin,
        account_id=account_id,
        provider=provider,
        name=name,
        scopes=cfg.scopes,
        observed_pair=observed,
    )
    generation = None
    if flow is None:
        index: ProfileIndexStore = app.state.profile_index
        profile = await index.get(account_id, provider, name) or Profile(
            id=profile_id, account_id=account_id, provider=provider, name=name
        )
        profile.scopes = list(cfg.scopes)
        profile.state = ProfileState.PENDING
        generation = await index.begin_pending(profile)

    pending = app.state.pending_auth
    pending.put(
        state,
        PendingAuthEntry(
            account_id=account_id,
            provider=provider,
            profile_name=name,
            profile_id=profile_id,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            oauth_generation=generation,
            pair_generation=None if flow is None else flow.generation,
            observed_pair=observed if flow is None else None,
        ),
    )
    pending.pop_for_profile(account_id, provider, name, exclude_state=state)
    return state

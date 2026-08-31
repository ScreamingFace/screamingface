from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr
from tortoise.transactions import in_transaction

from ..core.auth.middleware import CurrentAccount
from ..core.oauth_pkce import generate_pkce, generate_state
from ..core.pending_auth import PendingAuthEntry
from ..core.plugin_base import credential_strategy_from
from ..core.profile_index import (
    ProfileTransitionConflict,
)
from ..core.profile_models import (
    AuthType,
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from ._auth_context import (
    _credential_store_for_app,
    _index_store,
    _pending,
    _pending_for_app,
    _registry,
    _registry_for_app,
)
from .api_key_validation import normalize_api_key, require_valid_api_key
from .credential_persistence import (
    SupportsCredentialSlot,
    persist_credentials_or_503,
)

# The public-to-the-suite surface of this module. These helpers now live in the
# cohesive modules above, but `tests/unit/test_auth_routes.py` imports them from here
# and prior tests are append-only, so the names stay reachable at this path.
# WHY the redundant `as` alias: it is the PEP 484 marker for a deliberate re-export, so
# the linter keeps a name this module does not itself call.
from .oauth_connection_completion import OAuthConnectionStore as OAuthConnectionStore
from .oauth_connection_completion import _connection_label as _connection_label
from .oauth_connection_completion import (
    _record_oauth_connection_completion,
)
from .oauth_loopback import (
    _close_loopback_callback,
    _redirect_uri_for,
)
from .oauth_loopback import _expire_loopback_callback as _expire_loopback_callback
from .oauth_loopback import _handle_loopback_callback as _handle_loopback_callback
from .oauth_loopback import _http_response as _http_response
from .oauth_loopback import _loopback_host_allowed as _loopback_host_allowed
from .oauth_loopback import close_loopback_callbacks as close_loopback_callbacks
from .oauth_profile_completion import (
    _credential_name_for_pending,
    _exchange_oauth_code_for_pending,
    _mark_oauth_completion_error,
    _mark_profile_authenticated,
    _pending_or_unknown,
    _validate_pending_oauth,
)
from .profile_credential_lifecycle import (
    _invalidate_profile_session,
    _trigger_profile_discovery,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# INVARIANT (why the strategy builders live in THIS module): the merged suite
# substitutes a no-op strategy by patching `aigateway.routes.auth.credential_strategy_from`
# (`tests/integration/test_lifecycle_postgres_races.py`), which only takes effect if the
# builder resolves that name from this module's globals. Moving the builders elsewhere
# would leave that patch pointing at nothing and put a Postgres race test back on the
# network.
def _credential_strategy_for_app(
    app,
    plugin,
    provider: str,
    account_id: str,
    name: str,
    auth_type: AuthType = "oauth",
    *,
    credential_store=None,
):
    return _credential_strategy_for_credential_name(
        app,
        plugin,
        provider,
        credential_name_for(account_id, name),
        auth_type=auth_type,
        credential_store=credential_store,
    )


def _credential_strategy_for_credential_name(
    app,
    plugin,
    provider: str,
    credential_name: str,
    auth_type: AuthType = "oauth",
    *,
    credential_store=None,
):
    """``credential_store`` overrides the app's store for ONE call.

    # WHY the override exists (OME-1026 adversarial B2): the refresh path wraps the store
    # in an ownership fence, and strategies are built fresh per call, so the wrapper
    # reaches exactly the refresh it was built for and no other caller.
    """
    return credential_strategy_from(
        plugin,
        credential_name,
        auth_type=auth_type,
        credential_store=(
            credential_store if credential_store is not None else _credential_store_for_app(app)
        ),
        http_client_factory=getattr(app.state, f"{provider}_http_factory", None),
    )


class StartAuthRequest(BaseModel):
    name: str
    defaults: ProfileDefaults | None = None
    redirect_uri: str | None = None


@router.post("/v1/auth/{provider}/profiles", status_code=201)
async def start_oauth(
    provider: str,
    body: StartAuthRequest,
    request: Request,
    current: CurrentAccount,
) -> dict:
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": provider}
        )

    cfg = plugin.oauth_config()
    if cfg is None:
        raise HTTPException(status_code=400, detail={"code": "provider_does_not_use_oauth"})

    account_id = str(current.id)
    profile_id = profile_id_for(account_id, provider, body.name)
    code_verifier, code_challenge = generate_pkce()
    state = generate_state()

    # Bind the redirect (for loopback, a listener keyed by ``state``) BEFORE superseding any
    # older flow for this profile: a redirect-setup failure must leave the previous flow
    # untouched rather than destroy it for a flow that never started (OME-307 Blocker 5).
    redirect_uri: str | None = None
    if body.redirect_uri is not None:
        redirect_uri = await _redirect_uri_for(request, provider, cfg, state, body.redirect_uri)
    if redirect_uri is None:
        redirect_uri = await _redirect_uri_for(request, provider, cfg, state)

    # Update the existing profile in place instead of replacing it wholesale:
    # an api_key profile keeps its auth_type/account_label/defaults until the
    # OAuth flow actually COMPLETES (completion flips auth_type to "oauth" in
    # _mark_profile_authenticated). A wholesale reset at flow start would
    # desync the index from the still-stored API-key blob (SF-244 audit F08).
    profile = await _index_store(request).get(account_id, provider, body.name)
    if profile is None:
        profile = Profile(
            id=profile_id,
            account_id=account_id,
            provider=provider,
            name=body.name,
        )
    profile.scopes = list(cfg.scopes)
    profile.state = ProfileState.PENDING
    if body.defaults is not None:
        profile.defaults = body.defaults

    # INVARIANT (OME-307 Blockers 1 & 5): durably publish THIS flow — its pending profile and a
    # fresh ownership generation — in one atomic index CAS BEFORE irreversibly superseding any
    # older flow. On failure, tear down only this flow's own loopback listener and re-raise; the
    # older flow stays completable and no invisible pending flow is stranded. begin_pending is
    # what assigns the ownership generation the callback later presents to authenticate_pending.
    try:
        generation = await _index_store(request).begin_pending(profile)
    except Exception:
        await _close_loopback_callback(request.app, state)
        raise

    _pending(request).put(
        state,
        PendingAuthEntry(
            account_id=account_id,
            provider=provider,
            profile_name=body.name,
            profile_id=profile_id,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            oauth_generation=generation,
        ),
    )

    # Only now that this flow is fully published: supersede older flows for the same profile,
    # excluding this flow's own freshly-published state (Blocker 5).
    for stale_state in _pending(request).pop_for_profile(
        account_id, provider, body.name, exclude_state=state
    ):
        await _close_loopback_callback(request.app, stale_state)

    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(cfg.scopes),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if cfg.extra_authorize_params:
        params.update(cfg.extra_authorize_params)
    authorize_url = f"{cfg.authorize_url}?{urlencode(params)}"

    return {
        "profile_id": profile_id,
        "authorize_url": authorize_url,
        "state": state,
        "expires_in": 600,
    }


async def _complete_oauth_for_app(
    app,
    provider: str,
    code: str,
    state: str,
    current_account_id: str | None = None,
) -> None:
    """Run the OAuth token exchange and persist credentials.

    Used by both the GET browser-redirect callback and the POST manual
    paste-code endpoint. Raises HTTPException on failure.
    """
    pending_table = _pending_for_app(app)
    pending = _pending_or_unknown(pending_table.peek(state))
    _validate_pending_oauth(pending, provider, current_account_id)
    plugin = _registry_for_app(app).get(provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": provider}
        )

    credential_name = _credential_name_for_pending(pending)
    strategy = _credential_strategy_for_credential_name(app, plugin, provider, credential_name)
    if strategy is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "provider_does_not_use_oauth", "provider": provider},
        )

    # Consume the OAuth state after all synchronous validation and before the
    # first await that can race another callback using the same code.
    pending = _pending_or_unknown(pending_table.pop(state))
    try:
        try:
            creds = await _exchange_oauth_code_for_pending(
                app, plugin, provider, code, state, pending
            )
        except NotImplementedError as exc:
            await _mark_oauth_completion_error(app, pending, "provider_does_not_use_oauth", state)
            raise HTTPException(
                status_code=400,
                detail={"code": "provider_does_not_use_oauth", "provider": provider},
            ) from exc
        except Exception:
            await _mark_oauth_completion_error(app, pending, "OAuth code exchange failed", state)
            raise
        if pending.connection_id is None:
            slot = cast(SupportsCredentialSlot, strategy)
            try:
                # WHY: token exchange stays outside the transaction; only profile + credential
                # publication is atomic. The always-present account index row is mutated first,
                # matching API-key set/delete's lock order; the optional credential row follows.
                # The generation CAS rejects stale callbacks before they can write credentials.
                async with in_transaction():
                    await _mark_profile_authenticated(
                        app,
                        pending,
                        plugin,
                        creds,
                        require_pending=True,
                    )
                    await persist_credentials_or_503(
                        slot,
                        creds,
                        description="OAuth profile credentials",
                    )
            except ProfileTransitionConflict as exc:
                await _close_loopback_callback(app, state)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "profile_auth_conflict",
                        "provider": pending.provider,
                        "profile": pending.profile_name,
                    },
                ) from exc
            except HTTPException:
                await _mark_oauth_completion_error(
                    app, pending, "credential_store_unavailable", state
                )
                raise
            _invalidate_profile_session(app, plugin, pending.account_id, pending.profile_name)
        else:
            await _mark_profile_authenticated(app, pending, plugin, creds)
        await _record_oauth_connection_completion(app, pending, plugin, creds)
        await _close_loopback_callback(app, state)
    except asyncio.CancelledError:
        # INVARIANT (OME-307 Blocker 5): a callback cancellation must never strand the profile
        # pending. We consumed the state before the first await above; on cancellation the
        # enclosing transaction (if any) rolls back, and we re-publish the consumed state
        # SYNCHRONOUSLY so the flow stays completable via retry. Python 3.12
        # ``asyncio.CancelledError`` is a ``BaseException`` that escapes the ``except Exception``
        # handlers above; ``put`` is synchronous so it finishes even while the task unwinds.
        # AIDEV-NOTE: cleanup-then-re-raise — the cancellation is NEVER caught-and-suppressed.
        pending_table.put(state, pending)
        raise


async def upsert_api_key_profile(
    request: Request,
    *,
    provider: str,
    name: str,
    account_id: str,
    raw_api_key: SecretStr,
    defaults: ProfileDefaults | None,
) -> dict:
    """Create or update a profile that authenticates with a raw API key.

    No OAuth round-trip: the profile is AUTHENTICATED as soon as the key is
    stored. The key is persisted to the profile's credential blob slot (so a
    later OAuth completion overwrites it, and delete removes it). The RAW key is
    never returned in responses or logs; the profile carries only a masked
    display label of the last 4 characters (``account_label = "API key ····WXYZ"``),
    the same last-4 convention used by Stripe/AWS/GitHub.

    WHY `account_id` is a parameter rather than read from the caller: the admin console writes
    keys on a tenant's behalf (`OME-706`). Both routes MUST share this implementation — it carries
    the OME-307 transaction-ordering invariants below, and a second copy of them written for the
    admin path would be a second place for them to rot.
    """
    plugin = _registry(request).get(provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": provider}
        )
    api_key = normalize_api_key(raw_api_key)
    strategy = _credential_strategy_for_app(
        request.app, plugin, provider, account_id, name, auth_type="api_key"
    )
    if strategy is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "api_key_not_supported", "provider": provider},
        )

    await require_valid_api_key(request, plugin, provider, api_key)

    idx = _index_store(request)
    profile = await idx.get(account_id, provider, name)
    # INVARIANT (OME-307 Unit 3): if we observed an existing profile, publication must not
    # resurrect it should a concurrent delete remove it before we commit (delete wins).
    profile_observed = profile is not None
    if profile is None:
        profile = Profile(
            id=profile_id_for(account_id, provider, name),
            account_id=account_id,
            provider=provider,
            name=name,
        )
    if defaults is not None:
        profile.defaults = defaults
    profile.auth_type = "api_key"
    profile.state = ProfileState.AUTHENTICATED
    profile.last_refreshed_at = datetime.now(UTC)
    profile.account_label = f"API key ····{api_key[-4:]}"
    profile.scopes = []  # OAuth scopes are meaningless for API-key auth (F24)

    strategy_for_slot = cast(SupportsCredentialSlot, strategy)
    # WHY: the credential blob and profile index share the Tortoise connection; publish both
    # in one short transaction so readers never observe a committed mixed auth type.
    # INVARIANT (OME-307 Blocker 3): the index-row CAS runs FIRST, the credential write SECOND —
    # ONE consistent lock order shared with delete_profile. The account index row is the sole
    # ALWAYS-PRESENT row, so it is the only row that serializes a concurrent delete; the
    # credential row may be absent, and a missing-row operation takes no lock under READ
    # COMMITTED. Publishing the index first means a racing delete that removed the profile makes
    # require_present raise BEFORE any credential is written, so nothing is orphaned or resurrected.
    # INVARIANT (OME-307 Blocker 4): transaction rollback is the SOLE atomicity mechanism here.
    # ORMStore writes through the transaction's connection, so a failed OR cancelled publication
    # (including a 3.12 CancelledError, a BaseException) rolls back BOTH the index upsert and the
    # credential write. There is deliberately NO out-of-transaction compensation: a second,
    # post-rollback credential mutate is redundant with rollback AND could race a concurrent
    # writer that legitimately owns the slot (an ABA clobber). Any exception other than the
    # delete-wins conflict propagates unchanged so the enclosing txn rolls back and re-raises.
    try:
        async with in_transaction():
            # INVARIANT (OME-307 Unit 3): an observed-existing profile publishes conditionally
            # so a concurrent delete WINS (no resurrection); a first-time key stays an
            # unconditional create. Splitting the call keeps `upsert(profile)` — the create
            # contract — untouched for the common path.
            if profile_observed:
                await idx.upsert(profile, require_present=True)
            else:
                await idx.upsert(profile)
            await persist_credentials_or_503(
                strategy_for_slot,
                {"auth_type": "api_key", "api_key": api_key},
                description="API-key credentials",
            )
    except ProfileTransitionConflict as exc:
        # A concurrent delete removed the profile we were updating: delete wins, so the
        # rolled-back publication surfaces as a retryable conflict rather than a 500.
        raise HTTPException(
            status_code=409,
            detail={"code": "profile_conflict", "provider": provider, "profile": name},
        ) from exc
    # INVARIANT (OME-307 Unit 5): only after the API-key publication COMMITS do we
    # irreversibly cancel any in-flight OAuth flow for this profile. A late OAuth callback is
    # already rejected by authenticate_pending's pending-state CAS (it rolls back and returns
    # 409), so this pop is cleanup, not correctness. Deferring it past the commit means a
    # failed or cancelled publication above (including a 3.12 CancelledError, a BaseException)
    # leaves the older OAuth flow usable and orphans no credential. Closing loopback listeners
    # is network I/O and stays outside the transaction (SF-244 audit F10 stale cleanup).
    for stale_state in _pending(request).pop_for_profile(account_id, provider, name):
        await _close_loopback_callback(request.app, stale_state)
    _invalidate_profile_session(request.app, plugin, account_id, name)
    await _trigger_profile_discovery(request, plugin, account_id, profile)
    return profile.model_dump(mode="json")

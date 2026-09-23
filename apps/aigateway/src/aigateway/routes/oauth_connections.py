from __future__ import annotations

import logging
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from aigateway.core.auth.middleware import CurrentAccount
from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.errors import AuthError, CredentialNotFoundError
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.schemas import (
    CreateApiKeyConnectionRequest,
    CreateOAuthConnectionRequest,
    OAuthConnectionListResponse,
    OAuthConnectionResponse,
    OAuthConnectionTokenResponse,
    PatchOAuthConnectionRequest,
    SetConnectionApiKeyRequest,
    StartOAuthConnectionResponse,
)
from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
    response_from_connection,
)
from aigateway.core.oauth.token_service import (
    OAuthConnectionTokenError,
    oauth_connection_token_service,
)
from aigateway.core.oauth_pkce import generate_pkce, generate_state
from aigateway.core.pending_auth import PendingAuthEntry
from aigateway.core.plugin_base import credential_service_provider_for, credential_strategy_from
from aigateway.core.provider_access import (
    credential_has_other_owner,
    credential_name_of,
    lock_lower_addressers,
    republish_effective_api_key,
    retire_effective,
)
from aigateway.core.provider_access.connection_locator import credential_strategy_for_connection

from .api_key_validation import normalize_api_key, require_valid_api_key
from .auth import _redirect_uri_for
from .credential_persistence import persist_credentials_or_503
from .provider_access_http import refusals_as_http

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/v1/oauth/connections", response_model=OAuthConnectionListResponse)
async def list_connections(
    request: Request,
    current: CurrentAccount,
    provider: str | None = None,
    status: str | None = None,
) -> OAuthConnectionListResponse:
    store = _store(request)
    connections = await store.list(str(current.id), provider=provider, status=status)
    return OAuthConnectionListResponse(
        connections=[response_from_connection(connection) for connection in connections]
    )


@router.get("/v1/oauth/connections/{connection_id}", response_model=OAuthConnectionResponse)
async def get_connection(
    connection_id: UUID,
    request: Request,
    current: CurrentAccount,
) -> OAuthConnectionResponse:
    connection = await _get_visible_connection(request, str(current.id), connection_id)
    return connection


@router.post("/v1/oauth/connections", status_code=201, response_model=StartOAuthConnectionResponse)
async def start_connection_oauth(
    body: CreateOAuthConnectionRequest,
    request: Request,
    current: CurrentAccount,
) -> StartOAuthConnectionResponse:
    plugin = request.app.state.providers.get(body.provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": body.provider}
        )
    cfg = plugin.oauth_config()
    if cfg is None:
        raise HTTPException(status_code=400, detail={"code": "provider_does_not_use_oauth"})
    if plugin.requires_oauth_connection_label() and not body.label:
        raise HTTPException(
            status_code=422, detail={"code": "label_required", "provider": body.provider}
        )

    account_id = str(current.id)
    connection_id = uuid4()
    label = body.label or f"pending-{connection_id}"
    code_verifier, code_challenge = generate_pkce()
    state = generate_state()
    redirect_uri: str | None = None
    if body.redirect_uri is not None:
        redirect_uri = await _redirect_uri_for(
            request, body.provider, cfg, state, body.redirect_uri
        )
    store = _store(request)
    if body.label and await store.find_by_label(account_id, body.provider, body.label) is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": body.provider, "label": body.label},
        )
    try:
        await store.create_pending(
            account_id=account_id,
            provider=body.provider,
            label=label,
            connection_id=connection_id,
            credential_provider=credential_service_provider_for(plugin, body.provider),
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": body.provider, "label": label},
        ) from exc

    if redirect_uri is None:
        redirect_uri = await _redirect_uri_for(request, body.provider, cfg, state)
    request.app.state.pending_auth.put(
        state,
        PendingAuthEntry(
            account_id=account_id,
            provider=body.provider,
            profile_name=label,
            profile_id=str(connection_id),
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            connection_id=str(connection_id),
            requested_label=body.label,
        ),
    )

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
    return StartOAuthConnectionResponse(
        connection_id=connection_id,
        authorize_url=f"{cfg.authorize_url}?{urlencode(params)}",
        state=state,
    )


@router.post(
    "/v1/oauth/connections/api-key",
    status_code=201,
    response_model=OAuthConnectionResponse,
)
async def create_api_key_connection(
    body: CreateApiKeyConnectionRequest,
    request: Request,
    current: CurrentAccount,
) -> OAuthConnectionResponse:
    """Create an api-key-authenticated connection (no OAuth round-trip).

    The key is stored (encrypted at rest) in the same credential-blob slot the
    chat path reads for this connection, so it is usable on a real chat call
    immediately. The key is never echoed back or logged.
    """
    plugin = request.app.state.providers.get(body.provider)
    if plugin is None:
        raise HTTPException(
            status_code=404, detail={"code": "unknown_provider", "provider": body.provider}
        )
    api_key = normalize_api_key(body.api_key)
    account_id = str(current.id)
    connection_id = uuid4()
    # Build the strategy BEFORE creating any row: a provider that does not
    # support api-key auth (codex) yields None here and we 400 without leaving
    # an orphan connection. The credential_name is the same composite key the
    # chat path uses, so persist writes exactly the slot chat reads.
    strategy = credential_strategy_from(
        plugin,
        credential_key_for(account_id, connection_id),
        auth_type="api_key",
        credential_store=request.app.state.credential_store,
    )
    if strategy is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "api_key_not_supported", "provider": body.provider},
        )
    if plugin.requires_oauth_connection_label() and not body.label:
        raise HTTPException(
            status_code=422, detail={"code": "label_required", "provider": body.provider}
        )
    label = body.label or f"api-key-{connection_id}"
    store = _store(request)
    if await store.label_exists(account_id, body.provider, label):
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": body.provider, "label": label},
        )
    await require_valid_api_key(request, plugin, body.provider, api_key)
    # WHY (OME-307 Unit 4): persist the key and create the connection row in ONE short
    # transaction so ROLLBACK — not best-effort except-cleanup — is the atomicity mechanism.
    # A row failure (or a cancellation after the blob write) unwinds the credential write with
    # it, so neither an active connection-without-credential nor an orphan
    # credential-without-connection can ever commit. This matters most for cancellation: a
    # 3.12 asyncio.CancelledError is a BaseException an `except Exception` compensation could
    # never catch, but the transaction boundary rolls it back regardless. Persist runs before
    # the row inside the transaction, writing the blob slot keyed by the already-generated
    # connection_id — the exact slot the chat path reads (SF-291 review F4 ordering).
    try:
        async with in_transaction():
            await _persist_api_key_credentials(strategy, api_key)
            connection = await store.create_api_key(
                account_id=account_id,
                provider=body.provider,
                label=label,
                connection_id=connection_id,
                credential_provider=credential_service_provider_for(plugin, body.provider),
            )
    except IntegrityError as exc:
        # Duplicate label lost the race with a concurrent create. The transaction already
        # rolled the blob back, so no orphan remains — just surface the retryable conflict.
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": body.provider, "label": label},
        ) from exc
    credential_strategy_cache(request.app).evict(credential_key_for(account_id, connection_id))
    return response_from_connection(connection)


@router.put(
    "/v1/oauth/connections/{connection_id}/api-key",
    response_model=OAuthConnectionResponse,
)
async def set_connection_api_key(
    connection_id: UUID,
    body: SetConnectionApiKeyRequest,
    request: Request,
    current: CurrentAccount,
) -> OAuthConnectionResponse:
    """Replace the stored API key on an api-key connection.

    Accepts an active OR errored connection: replacing the key is exactly how a
    user recovers a connection that errored on a bad/missing key, so a
    successful replace re-activates it (SF-291 review RF2-1)."""
    account_id = str(current.id)
    store = _store(request)
    connection = await store.get(account_id, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
    if connection.auth_type != "api_key" or connection.status not in ("active", "error"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "connection_not_api_key",
                "message": "Connection does not use API-key authentication",
            },
        )
    api_key = normalize_api_key(body.api_key)
    plugin = request.app.state.providers.get(connection.provider)
    if plugin is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_provider", "provider": connection.provider},
        )
    # WHY the locator: a migrated pair's effective row addresses the Profile blob (S2'b4); a
    # plain row's UUID locator spells today's UUID name, so nothing changes for it.
    credential_name = credential_name_of(plugin, connection, account_id=account_id)
    strategy = credential_strategy_from(
        plugin,
        credential_name,
        auth_type="api_key",
        credential_store=request.app.state.credential_store,
    )
    if strategy is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "api_key_not_supported", "provider": connection.provider},
        )
    await require_valid_api_key(request, plugin, connection.provider, api_key)

    # WHY: validation is intentionally outside the transaction; only the short publication
    # boundary is serialized. Re-checking eligibility inside it prevents a stale validation
    # result from undoing a concurrent delete/revoke, and rollback keeps blob + row coherent.
    # INVARIANT (OME-307 Blocker 3): serialize on the ALWAYS-PRESENT connection row FIRST, then
    # write the credential blob SECOND — ONE consistent lock order shared with delete_connection.
    # reactivate is a conditional UPDATE (status IN active,error) that takes the connection-row
    # lock; a concurrent delete that revoked the row makes it match 0 rows, so we 409 and roll
    # back BEFORE writing any credential. The credential row may be ABSENT, and a missing-row
    # write/delete takes no lock under READ COMMITTED, so it can never serialize the race — only
    # the always-present connection row can. Persisting first would let a concurrent delete's
    # missing-row credential delete no-op, then our commit would orphan a credential under a
    # revoked connection.
    with refusals_as_http():
        async with in_transaction():
            connection = await _replace_api_key(
                request, store, account_id, connection_id, strategy, api_key
            )
    credential_strategy_cache(request.app).evict(credential_name)
    return response_from_connection(connection)


async def _replace_api_key(
    request: Request,
    store: OAuthConnectionStore,
    account_id: str,
    connection_id: UUID,
    strategy,
    api_key: str,
) -> OAuthConnection:
    """The publication boundary of a key replacement — marker → index → row → blob."""
    latest_connection = await store.get(account_id, connection_id)
    if (
        latest_connection is None
        or latest_connection.auth_type != "api_key"
        or latest_connection.status not in ("active", "error")
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "connection_conflict",
                "message": "Connection changed during API-key validation",
            },
        )
    # INVARIANT (D14, S2'b4): a migrated pair's effective row fences the pair and mirrors the
    # compat document FIRST (marker, index), then the row, then the blob — a no-op otherwise.
    await republish_effective_api_key(request.app, latest_connection, raw_api_key=api_key)
    connection = await store.reactivate(latest_connection)
    if connection is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "connection_conflict",
                "message": "Connection changed during API-key validation",
            },
        )
    await _persist_api_key_credentials(strategy, api_key)
    return connection


@router.patch("/v1/oauth/connections/{connection_id}", response_model=OAuthConnectionResponse)
async def patch_connection(
    connection_id: UUID,
    body: PatchOAuthConnectionRequest,
    request: Request,
    current: CurrentAccount,
) -> OAuthConnectionResponse:
    store = _store(request)
    connection = await store.get(str(current.id), connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
    if connection.status != "active":
        raise HTTPException(status_code=409, detail={"code": "connection_not_active"})
    if body.label is None:
        return response_from_connection(connection)
    try:
        patched = await store.patch_active_label(connection, body.label)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": connection.provider, "label": body.label},
        ) from exc
    if patched is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "connection_conflict", "message": "Connection changed during patch"},
        )
    return response_from_connection(patched)


@router.delete("/v1/oauth/connections/{connection_id}", status_code=204)
async def delete_connection(connection_id: UUID, request: Request, current: CurrentAccount) -> None:
    store = _store(request)
    with refusals_as_http():
        async with in_transaction():
            connection = await _delete_connection(request, store, str(current.id), connection_id)
    # Evict the shared cached strategy so a deleted connection's still-valid token
    # can't keep being served from memory (SF-282) — under the name the locator derives, which
    # for a migrated pair's effective row is the Profile address (S2'b4).
    plugin = request.app.state.providers.get(connection.provider)
    credential_strategy_cache(request.app).evict(
        credential_name_of(plugin, connection, account_id=str(current.id))
    )


async def _delete_connection(
    request: Request, store: OAuthConnectionStore, account_id: str, connection_id: UUID
) -> OAuthConnection:
    connection = await store.get(account_id, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
    # INVARIANT (D14, S2'b4): a migrated pair's effective row retires the pair FIRST — marker
    # (effective → None) and compat document — before the row and the blob; no-op otherwise.
    await retire_effective(request.app, connection)
    # WHY (D-R1-2): several rows — and, after an R1 rollback, the legacy Profile — may address ONE
    # blob; the blob goes with its LAST live addresser. The pair's live rows lock in ascending id
    # order around the revoke (lower here, own in mark_revoked, higher in the owner check).
    await lock_lower_addressers(connection)
    # INVARIANT (OME-307 Blocker 3): mark the ALWAYS-PRESENT connection row revoked FIRST
    # (mark_revoked UPDATEs by PK and takes its row lock, held until commit), THEN delete the
    # credential blob SECOND — ONE consistent lock order shared with set_connection_api_key.
    # The credential row may be ABSENT; a missing-row delete takes no lock under READ
    # COMMITTED, so it cannot serialize a concurrent set. Locking the connection row first
    # forces a racing set to observe the revoke (its reactivate CAS matches 0 rows and 409s),
    # so nothing is orphaned or resurrected.
    await store.mark_revoked(connection)
    keep_blob = await credential_has_other_owner(request.app, connection)
    if not keep_blob:
        await _delete_credentials(request, connection.credential_locator)
    return connection


@router.get(
    "/v1/oauth/connections/{connection_id}/token",
    response_model=OAuthConnectionTokenResponse,
)
async def get_connection_token(
    connection_id: UUID,
    request: Request,
    current: CurrentAccount,
) -> OAuthConnectionTokenResponse:
    """Return a fresh access token for the connection.

    Consumed by SF backend plugins that delegate token management to
    aigateway. The strategy refreshes against the upstream provider if
    the cached credential is within the refresh window.
    """
    from datetime import UTC, datetime

    try:
        token = await oauth_connection_token_service(request.app).get_token(
            account_id=current.id,
            connection_id=connection_id,
            store=_store(request),
            providers=request.app.state.providers,
            credential_store=request.app.state.credential_store,
            http_client_factory_for=lambda provider: getattr(
                request.app.state, f"{provider}_http_factory", None
            ),
            strategy_cache=credential_strategy_cache(request.app),
        )
    except OAuthConnectionTokenError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return OAuthConnectionTokenResponse(
        access_token=token.access_token,
        expires_at=datetime.fromtimestamp(token.expires_at_ms / 1000, tz=UTC),
    )


@router.post(
    "/v1/oauth/connections/{connection_id}/refresh", response_model=OAuthConnectionResponse
)
async def refresh_connection(
    connection_id: UUID,
    request: Request,
    current: CurrentAccount,
) -> OAuthConnectionResponse:
    store = _store(request)
    connection = await store.get(str(current.id), connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
    if connection.status != "active":
        raise HTTPException(status_code=409, detail={"code": "connection_not_active"})
    if connection.auth_type == "api_key":
        # /refresh is OAuth-only. An api-key connection has nothing to refresh,
        # and running oauth_strategy_for against its blob would raise and flip
        # the row to error (SF-291 review F2). Reject without mutating the row.
        raise HTTPException(status_code=400, detail={"code": "connection_not_oauth"})
    plugin = request.app.state.providers.get(connection.provider)
    if plugin is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_provider"})
    # Resolve the SHARED strategy (same cache key as chat/token dispatch) so its
    # asyncio.Lock single-flights the refresh across paths instead of a private
    # fresh strategy with its own lock (SF-323). The post-refresh eviction below
    # still forces later dispatch to rebuild from the persisted credentials.
    # WHY the locator (S2'b4): a migrated pair's effective row addresses the Profile blob; the
    # locator-derived name is the one the chat path caches under, so ONE eviction covers both.
    provider = connection.provider
    account_id = str(current.id)
    credential_name = credential_name_of(plugin, connection, account_id=account_id)
    strategy = credential_strategy_cache(request.app).get_or_create(
        provider=provider,
        auth_type="oauth",
        credential_name=credential_name,
        build=lambda: credential_strategy_for_connection(
            request.app, plugin, provider, connection, account_id=account_id
        ),
    )
    if strategy is None:
        raise HTTPException(status_code=400, detail={"code": "provider_does_not_use_oauth"})
    try:
        await strategy.refresh_credentials()
    except (CredentialNotFoundError, AuthError) as exc:
        await store.mark_error(connection, str(exc))
        credential_strategy_cache(request.app).evict(credential_name)
        raise HTTPException(
            status_code=401, detail={"code": "auth_required", "message": str(exc)}
        ) from exc
    # Manual refresh wrote new tokens to the store; drop the cached instance so the
    # chat path rebuilds and reads them (SF-282).
    credential_strategy_cache(request.app).evict(credential_name)
    # INVARIANT (OME-307 H-1): republish CONDITIONALLY on the still-active row. A delete or revoke
    # that raced this refresh's network window wins — complete_active updates zero rows and returns
    # None, and we 409 instead of flipping a revoked/deleted connection back to active.
    refreshed = await store.complete_active(
        connection,
        label=connection.label,
        identity=response_from_connection(connection).account,
    )
    if refreshed is None:
        raise HTTPException(status_code=409, detail={"code": "connection_conflict"})
    return response_from_connection(refreshed)


def _store(request: Request) -> OAuthConnectionStore:
    store = getattr(request.app.state, "oauth_connections", None)
    if isinstance(store, OAuthConnectionStore):
        return store
    store = OAuthConnectionStore()
    request.app.state.oauth_connections = store
    return store


async def _get_visible_connection(
    request: Request,
    account_id: str,
    connection_id: UUID,
) -> OAuthConnectionResponse:
    store = _store(request)
    connection = await store.get(account_id, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
    duplicate_id = _duplicate_id(connection.error_message)
    if connection.status == "revoked" and duplicate_id is not None:
        duplicate = await store.get(account_id, duplicate_id)
        if duplicate is not None:
            return response_from_connection(duplicate, is_duplicate=True)
    return response_from_connection(connection)


async def _delete_credentials(request: Request, locator: dict) -> None:
    service = locator.get("service")
    account = locator.get("account")
    if isinstance(service, str) and isinstance(account, str):
        await request.app.state.credential_store.delete(service, account)


async def _persist_api_key_credentials(strategy, api_key: str) -> None:
    await persist_credentials_or_503(
        strategy,
        {"auth_type": "api_key", "api_key": api_key},
        description="API-key credentials",
    )


def _duplicate_id(message: str | None) -> UUID | None:
    if not isinstance(message, str) or not message.startswith("duplicate:"):
        return None
    try:
        return UUID(message.split(":", 1)[1])
    except ValueError:
        return None

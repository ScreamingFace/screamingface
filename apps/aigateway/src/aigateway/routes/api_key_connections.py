"""API-key-authenticated Connection creation and credential replacement routes."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from aigateway.core.auth.middleware import CurrentAccount
from aigateway.core.credential_strategy_cache import credential_strategy_cache
from aigateway.core.oauth.schemas import (
    CreateApiKeyConnectionRequest,
    OAuthConnectionResponse,
    SetConnectionApiKeyRequest,
)
from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
    response_from_connection,
)
from aigateway.core.plugin_base import credential_service_provider_for, credential_strategy_from

from .api_key_validation import normalize_api_key, require_valid_api_key
from .credential_persistence import persist_credentials_or_503
from .profile_credential_lifecycle import retire_connection_credential

router = APIRouter()


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
    successful replace re-activates it (SF-291 review RF2-1).
    """
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
    strategy = credential_strategy_from(
        plugin,
        credential_key_for(account_id, connection.id),
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
    async with in_transaction():
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
    retire_connection_credential(request.app, account_id=account_id, connection=connection)
    return response_from_connection(connection)


def _store(request: Request) -> OAuthConnectionStore:
    store = getattr(request.app.state, "oauth_connections", None)
    if isinstance(store, OAuthConnectionStore):
        return store
    store = OAuthConnectionStore()
    request.app.state.oauth_connections = store
    return store


async def _persist_api_key_credentials(strategy, api_key: str) -> None:
    await persist_credentials_or_503(
        strategy,
        {"auth_type": "api_key", "api_key": api_key},
        description="API-key credentials",
    )

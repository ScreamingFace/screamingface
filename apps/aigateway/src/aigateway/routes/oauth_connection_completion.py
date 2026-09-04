"""Completing an OAuth CONNECTION flow (an account-level provider link).

A connection is not a profile: it is an account-scoped credential with an identity and
a label, and its duplicates are resolved rather than refused. Those rules — identity
extraction, duplicate identity/label handling, and the connection's own error marking —
live here so the profile completion path is not carrying them.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from ..core.credential_strategy_cache import credential_strategy_cache
from ..core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
)
from ..core.pending_auth import PendingAuthEntry
from ..core.plugin_base import (
    credential_service_provider_for,
)
from .auth_context import _credential_store_for_app
from .credential_persistence import (
    SupportsCredentialPersistence,
    persist_credentials_or_503,
)

logger = logging.getLogger(__name__)
router = APIRouter()


async def _mark_connection_error(app, pending: PendingAuthEntry, message: str) -> None:
    if pending.connection_id is None:
        return
    store = OAuthConnectionStore()
    connection = await store.get(pending.account_id, pending.connection_id)
    if connection is not None:
        # INVARIANT: only this callback's still-pending connection may transition to ERROR.
        # A concurrent DELETE or successful activation owns any non-pending row and wins.
        await store.mark_pending_error(connection, message)
    credential_strategy_cache(app).evict(
        credential_key_for(pending.account_id, pending.connection_id)
    )


async def _persist_connection_credentials(
    app,
    plugin,
    provider: str,
    account_id: str,
    connection_id: str,
    creds: dict,
) -> None:
    # WHY the import is inside the function: the builder lives in ``routes.auth``
    # (see the invariant there), and that module imports this one for connection
    # completion, so a module-level import would be a cycle.
    from .auth import _credential_strategy_for_credential_name

    strategy = _credential_strategy_for_credential_name(
        app,
        plugin,
        provider,
        credential_key_for(account_id, connection_id),
    )
    if strategy is not None:
        await persist_credentials_or_503(
            cast(SupportsCredentialPersistence, strategy),
            creds,
            description="OAuth connection credentials",
        )
    credential_strategy_cache(app).evict(credential_key_for(account_id, connection_id))


async def _record_oauth_connection_completion(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
) -> None:
    store = OAuthConnectionStore()
    if not _plugin_extracts_identity(plugin) and pending.connection_id is None:
        return
    identity = await _extract_connection_identity(app, pending, plugin, creds)
    label = _connection_label(pending, plugin, creds, identity)
    if not label:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_required", "provider": pending.provider},
        )

    if await _handle_duplicate_connection_identity(app, store, pending, plugin, label, identity):
        return
    if await _handle_duplicate_connection_label(app, store, pending, plugin, label, identity):
        return

    connection = await _connection_for_pending(store, pending, plugin, label)
    try:
        # INVARIANT: connection lifecycle operations lock the stable connection row before the
        # optional credential row. The pending-only CAS and credential write commit together, so
        # a concurrent DELETE wins without credential orphaning or stale-row resurrection.
        async with in_transaction():
            activated = await store.complete_pending(connection, label=label, identity=identity)
            if activated is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "connection_conflict",
                        "provider": pending.provider,
                    },
                )
            await _persist_connection_credentials(
                app,
                plugin,
                pending.provider,
                pending.account_id,
                str(activated.id),
                creds,
            )
    except IntegrityError as exc:
        await store.mark_revoked(connection, "connection_conflict")
        raise HTTPException(
            status_code=409,
            detail={"code": "connection_conflict", "provider": pending.provider, "label": label},
        ) from exc
    except HTTPException as exc:
        if exc.status_code == 503:
            await store.mark_pending_error(connection, "credential_store_unavailable")
        raise
    except Exception as exc:
        await store.mark_pending_error(connection, "connection_activation_failed")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "connection_activation_failed",
                "provider": pending.provider,
                "message": "Could not activate OAuth connection. Try again.",
            },
        ) from exc


def _plugin_extracts_identity(plugin) -> bool:
    return callable(getattr(plugin, "extract_identity", None))


async def _extract_connection_identity(
    app,
    pending: PendingAuthEntry,
    plugin,
    creds: dict,
) -> Any | None:
    extractor = getattr(plugin, "extract_identity", None)
    if not callable(extractor):
        return None
    return await cast(Callable[..., Awaitable[Any]], extractor)(
        creds,
        http_client_factory=getattr(app.state, f"{pending.provider}_http_factory", None),
    )


async def _handle_duplicate_connection_identity(
    app,
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    plugin,
    label: str,
    identity,
) -> bool:
    duplicate = await store.find_by_identity(
        pending.account_id, pending.provider, getattr(identity, "sub", None)
    )
    if duplicate is None:
        return False
    if pending.connection_id is not None:
        connection = await _connection_for_pending(store, pending, plugin, label)
        if duplicate.id != connection.id:
            await store.delete_or_supersede_pending(connection, duplicate)
            await _delete_connection_credentials(app, connection.credential_locator)
    return True


async def _handle_duplicate_connection_label(
    app,
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    plugin,
    label: str,
    identity,
) -> bool:
    if identity is not None and identity.sub is not None:
        return False
    duplicate_label = await store.find_by_label(pending.account_id, pending.provider, label)
    if duplicate_label is None:
        return False
    if pending.connection_id is None:
        return True
    connection = await _connection_for_pending(store, pending, plugin, label)
    if duplicate_label.id != connection.id:
        await store.delete_or_supersede_pending(connection, duplicate_label)
        await _delete_connection_credentials(app, connection.credential_locator)
    raise HTTPException(
        status_code=409,
        detail={"code": "label_conflict", "provider": pending.provider, "label": label},
    )


async def _delete_connection_credentials(app, locator: dict) -> None:
    service = locator.get("service")
    account = locator.get("account")
    if isinstance(service, str) and isinstance(account, str):
        await _credential_store_for_app(app).delete(service, account)


async def _connection_for_pending(
    store: OAuthConnectionStore,
    pending: PendingAuthEntry,
    plugin,
    label: str,
):
    if pending.connection_id is not None:
        connection = await store.get(pending.account_id, pending.connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail={"code": "connection_not_found"})
        return connection
    try:
        return await store.create_pending(
            account_id=pending.account_id,
            provider=pending.provider,
            label=label,
            connection_id=uuid4(),
            credential_provider=credential_service_provider_for(plugin, pending.provider),
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "label_conflict", "provider": pending.provider, "label": label},
        ) from exc


def _connection_label(pending: PendingAuthEntry, plugin, creds: dict, identity) -> str | None:
    if pending.requested_label:
        return pending.requested_label
    if identity is not None:
        label = identity.label()
        if label:
            return label
    label = plugin.account_label_from_credentials(creds)
    if label:
        return label
    return pending.compatibility_profile_name or pending.profile_name

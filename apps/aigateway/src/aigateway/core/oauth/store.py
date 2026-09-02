from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from tortoise.exceptions import DoesNotExist
from tortoise.expressions import F

from aigateway.core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from aigateway.core.auth.models import Account
from aigateway.core.profile_models import AuthType

from .identity import AccountIdentity
from .models import OAuthConnection
from .schemas import OAuthConnectionResponse, OAuthConnectionStatus

DEFAULT_CREDENTIAL_ACCOUNT = "default"


def credential_key_for(account_id: str | UUID, connection_id: str | UUID) -> str:
    return f"{account_id}:{connection_id}"


def credential_locator_for(
    provider: str,
    account_id: str | UUID,
    connection_id: str | UUID,
) -> dict[str, str]:
    return {
        "service": f"aigateway:{provider}:{credential_key_for(account_id, connection_id)}",
        "account": DEFAULT_CREDENTIAL_ACCOUNT,
    }


class OAuthConnectionStore:
    async def list(
        self,
        account_id: str | UUID,
        *,
        provider: str | None = None,
        status: str | None = None,
    ) -> list[OAuthConnection]:
        query = OAuthConnection.filter(account_id=account_id)
        if provider is not None:
            query = query.filter(provider=provider)
        if status is not None:
            query = query.filter(status=status)
        else:
            query = query.exclude(status="revoked")
        return await query.order_by("provider", "label", "created_at")

    async def get(
        self, account_id: str | UUID, connection_id: str | UUID
    ) -> OAuthConnection | None:
        try:
            return await OAuthConnection.get(id=connection_id, account_id=account_id)
        except DoesNotExist:
            return None

    async def create_pending(
        self,
        *,
        account_id: str | UUID,
        provider: str,
        label: str,
        connection_id: UUID,
        credential_provider: str | None = None,
    ) -> OAuthConnection:
        await _ensure_anonymous_account(account_id)
        return await OAuthConnection.create(
            id=connection_id,
            account_id=account_id,
            provider=provider,
            label=label,
            status="pending",
            credential_locator=credential_locator_for(
                credential_provider or provider,
                account_id,
                connection_id,
            ),
        )

    async def create_api_key(
        self,
        *,
        account_id: str | UUID,
        provider: str,
        label: str,
        connection_id: UUID,
        credential_provider: str | None = None,
    ) -> OAuthConnection:
        """Create an api-key connection in the active state directly.

        Unlike create_pending (OAuth: pending -> active on callback), an
        api-key connection has no browser round-trip, so it is authenticated
        the moment its key is stored. status has no DB default, so it is set
        explicitly here; auth_type is set to "api_key" (the column defaults to
        "oauth"). The credential_locator points at the same blob slot the chat
        path reads via credential_key_for(account_id, connection_id)."""
        await _ensure_anonymous_account(account_id)
        return await OAuthConnection.create(
            id=connection_id,
            account_id=account_id,
            provider=provider,
            label=label,
            status="active",
            auth_type="api_key",
            # OME-1026 U2: an active row means a PUBLISHED credential, so the durable
            # fence starts at 1 — 0 is reserved for rows that predate the fence.
            credential_generation=1,
            credential_locator=credential_locator_for(
                credential_provider or provider,
                account_id,
                connection_id,
            ),
        )

    async def find_by_identity(
        self,
        account_id: str | UUID,
        provider: str,
        identity_sub: str | None,
    ) -> OAuthConnection | None:
        if not identity_sub:
            return None
        return await OAuthConnection.filter(
            account_id=account_id,
            provider=provider,
            identity_sub=identity_sub,
            status="active",
        ).first()

    async def find_by_label(
        self,
        account_id: str | UUID,
        provider: str,
        label: str,
    ) -> OAuthConnection | None:
        return await OAuthConnection.filter(
            account_id=account_id,
            provider=provider,
            label=label,
            status="active",
        ).first()

    async def label_exists(
        self,
        account_id: str | UUID,
        provider: str,
        label: str,
    ) -> bool:
        """Check the same all-status label tuple enforced by the database constraint."""
        return await OAuthConnection.filter(
            account_id=account_id,
            provider=provider,
            label=label,
        ).exists()

    async def complete(
        self,
        connection: OAuthConnection,
        *,
        label: str,
        identity: AccountIdentity | None,
    ) -> OAuthConnection:
        connection.label = label
        connection.status = "active"
        connection.error_message = None
        connection.last_refreshed_at = datetime.now(UTC)
        if identity is not None:
            connection.identity_sub = identity.sub
            connection.identity_email = identity.email
            connection.identity_name = identity.name
            connection.identity_raw = identity.raw
        await connection.save()
        return connection

    async def complete_pending(
        self,
        connection: OAuthConnection,
        *,
        label: str,
        identity: AccountIdentity | None,
    ) -> OAuthConnection | None:
        """Activate a connection only while this OAuth callback still owns pending state."""
        refreshed_at = datetime.now(UTC)
        updates: dict = {
            "label": label,
            "status": "active",
            "error_message": None,
            "last_refreshed_at": refreshed_at,
        }
        if identity is not None:
            updates.update(
                identity_sub=identity.sub,
                identity_email=identity.email,
                identity_name=identity.name,
                identity_raw=identity.raw,
            )
        updated = await OAuthConnection.filter(
            id=connection.id,
            account_id=connection.account_id,
            status="pending",
        ).update(**updates)
        if updated != 1:
            return None
        for field, value in updates.items():
            setattr(connection, field, value)
        return connection

    async def complete_active(
        self,
        connection: OAuthConnection,
        *,
        label: str,
        identity: AccountIdentity | None,
    ) -> OAuthConnection | None:
        """Republish a refreshed connection only while it is still active.

        INVARIANT (OME-307 H-1): a manual refresh reads the row, runs the provider network call,
        then republishes. A delete/revoke that commits during that window must WIN. Fencing the
        write on ``status="active"`` (same idiom as ``complete_pending``) makes the republish
        update zero rows once the row leaves ``active``; the caller surfaces a conflict instead of
        resurrecting a revoked/deleted connection back to ``active``.
        """
        refreshed_at = datetime.now(UTC)
        updates: dict = {
            "label": label,
            "status": "active",
            "error_message": None,
            "last_refreshed_at": refreshed_at,
        }
        if identity is not None:
            updates.update(
                identity_sub=identity.sub,
                identity_email=identity.email,
                identity_name=identity.name,
                identity_raw=identity.raw,
            )
        updated = await OAuthConnection.filter(
            id=connection.id,
            account_id=connection.account_id,
            status="active",
        ).update(**updates)
        if updated != 1:
            return None
        for field, value in updates.items():
            setattr(connection, field, value)
        return connection

    async def mark_error(self, connection: OAuthConnection, message: str) -> OAuthConnection | None:
        updates: dict[str, object] = {"status": "error", "error_message": message}
        # OAuth connections are superseded by a fresh re-auth, so the old row's
        # label/identity are cleared. An api-key connection is re-keyed IN PLACE
        # (Replace key), so its label and identity must survive the error state
        # to stay recoverable (SF-291 review RF2-1).
        if connection.auth_type != "api_key":
            updates["label"] = f"error:{connection.id}"
            updates["identity_sub"] = None
        updated = await OAuthConnection.filter(
            id=connection.id,
            account_id=connection.account_id,
            status="active",
        ).update(**updates)
        if updated != 1:
            return None
        for field, value in updates.items():
            setattr(connection, field, value)
        return connection

    async def mark_pending_error(
        self,
        connection: OAuthConnection,
        message: str,
    ) -> OAuthConnection | None:
        """Mark an OAuth connection error only while its callback still owns pending state."""
        label = f"error:{connection.id}"
        updated = await OAuthConnection.filter(
            id=connection.id,
            account_id=connection.account_id,
            status="pending",
        ).update(
            label=label,
            identity_sub=None,
            status="error",
            error_message=message,
        )
        if updated != 1:
            return None
        connection.label = label
        connection.identity_sub = None
        connection.status = "error"
        connection.error_message = message
        return connection

    async def patch_active_label(
        self,
        connection: OAuthConnection,
        label: str,
    ) -> OAuthConnection | None:
        """Update a label only while the connection remains active."""
        updated = await OAuthConnection.filter(
            id=connection.id,
            account_id=connection.account_id,
            status="active",
        ).update(label=label)
        if updated != 1:
            return None
        connection.label = label
        return connection

    async def reactivate(self, connection: OAuthConnection) -> OAuthConnection | None:
        """Return an errored connection to active after its credential is
        replaced, unless a concurrent lifecycle operation made it ineligible."""
        refreshed_at = datetime.now(UTC)
        updated = await OAuthConnection.filter(
            id=connection.id,
            account_id=connection.account_id,
            auth_type="api_key",
            status__in=("active", "error"),
        ).update(
            status="active",
            error_message=None,
            last_refreshed_at=refreshed_at,
            # OME-1026 U2: re-keying keeps this row's id, so the durable fence is what
            # retires the old key's private snapshots. Atomic under the row lock —
            # two concurrent replaces serialize here and each gets its own generation.
            credential_generation=F("credential_generation") + 1,
        )
        if updated != 1:
            return None
        connection.status = "active"
        connection.error_message = None
        connection.last_refreshed_at = refreshed_at
        await connection.refresh_from_db(fields=["credential_generation"])
        return connection

    async def mark_revoked(
        self,
        connection: OAuthConnection,
        message: str | None = None,
    ) -> OAuthConnection:
        connection.label = f"revoked:{connection.id}"
        connection.identity_sub = None
        connection.status = "revoked"
        connection.error_message = message
        await connection.save(update_fields=["label", "identity_sub", "status", "error_message"])
        return connection

    async def delete_or_supersede_pending(
        self,
        connection: OAuthConnection,
        duplicate: OAuthConnection,
    ) -> OAuthConnection:
        return await self.mark_revoked(connection, f"duplicate:{duplicate.id}")

    async def touch_last_used(self, connection: OAuthConnection) -> OAuthConnection:
        connection.last_used_at = datetime.now(UTC)
        await connection.save(update_fields=["last_used_at"])
        return connection

    async def touch_last_refreshed(self, connection: OAuthConnection) -> OAuthConnection:
        connection.last_refreshed_at = datetime.now(UTC)
        await connection.save(update_fields=["last_refreshed_at"])
        return connection


def response_from_connection(
    connection: OAuthConnection,
    *,
    is_duplicate: bool = False,
) -> OAuthConnectionResponse:
    account = None
    if connection.identity_sub or connection.identity_email or connection.identity_name:
        account = AccountIdentity(
            sub=connection.identity_sub,
            email=connection.identity_email,
            name=connection.identity_name,
            raw=connection.identity_raw or {},
        )
    return OAuthConnectionResponse(
        id=connection.id,
        account_id=connection.account_id,
        provider=connection.provider,
        label=connection.label,
        # WHY: tortoise-orm >=1.1.8 types CharField as `str`, which no longer satisfies
        # these Literal aliases. The columns are bare CharFields, so the narrowing is ours
        # to assert; the Pydantic response model still rejects a junk value on construction.
        status=cast(OAuthConnectionStatus, connection.status),
        auth_type=cast(AuthType, connection.auth_type),
        account=account,
        credential_locator=connection.credential_locator,
        created_at=connection.created_at,
        last_used_at=connection.last_used_at,
        last_refreshed_at=connection.last_refreshed_at,
        error_message=connection.error_message,
        is_duplicate=is_duplicate,
    )


async def _ensure_anonymous_account(account_id: str | UUID) -> None:
    if str(account_id) != str(ANONYMOUS_ACCOUNT_ID):
        return
    await Account.get_or_create(
        id=ANONYMOUS_ACCOUNT_ID,
        defaults={
            "username": "anonymous",
            "password_hash": "",
            "display_name": "Anonymous",
            "is_active": True,
        },
    )

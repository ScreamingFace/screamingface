"""OME-1026 correction: durable Connection generations cover API-key ownership only."""

from __future__ import annotations

from uuid import uuid4

import pytest
from tortoise.contrib.test import tortoise_test_context

from aigateway.core.auth.models import Account
from aigateway.core.oauth.store import OAuthConnectionStore

_MODELS = ["aigateway.core.auth.models", "aigateway.core.oauth.models"]


@pytest.mark.asyncio
async def test_generic_completion_does_not_claim_an_api_key_publication() -> None:
    async with tortoise_test_context(_MODELS):
        account = await Account.create(username="complete", password_hash="hash")
        store = OAuthConnectionStore()
        connection = await store.create_pending(
            account_id=account.id,
            provider="codex",
            label="pending",
            connection_id=uuid4(),
        )

        completed = await store.complete(connection, label="active", identity=None)

        assert completed.credential_generation == 0


@pytest.mark.asyncio
async def test_oauth_callback_completion_preserves_the_generation() -> None:
    async with tortoise_test_context(_MODELS):
        account = await Account.create(username="callback", password_hash="hash")
        store = OAuthConnectionStore()
        connection = await store.create_pending(
            account_id=account.id,
            provider="codex",
            label="pending",
            connection_id=uuid4(),
        )

        completed = await store.complete_pending(connection, label="active", identity=None)

        assert completed is not None
        assert completed.credential_generation == 0


@pytest.mark.asyncio
async def test_oauth_refresh_metadata_preserves_the_generation() -> None:
    async with tortoise_test_context(_MODELS):
        account = await Account.create(username="refresh", password_hash="hash")
        store = OAuthConnectionStore()
        connection = await store.create_pending(
            account_id=account.id,
            provider="codex",
            label="pending",
            connection_id=uuid4(),
        )
        active = await store.complete(connection, label="active", identity=None)
        active.credential_generation = 7
        await active.save(update_fields=["credential_generation"])

        refreshed = await store.complete_active(active, label="refreshed", identity=None)

        assert refreshed is not None
        assert refreshed.credential_generation == 7

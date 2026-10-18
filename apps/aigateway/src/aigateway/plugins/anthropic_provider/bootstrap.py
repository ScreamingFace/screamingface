"""Anthropic bootstrap helpers for importing pre-seeded Claude Code credentials."""

from __future__ import annotations

import json
import logging

from aigateway.core.credential_blob.store import CredentialBlobStore, ORMStore
from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.errors import BootstrapError
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileDefaults, ProfileState

from .auth import credential_service_for
from .settings import AnthropicPluginSettings

logger = logging.getLogger(__name__)


async def bootstrap_from_claude_code(
    account_id: str,
    credential_store: CredentialBlobStore | None = None,
    index_store: ProfileIndexStore | None = None,
    cc_account: str | None = None,
    settings: AnthropicPluginSettings | None = None,
) -> None:
    config = settings or AnthropicPluginSettings()
    store = credential_store or ORMStore()
    idx = index_store or ProfileIndexStore(credential_store=store)
    account = cc_account if cc_account is not None else config.bootstrap_user

    existing = await idx.list(account_id)
    if existing:
        logger.debug("bootstrap: account index already populated; skipping")
        return

    cc_raw = await store.read(config.claude_code_keychain_service, account)
    if cc_raw is None:
        logger.info("bootstrap: no Claude Code credential entry found; nothing to import")
        return

    try:
        outer = json.loads(cc_raw)
        cc_creds = outer["claudeAiOauth"]
        converted = {
            "access_token": cc_creds["accessToken"],
            "refresh_token": cc_creds["refreshToken"],
            "expires_at_ms": int(cc_creds["expiresAt"]),
            "token_type": "Bearer",
        }
    except (KeyError, ValueError, TypeError) as exc:
        raise BootstrapError(f"Claude Code credential entry has unexpected shape: {exc}") from exc

    await store.write(
        credential_service_for(credential_name_for(account_id, "default")),
        config.keychain_account,
        json.dumps(converted),
    )
    profile = Profile(
        id=profile_id_for(account_id, "anthropic", "default"),
        account_id=account_id,
        provider="anthropic",
        name="default",
        scopes=cc_creds.get("scopes", []),
        state=ProfileState.AUTHENTICATED,
        defaults=ProfileDefaults(),
    )
    await idx.upsert(profile)
    logger.info("bootstrap: imported Claude Code creds into account-scoped anthropic:default")

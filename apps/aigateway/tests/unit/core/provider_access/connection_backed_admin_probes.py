"""Probes shared by the Connection-backed admin suites (OME-1208, S2'b1).

# AIDEV-NOTE: helpers only (the `legacy`/`migrated` fixtures stay in each suite, explicit);
# both admin suites share ONE probing vocabulary here instead of duplicating it.
"""

from __future__ import annotations

from typing import Any

from provider_access_harness import PROVIDER

from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
)
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.provider_access import (
    PairAuthorityStore,
    Selector,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

KEY = "sk-ant-api03-migrated-key-2468"
MASKED = f"API key ····{KEY[-4:]}"
DEFAULT = Selector.from_header(None)


def admin_of(harness: Any) -> Any:
    return harness.client.app.state.provider_credential_admin


def set_api_key(harness: Any, name: str | None = "default", key: str = KEY, **kwargs: Any) -> Any:
    kwargs.setdefault("defaults", None)
    return harness.call(
        admin_of(harness).set_api_key,
        harness.account_id,
        PROVIDER,
        raw_api_key=key,
        legacy_name=name,
        **kwargs,
    )


def delete(harness: Any, name: str = "default") -> None:
    harness.call(admin_of(harness).delete, harness.account_id, PROVIDER, legacy_name=name)


def list_summaries(harness: Any, provider: str | None = None) -> Any:
    return harness.call(admin_of(harness).list, harness.account_id, provider)


def document(harness: Any, name: str = "default") -> Profile | None:
    index = ProfileIndexStore(credential_store=harness.blobs.store)
    return harness.call(index.get, harness.account_id, PROVIDER, name)


def connection(harness: Any, connection_id: str) -> Any:
    return harness.call(OAuthConnectionStore().get, harness.account_id, connection_id)


def connections(harness: Any) -> list[Any]:
    return harness.call(OAuthConnectionStore().list, harness.account_id, provider=PROVIDER)


def marker(harness: Any) -> Any:
    return harness.call(PairAuthorityStore().read, harness.account_id, PROVIDER)


def blob_at_profile_address(harness: Any, name: str = "default") -> str | None:
    service = credential_service_for(credential_name_for(harness.account_id, name))
    return harness.blobs.read(service, "default")


def blob_at_connection_address(harness: Any, connection_id: str) -> str | None:
    service = credential_service_for(credential_key_for(harness.account_id, connection_id))
    return harness.blobs.read(service, "default")


def seed_legacy_provider(harness: Any, provider: str, name: str = "default") -> Profile:
    profile = Profile(
        id=profile_id_for(harness.account_id, provider, name),
        account_id=harness.account_id,
        provider=provider,
        name=name,
        state=ProfileState.AUTHENTICATED,
    )
    harness.call(ProfileIndexStore(credential_store=harness.blobs.store).upsert, profile)
    return profile


__all__ = [
    "DEFAULT",
    "KEY",
    "MASKED",
    "admin_of",
    "blob_at_connection_address",
    "blob_at_profile_address",
    "connection",
    "connections",
    "delete",
    "document",
    "list_summaries",
    "marker",
    "seed_legacy_provider",
    "set_api_key",
]

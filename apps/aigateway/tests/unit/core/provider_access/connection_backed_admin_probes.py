"""Probes shared by the Connection-backed admin suites (OME-1208, S2'b1).

# AIDEV-NOTE: helpers only (the `legacy`/`migrated` fixtures stay in each suite, explicit);
# both admin suites share ONE probing vocabulary here instead of duplicating it.
"""

from __future__ import annotations

from typing import Any

from provider_access_harness import PROVIDER

from aigateway.core.credential_names import credential_name_for
from aigateway.core.oauth.store import (
    OAuthConnectionStore,
    credential_key_for,
)
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile
from aigateway.core.provider_access import (
    PairAuthorityStore,
    Selector,
    delete_pair,
    set_pair_api_key,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

KEY = "sk-ant-api03-migrated-key-2468"
MASKED = f"API key ····{KEY[-4:]}"
DEFAULT = Selector.from_header(None)


async def _accept_key() -> None:
    return None


def put_pair_key(harness: Any, key: str = KEY) -> Any:
    """The surviving pair-level key write (D18) — what an intruder key write is since E3."""
    return harness.call(
        set_pair_api_key,
        harness.client.app,
        harness.account_id,
        PROVIDER,
        key,
        validate=_accept_key,
    )


def delete(harness: Any) -> None:
    """The surviving pair-level delete (D18): the pair ends with no credential."""
    harness.call(delete_pair, harness.client.app, harness.account_id, PROVIDER)


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


__all__ = [
    "DEFAULT",
    "KEY",
    "MASKED",
    "blob_at_connection_address",
    "blob_at_profile_address",
    "connection",
    "connections",
    "delete",
    "document",
    "marker",
    "put_pair_key",
]

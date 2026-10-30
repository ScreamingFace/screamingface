"""The Connection-backed harness for the provider-access CONTRACT suite (OME-1208, Stage B S2').

# FEATURE: Stage B Target — the contract tests run over a MIGRATED pair: an effective Connection
# whose `credential_locator` addresses the blob at the credential's name address (no secret
# re-entry) and a `migrated` pair marker (D14). What the tests observe as "the credential's state"
# is the authority's: the effective Connection's status, read back through the seed vocabulary.
# WHY `seed_credential` is the one seam that differs from the base harness: it seeds the migrated
# pair. `seed_connection` still creates a plain extra Connection with its UUID locator.
# FEATURE: OME-1138 Stage E, E5c — no Profile document is seeded beside the pair any more; the
# blob at the name address (`seed_blob`) is what a Profile-era install still holds.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from provider_access_harness import PROVIDER, RealAppHarness

from aigateway.core.auth_types import AuthType
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.provider_access import PairAuthorityStore
from tests.unit.seed_state import SeedState

# WHY the alias: `credential_locator_for(<credential-provider>, account, <name>)` spells the very
# service every plugin's `credential_service_for(credential_name_for(account, name))` spells, so
# the migrated Connection's locator IS the name address's blob (S1 verified fact).
CREDENTIAL_PROVIDER = "anthropic"

SEED_STATE_FOR_STATUS = {"active": "authenticated", "pending": "pending", "error": "error"}


async def migrate_pair(
    account_id: str,
    *,
    name: str = "default",
    state: SeedState = SeedState.AUTHENTICATED,
    auth_type: str = "oauth",
    label: str | None = None,
) -> OAuthConnection:
    """Seed a migrated pair — Connection + marker.

    The blob at the name address is the caller's (`seed_blob`); this creates the effective
    Connection pointing at that blob, in the status `state` maps to, and advances the pair marker
    to `migrated` on top of whatever generation it holds.
    """
    store = OAuthConnectionStore()
    label = label or name
    connection = await store.create_pending(
        account_id=account_id,
        provider=PROVIDER,
        label=label,
        connection_id=uuid4(),
        credential_provider=CREDENTIAL_PROVIDER,
    )
    connection.credential_locator = credential_locator_for(CREDENTIAL_PROVIDER, account_id, name)
    await connection.save(update_fields=["credential_locator"])
    if auth_type != "oauth":
        connection = await store.set_auth_type(connection, cast(AuthType, auth_type)) or connection
    if state is not SeedState.PENDING:
        connection = await store.complete(connection, label=label, identity=None)
    if state is SeedState.ERROR:
        # WHY via active: an errored authority is one that WAS usable — `mark_error` transitions
        # only a non-pending row, exactly as the read path marks a rejected credential.
        connection = await store.mark_error(connection, "seeded error") or connection
    markers = PairAuthorityStore()
    current = await markers.read(account_id, PROVIDER)
    await markers.advance(
        account_id,
        PROVIDER,
        expected_generation=current.generation,
        migration_state="migrated",
        effective_connection_id=connection.id,
    )
    refreshed = await store.get(account_id, connection.id)
    return refreshed if refreshed is not None else connection


class ConnectionBackedHarness(RealAppHarness):
    """The real app's port over a MIGRATED pair; every recorder of the base harness applies."""

    def __init__(self, client: Any, credential_blobs: Any, monkeypatch: Any) -> None:
        super().__init__(client, credential_blobs, monkeypatch)
        self.migrated: dict[str, str] = {}

    def seed_authority(
        self,
        *,
        name: str = "default",
        state: SeedState = SeedState.AUTHENTICATED,
        auth_type: str = "oauth",
        label: str | None = None,
    ) -> str:
        """Only the effective Connection (locator → the name address) and the `migrated` marker."""
        connection = self.call(
            migrate_pair, self.account_id, name=name, state=state, auth_type=auth_type, label=label
        )
        self.migrated[name] = str(connection.id)
        return str(connection.id)

    def seed_credential(
        self,
        *,
        name: str = "default",
        state: SeedState = SeedState.AUTHENTICATED,
        auth_type: str = "oauth",
        credential: str | None = "tok",
    ) -> None:
        """The situation "a stored credential in `state`" — as a migrated pair."""
        self.seed_blob(name=name, auth_type=auth_type, credential=credential)
        self.seed_authority(name=name, state=state, auth_type=auth_type)

    def credential_state(self, name: str = "default") -> str | None:
        """The authority's state in the seed vocabulary: the effective Connection's status."""
        connection_id = self.migrated.get(name)
        if connection_id is None:
            return None
        status = self.connection_status(connection_id)
        return None if status is None else SEED_STATE_FOR_STATUS.get(status, status)


__all__ = [
    "CREDENTIAL_PROVIDER",
    "SEED_STATE_FOR_STATUS",
    "ConnectionBackedHarness",
    "migrate_pair",
]

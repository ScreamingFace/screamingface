"""Probes shared by the E5b purge suites (OME-1138 Stage E): seeding, raw rows, leak scans.

# FEATURE: Stage E history cleanup — the suites name a situation (an account, a Connection row of
# any status and locator, a pair marker, a Profile document, a blob at an address) and read the
# raw `credential_blobs` rows back; the purge itself runs through the real stores on the app.
# WHY Connection rows are created directly: the purge must classify rows no live flow would mint
# today (a malformed locator, an unloaded provider, an `error` row), so the seed names the columns.
"""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from aigateway.core.auth.models import Account
from aigateway.core.credential_names import profile_id_for
from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import credential_locator_for
from aigateway.core.profile_index import INDEX_CREDENTIAL_SERVICE, ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileIndex, ProfileState
from aigateway.core.provider_access.history_purge import PurgeContext, PurgeReport, run_purge
from aigateway.core.provider_access.pair_authority import PairAuthorityStore

ANTHROPIC = "anthropic"
SECRET = "sk-purge-secret-4242"
# WHY: every string a leaking report or journal line could carry — scanned by `leaks_in`.
NEEDLES = ("aigateway:", "default", "v1:", SECRET, "account:")
Address = tuple[str, str]


def address(account_id: str, suffix: str | UUID, *, cp: str = ANTHROPIC) -> str:
    """A provider-credential service under `cp`'s namespace for this account."""
    return f"aigateway:{cp}:{account_id}:{suffix}"


def index_row(account_id: str) -> Address:
    return INDEX_CREDENTIAL_SERVICE, f"account:{account_id}"


LEGACY_INDEX_ROW: Address = (INDEX_CREDENTIAL_SERVICE, "default")


class PurgeHarness:
    def __init__(self, client: Any, credential_blobs: Any) -> None:
        self.client = client
        self.blobs = credential_blobs

    @property
    def app(self) -> Any:
        return self.client.app

    def call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return self.client.portal.call(partial(fn, *args, **kwargs))

    def context(self, providers: Any = None) -> PurgeContext:
        return PurgeContext.build(self.app, providers or self.app.state.providers)

    def purge(
        self,
        mode: str = "apply",
        *,
        accounts: tuple[str, ...] | None = None,
        journal: io.StringIO | None = None,
        providers: Any = None,
    ) -> PurgeReport:
        """`accounts=None` is `--all`."""
        return self.call(
            run_purge, self.context(providers), mode=mode, account_ids=accounts, journal=journal
        )

    # --- seeding ---------------------------------------------------------------------------

    def new_account(self) -> str:
        account_id = str(uuid4())
        self.call(
            Account.create, id=account_id, username=f"purge-{account_id[:8]}", password_hash="x"
        )
        return account_id

    def connection(
        self,
        account_id: str,
        *,
        provider: str = ANTHROPIC,
        status: str = "active",
        auth_type: str = "oauth",
        locator: Any = None,
        cp: str | None = None,
    ) -> UUID:
        """A Connection row; its locator defaults to its own `<account>:<uuid>` address."""
        connection_id = uuid4()
        if locator is None:
            locator = credential_locator_for(cp or provider, account_id, connection_id)
        self.call(
            OAuthConnection.create,
            id=connection_id,
            account_id=account_id,
            provider=provider,
            label=f"c-{connection_id.hex[:8]}",
            status=status,
            auth_type=auth_type,
            credential_locator=locator,
        )
        return connection_id

    def blob(self, service: str, account: str = "default") -> Address:
        self.blobs.write(service, account, json.dumps({"auth_type": "api_key", "api_key": SECRET}))
        return service, account

    def document(
        self, account_id: str, *, provider: str = ANTHROPIC, name: str = "default"
    ) -> None:
        """A Profile document in the account's own index row."""
        store = ProfileIndexStore(credential_store=self.blobs.store)
        self.call(store.upsert, profile(account_id, provider=provider, name=name))

    def legacy_documents(self, *profiles: Profile) -> None:
        """The pre-split global index row, listing these documents."""
        self.blobs.write(*LEGACY_INDEX_ROW, ProfileIndex(profiles=list(profiles)).model_dump_json())

    def mark(
        self,
        account_id: str,
        state: str,
        *,
        provider: str = ANTHROPIC,
        effective: UUID | None = None,
    ) -> None:
        self.call(
            PairAuthorityStore().advance,
            account_id,
            provider,
            expected_generation=0,
            migration_state=state,
            effective_connection_id=effective,
        )

    # --- observation -----------------------------------------------------------------------

    def rows(self) -> set[Address]:
        with closing(sqlite3.connect(self.blobs.db_path)) as conn:
            return set(conn.execute("select service, account from credential_blobs").fetchall())

    def dump(self) -> list[str]:
        """Every table, byte for byte."""
        with closing(sqlite3.connect(self.blobs.db_path)) as conn:
            return list(conn.iterdump())

    def sql(self, statement: str, *params: Any) -> None:
        with closing(sqlite3.connect(self.blobs.db_path)) as conn, conn:
            conn.execute(statement, params)


def profile(account_id: str, *, provider: str = ANTHROPIC, name: str = "default") -> Profile:
    return Profile(
        id=profile_id_for(account_id, provider, name),
        account_id=account_id,
        provider=provider,
        name=name,
        state=ProfileState.AUTHENTICATED,
    )


def leaks_in(text: str) -> list[str]:
    return [needle for needle in NEEDLES if needle in text]


def zero_counts(**nonzero: int) -> dict[str, int]:
    counts = {
        "index_rows": 0,
        "name_shaped_blobs": 0,
        "uuid_shaped_blobs": 0,
        "deleted_account_blobs": 0,
        "kept_unrecognised_rows": 0,
        "kept_unproven_rows": 0,
        "skipped_accounts": 0,
    }
    counts.update(nonzero)
    return counts


__all__ = [
    "ANTHROPIC",
    "LEGACY_INDEX_ROW",
    "SECRET",
    "Address",
    "PurgeHarness",
    "address",
    "index_row",
    "leaks_in",
    "profile",
    "zero_counts",
]

"""The D18 successor PUT/DELETE bridge racing on PostgreSQL (OME-1497, G1 part 2).

# FEATURE: OME-1138 D18 (contract §5.1, §5.3, §8) — the mutation bridge adopts a `none` pair under
# the same pair-generation fence every G0 writer claims. Two writers that captured one generation
# commit exactly one ownership change; the loser rolls back whole — no orphan Connection, document
# or blob — and is reported as superseded, never retried on a fresh read.
# INVARIANT: PostgreSQL blocks the second writer on the marker row (or the first marker's unique
# INSERT) until the first commits, then its predicate matches nothing; SQLite's single writer
# cannot show that ordering, which is why this lane exists.
# NOTE: fixtures are bound from the backing lane: one container per module, migrated to
# head. Run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any
from uuid import uuid4

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import Profile, ProfileState
from aigateway.core.provider_access import (
    PairAuthorityStore,
    WriteConflict,
    delete_pair,
    set_pair_api_key,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
KEY = "sk-ant-api03-postgres-bridge-key-1111"
LEGACY_KEY = "sk-ant-api03-postgres-legacy-key-2222"


async def _valid() -> None:
    return None


def _outcome(fn: Any) -> Any:
    """Run one writer to completion; a lost write comes back as its `WriteConflict`."""
    try:
        return fn()
    except WriteConflict as exc:
        return exc


def _bridge_put(client: TestClient, account_id: str) -> Any:
    return _outcome(
        partial(
            backing._call,
            client,
            set_pair_api_key,
            backing._app(client),
            account_id,
            PROVIDER,
            KEY,
            validate=_valid,
        )
    )


def _bridge_delete(client: TestClient, account_id: str) -> Any:
    return _outcome(
        partial(backing._call, client, delete_pair, backing._app(client), account_id, PROVIDER)
    )


async def _seed_legacy_profile(app: Any, account_id: str, name: str) -> None:
    """A single-Connection `none` pair at a legacy Profile's address: claim, document, blob, row.

    # WHY store seeding: the Profile api-key route answers 410 since OME-1209 Stage E3, and the
    # native create would write a Connection-addressed blob, not the Profile address under test.
    # WHY the Connection: D18 reads no Profile document since OME-1209 Stage E4a, so a Profile
    # alone is the empty pair; one active row at its address keeps the pair in row 9.
    """
    markers = PairAuthorityStore()
    pair = await markers.read(account_id, PROVIDER)
    await markers.advance(
        account_id, PROVIDER, expected_generation=pair.generation, migration_state="none"
    )
    await app.state.credential_store.write(
        credential_service_for(credential_name_for(account_id, name)),
        "default",
        backing._api_key_blob(LEGACY_KEY),
    )
    await backing._index(app).upsert(
        Profile(
            id=profile_id_for(account_id, PROVIDER, name),
            account_id=account_id,
            provider=PROVIDER,
            name=name,
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )
    await OAuthConnectionStore().create_api_key(
        account_id=account_id,
        provider=PROVIDER,
        label=name,
        connection_id=uuid4(),
        credential_provider=PROVIDER,
        credential_locator=credential_locator_for(PROVIDER, account_id, name),
    )


def _race(monkeypatch: pytest.MonkeyPatch, first: Any, second: Any) -> tuple[Any, Any]:
    """Run `first` until it holds the marker, start `second`, then let `first` commit."""
    hold = backing._MarkerHold(monkeypatch, holds=lambda index, _kw: index == 0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        winning = executor.submit(first)
        assert hold.held.wait(20), "the first writer never claimed the pair"
        losing = executor.submit(second)
        assert hold.attempted.wait(20), "the second writer never reached its claim"
        hold.release.set()
        return winning.result(timeout=30), losing.result(timeout=30)


def _live(client: TestClient, account_id: str) -> list[Any]:
    return backing._call(client, OAuthConnectionStore().list, account_id, provider=PROVIDER)


def _blob(client: TestClient, account_id: str, name: str) -> str | None:
    raw = backing._profile_blob(client, account_id, name)
    return None if raw is None else json.loads(raw)["api_key"]


def _fresh_pair(client: TestClient) -> str:
    account_id = backing._account_id(client)
    app = backing._app(client)
    backing._call(client, backing._reset_pair, app, account_id)
    # WHY: the shared reset keeps blobs, and the bridge's default address is reused across tests.
    default = credential_locator_for(PROVIDER, account_id, "default")
    backing._call(client, app.state.credential_store.delete, default["service"], default["account"])
    return account_id


def _superseded(outcome: Any) -> bool:
    return isinstance(outcome, WriteConflict) and outcome.kind == "superseded"


def test_two_first_bridge_puts_commit_exactly_one_and_leave_no_orphan_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = _fresh_pair(pg_client)

    won, lost = _race(
        monkeypatch,
        partial(_bridge_put, pg_client, account_id),
        partial(_bridge_put, pg_client, account_id),
    )

    assert not isinstance(won, WriteConflict), won
    assert _superseded(lost), lost
    # INVARIANT: the loser's Connection INSERT rolled back with its lost first-marker INSERT.
    (row,) = _live(pg_client, account_id)
    assert row.credential_locator == credential_locator_for(PROVIDER, account_id, "default")
    pair = backing._marker(pg_client, account_id)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        row.id,
        1,
    )
    assert _blob(pg_client, account_id, "default") == KEY


@pytest.mark.parametrize("put_first", [True, False], ids=["put-first", "delete-first"])
def test_a_bridge_put_and_delete_on_a_sole_profile_commit_exactly_one_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch, put_first: bool
) -> None:
    account_id = _fresh_pair(pg_client)
    name = backing._fresh_name()
    backing._call(pg_client, _seed_legacy_profile, backing._app(pg_client), account_id, name)
    put = partial(_bridge_put, pg_client, account_id)
    delete = partial(_bridge_delete, pg_client, account_id)

    won, lost = _race(monkeypatch, *((put, delete) if put_first else (delete, put)))

    assert not isinstance(won, WriteConflict), won
    assert _superseded(lost), lost
    pair = backing._marker(pg_client, account_id)
    assert pair.migration_state == "migrated"
    if put_first:
        (row,) = _live(pg_client, account_id)
        assert pair.effective_connection_id == row.id
        assert backing._document(pg_client, account_id, name) is not None
        assert _blob(pg_client, account_id, name) == KEY
    else:
        # INVARIANT: the stale PUT never resurrects the credential the DELETE removed.
        assert pair.effective_connection_id is None
        assert _live(pg_client, account_id) == []
        # WHY the document survives (OME-1209 E4b): the DELETE removes no document; E5 does.
        assert backing._document(pg_client, account_id, name) is not None
        assert _blob(pg_client, account_id, name) is None

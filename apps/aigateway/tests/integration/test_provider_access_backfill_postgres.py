"""The backfill on PostgreSQL: apply, idempotent re-run, the FIRST-marker race (OME-1208, S4).

# FEATURE: `python -m aigateway.migrate_profiles --apply` against the production engine: a
# Profile-only pair migrates without re-entry and the JSONB locator round-trips; a second run is a
# no-op; two apply runs racing for one pair's FIRST marker (both at generation 0) end with exactly
# one Connection and one marker — the loser's whole account transaction rolls back on the unique
# constraint and is reported as a conflict, never as a duplicate.
# INVARIANT (D14, card "apply is idempotent and crash/retry safe"): PostgreSQL blocks the second
# INSERT on the unique `(account_id, provider)` marker — or the `(account_id, provider, label)`
# Connection — until the first commits, then raises `IntegrityError`; SQLite's single writer cannot
# show that ordering, which is why this lane exists.
# AIDEV-NOTE: fixtures are bound from the S2'c module (itself bound from the lifecycle lane): one
# container per module, migrated to head by the tortoise CLI. Run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import pytest
import test_provider_access_backing_postgres as backing
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.oauth.models import OAuthConnection
from aigateway.core.oauth.store import OAuthConnectionStore, credential_locator_for
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.core.provider_access.backfill_apply import apply_account, run_backfill
from aigateway.core.provider_access.backfill_classify import BackfillContext
from aigateway.core.provider_access.models import ProviderCredentialSlot
from aigateway.core.provider_access.pair_authority import PairAuthorityStore

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = "anthropic"


def _app(client: TestClient) -> FastAPI:
    app = client.app
    if not isinstance(app, FastAPI):
        raise AssertionError("TestClient is not running the expected FastAPI app")
    return app


def _call(
    client: TestClient, fn: Callable[..., Coroutine[Any, Any, Any]], *a: Any, **kw: Any
) -> Any:
    portal = client.portal
    if portal is None:
        raise AssertionError("TestClient portal is not active")
    return portal.call(partial(fn, *a, **kw))


async def _reset_and_seed_profile_only(app: FastAPI, account_id: str, name: str) -> None:
    await ProviderCredentialSlot.filter(account_id=account_id, provider=PROVIDER).delete()
    await OAuthConnection.filter(account_id=account_id, provider=PROVIDER).delete()
    for document in await app.state.profile_index.list(account_id, provider=PROVIDER):
        await app.state.profile_index.remove(document.id)
    locator = credential_locator_for(PROVIDER, account_id, name)
    # WHY: the S2'c helper's blob carries `expires_at_ms` — the token route refuses one without it.
    await app.state.credential_store.write(
        locator["service"], locator["account"], backing._oauth_blob("tok")
    )
    await app.state.profile_index.upsert(
        Profile(
            id=profile_id_for(account_id, PROVIDER, name),
            account_id=account_id,
            provider=PROVIDER,
            name=name,
            state=ProfileState.AUTHENTICATED,
        )
    )


def _seed(client: TestClient) -> tuple[str, str, BackfillContext]:
    account_id = client.get("/v1/auth/me").json()["id"]
    name = f"pair-{account_id[:8]}"
    _call(client, _reset_and_seed_profile_only, _app(client), account_id, name)
    return account_id, name, BackfillContext.from_app(_app(client))


def _connections(client: TestClient, account_id: str) -> list[Any]:
    return _call(client, OAuthConnectionStore().list, account_id, provider=PROVIDER)


def _marker(client: TestClient, account_id: str) -> Any:
    return _call(client, PairAuthorityStore().read, account_id, PROVIDER)


def test_apply_migrates_a_profile_only_pair_on_postgres_and_a_rerun_is_a_no_op(
    pg_client: TestClient,
) -> None:
    account_id, name, ctx = _seed(pg_client)

    report = _call(pg_client, run_backfill, ctx, mode="apply", account_ids=(account_id,))

    (record,) = report.accounts[0].records
    assert (record.category, record.applied, record.generation) == ("profile_only", True, 1)
    (row,) = _connections(pg_client, account_id)
    assert (row.label, row.status, row.auth_type) == (name, "active", "oauth")
    # WHY: JSONB — the locator must come back as the very mapping the strategy factory parses.
    assert row.credential_locator == credential_locator_for(PROVIDER, account_id, name)
    pair = _marker(pg_client, account_id)
    assert (pair.migration_state, pair.effective_connection_id, pair.generation) == (
        "migrated",
        row.id,
        1,
    )
    token = pg_client.get(f"/v1/oauth/connections/{row.id}/token")
    assert token.status_code == 200, token.text
    assert token.json()["access_token"] == "tok"

    again = _call(pg_client, run_backfill, ctx, mode="apply", account_ids=(account_id,))
    (record,) = again.accounts[0].records
    assert (record.category, record.applied) == ("already_migrated", False)
    assert len(_connections(pg_client, account_id)) == 1
    assert _marker(pg_client, account_id).generation == 1


def test_two_apply_runs_racing_for_the_first_marker_leave_one_connection(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id, _name, ctx = _seed(pg_client)
    held = threading.Event()
    second_started = threading.Event()
    release = threading.Event()
    real_advance = PairAuthorityStore.advance
    real_create = OAuthConnectionStore.create_pending

    async def advance(store: Any, *args: Any, **kwargs: Any) -> Any:
        result = await real_advance(store, *args, **kwargs)
        if not held.is_set():
            # The first run: its Connection and marker are INSERTed, uncommitted, rows locked.
            held.set()
            if not await asyncio.to_thread(release.wait, 20):
                raise TimeoutError("the first apply was never released")
        return result

    async def create_pending(store: Any, *args: Any, **kwargs: Any) -> Any:
        if held.is_set():
            # The second run classified the pair with no marker visible (READ COMMITTED) and now
            # tries to insert its own Connection — PostgreSQL parks it behind the first's row.
            second_started.set()
        return await real_create(store, *args, **kwargs)

    monkeypatch.setattr(PairAuthorityStore, "advance", advance)
    monkeypatch.setattr(OAuthConnectionStore, "create_pending", create_pending)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_call, pg_client, apply_account, ctx, account_id)
        assert held.wait(20), "the first apply never reached its marker advance"
        second = executor.submit(_call, pg_client, apply_account, ctx, account_id)
        assert second_started.wait(20), "the second apply never reached its Connection insert"
        release.set()
        winner = first.result(timeout=30)
        loser = second.result(timeout=30)

    assert winner.conflict is False and winner.records[0].applied is True
    # INVARIANT: the loser's account transaction rolled back as a whole — no second Connection, no
    # second marker, and it says so instead of guessing.
    assert loser.conflict is True and loser.records[0].applied is False
    assert len(_connections(pg_client, account_id)) == 1
    pair = _marker(pg_client, account_id)
    assert (pair.migration_state, pair.generation) == ("migrated", 1)
    monkeypatch.undo()
    rerun = _call(pg_client, run_backfill, ctx, mode="apply", account_ids=(account_id,))
    assert rerun.accounts[0].records[0].category == "already_migrated"
    assert len(_connections(pg_client, account_id)) == 1

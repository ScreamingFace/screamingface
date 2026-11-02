"""OME-307 Blocker 3 — atomic connection revoke/delete versus a racing API-key replace.

FEATURE: deleting an api-key connection (connection row + credential blob) and replacing the
API key on that same connection (``set_connection_api_key``).
STORY: as a user who deletes a connection while an API-key replace for that same connection is
still in flight, the delete wins cleanly — no encrypted credential is left behind under a
revoked connection, and the older replace does not silently reactivate the connection I just
deleted.

INVARIANT: ``set_connection_api_key`` and ``delete_connection`` each publish the
connection-row transition and the credential blob write/delete in ONE transaction, in ONE
consistent lock order — the ALWAYS-PRESENT connection row FIRST, the credential blob SECOND.
Serializing on the credential row instead fails when that row is ABSENT: a missing-row delete
takes no lock under READ COMMITTED, so it cannot serialize a concurrent INSERT, orphaning a
credential under a revoked connection. The profile analogue of this race retired with the
Profile index at OME-1138 Stage E, E5c.

WHY a store double: the gateway unit harness is SQLite-only and serializes whole transactions
on one connection, so it cannot exhibit the PostgreSQL per-row interleaving this race needs. In
production the connection row (``oauth_connections``) and the credential blob
(``credential_blobs``) live in the SAME database and are published in ONE ``in_transaction()``,
so they share one MVCC snapshot and lock manager — modelled here as two keys in one
``MvccRowStore``. The connection-row operations transcribe the VERIFIED production semantics:
``OAuthConnectionStore.reactivate`` is a conditional CAS (``UPDATE ... WHERE status IN
('active','error')``; 0 rows -> ``None`` -> the route raises 409 -> rollback) and
``OAuthConnectionStore.mark_revoked`` is an unconditional ``UPDATE`` by primary key. The real
methods' sequential behaviour is guarded by the route-level tests in
``test_api_key_connection_races.py``; this file guards the per-row lock-ordering invariant those
serialized tests cannot exercise.
"""

from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from aigateway.core.oauth.store import OAuthConnectionStore

from ._pg_mvcc_store import MvccRowStore

# The always-present connection row and the (possibly-absent) credential blob slot the chat
# path reads for this connection. Only their identity as distinct contended rows matters.
_CONN_SERVICE = "aigateway:oauth:connection"
_CONN_ACCOUNT = "account-1:conn-1"
_CRED_SERVICE = "aigateway:anthropic:cred"
_CRED_ACCOUNT = "account-1:conn-1"


class _ReactivateConflict(Exception):
    """Models ``OAuthConnectionStore.reactivate`` matching 0 rows (connection concurrently
    revoked): the conditional UPDATE changes nothing, the route receives ``None`` and raises
    409, and the transaction rolls back. Raised from inside ``mutate`` so the transaction
    unwinds exactly as the route's 409 does — the credential write never commits."""


def _status_of(raw: str | None) -> str | None:
    return None if raw is None else json.loads(raw)["status"]


def _reactivate(current: str | None) -> str:
    # WHY: transcribes OAuthConnectionStore.reactivate — UPDATE ... WHERE status IN
    # ('active','error'). A concurrently-revoked row matches nothing, which the route maps to a
    # 409; here that is a raise so the enclosing transaction rolls back the same way.
    if _status_of(current) not in ("active", "error"):
        raise _ReactivateConflict
    return json.dumps({"status": "active"})


async def _seed_connection_without_credential(store: MvccRowStore) -> None:
    # An errored api-key connection legitimately has a connection row but NO credential blob —
    # the credential-absent precondition the review requires. The always-present connection row
    # is seeded; the credential row is deliberately NOT written.
    await store.write(_CONN_SERVICE, _CONN_ACCOUNT, json.dumps({"status": "error"}))


@pytest.mark.asyncio
async def test_conn_delete_wins_over_set_when_delete_commits_first_credential_absent() -> None:
    """Credential row ABSENT, ``delete_connection`` commits first.

    Production ordering under test (connection-row transition FIRST, credential SECOND):

      1. DELETE acquires the always-present connection-row lock (``mark_revoked``), then its
         credential delete finds NO credential row (absent) — a no-op that takes no lock — and
         COMMITS. Connection revoked.
      2. SET was blocked on the connection-row lock; it now runs ``reactivate``, re-evaluates
         the committed status, finds it revoked, and raises (the route's 409) — it must NOT
         reactivate the revoked connection, and its API-key blob write is never committed.

    Final state: connection revoked, credential absent — delete wins, no orphan, no
    resurrection. Serializing on the credential row instead would fail: the missing-row delete
    takes no lock, so SET's later INSERT would not be serialized and would orphan a credential.
    """
    store = MvccRowStore()
    await _seed_connection_without_credential(store)
    delete_holds_conn = asyncio.Event()

    async def delete_op() -> None:
        async with store.transaction():
            # mark_revoked: unconditional UPDATE by PK on the always-present connection row.
            await store.write(_CONN_SERVICE, _CONN_ACCOUNT, json.dumps({"status": "revoked"}))
            delete_holds_conn.set()
            await store.delete(_CRED_SERVICE, _CRED_ACCOUNT)  # credential SECOND (absent -> no-op)

    async def set_op() -> None:
        await delete_holds_conn.wait()  # DELETE takes the connection-row lock first
        async with store.transaction():
            await store.mutate(_CONN_SERVICE, _CONN_ACCOUNT, _reactivate)  # blocks, then conflicts
            await store.write(_CRED_SERVICE, _CRED_ACCOUNT, "api-key-blob")

    results = await asyncio.gather(delete_op(), set_op(), return_exceptions=True)

    assert results[0] is None, f"delete unexpectedly failed: {results[0]!r}"
    assert isinstance(results[1], _ReactivateConflict), (
        f"set must abort rather than reactivate, got {results[1]!r}"
    )
    assert _status_of(store.committed.get((_CONN_SERVICE, _CONN_ACCOUNT))) == "revoked"
    assert store.committed.get((_CRED_SERVICE, _CRED_ACCOUNT)) is None  # no orphan credential


@pytest.mark.asyncio
async def test_conn_delete_wins_over_set_when_set_commits_first_credential_absent() -> None:
    """Credential row ABSENT, the API-key ``set`` commits first.

    Production ordering under test (connection-row transition FIRST, credential SECOND):

      1. SET acquires the connection-row lock (``reactivate`` -> active), writes (INSERTs) its
         credential blob, and COMMITS.
      2. DELETE was blocked on the connection-row lock; it now marks the connection revoked and
         — because SET's credential blob is now COMMITTED and visible — deletes it too, then
         COMMITS.

    Final state: connection revoked, credential gone — the later delete still cleans up SET's
    blob, so no orphan survives. This is the commit order the credential-first ordering handles
    correctly only when the blob already exists; here it is created mid-race.
    """
    store = MvccRowStore()
    await _seed_connection_without_credential(store)
    set_holds_conn = asyncio.Event()

    async def set_op() -> None:
        async with store.transaction():
            await store.mutate(_CONN_SERVICE, _CONN_ACCOUNT, _reactivate)  # conn-row CAS FIRST
            set_holds_conn.set()
            await store.write(_CRED_SERVICE, _CRED_ACCOUNT, "api-key-blob")  # credential SECOND

    async def delete_op() -> None:
        await set_holds_conn.wait()  # SET takes the connection-row lock first
        async with store.transaction():
            # mark_revoked blocks until SET commits, then revokes by PK.
            await store.write(_CONN_SERVICE, _CONN_ACCOUNT, json.dumps({"status": "revoked"}))
            await store.delete(_CRED_SERVICE, _CRED_ACCOUNT)  # SET's blob now visible -> deleted

    results = await asyncio.gather(set_op(), delete_op(), return_exceptions=True)

    assert results[0] is None, f"set unexpectedly failed: {results[0]!r}"
    assert results[1] is None, f"delete unexpectedly failed: {results[1]!r}"
    assert _status_of(store.committed.get((_CONN_SERVICE, _CONN_ACCOUNT))) == "revoked"
    assert store.committed.get((_CRED_SERVICE, _CRED_ACCOUNT)) is None  # no orphan credential


def test_connection_delete_wins_over_stale_patch(
    authenticated_client,
    monkeypatch,
) -> None:
    """PATCH must condition its label update on the connection remaining active."""
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    connection_id = uuid4()

    async def _seed_active_connection() -> None:
        store = OAuthConnectionStore()
        connection = await store.create_pending(
            account_id=account_id,
            provider="anthropic",
            label="before-patch",
            connection_id=connection_id,
        )
        await store.complete(connection, label="before-patch", identity=None)

    authenticated_client.portal.call(_seed_active_connection)
    get_connection = OAuthConnectionStore.get
    patch_read = threading.Event()
    release_patch = threading.Event()
    get_count = 0
    get_count_lock = threading.Lock()

    async def _stall_first_get(self, *args, **kwargs):
        nonlocal get_count
        connection = await get_connection(self, *args, **kwargs)
        with get_count_lock:
            get_count += 1
            call_number = get_count
        if call_number == 1:
            patch_read.set()
            if not await asyncio.to_thread(release_patch.wait, 5):
                raise TimeoutError("connection PATCH was not released")
        return connection

    monkeypatch.setattr(OAuthConnectionStore, "get", _stall_first_get)
    with ThreadPoolExecutor(max_workers=1) as executor:
        patch = executor.submit(
            authenticated_client.patch,
            f"/v1/oauth/connections/{connection_id}",
            json={"label": "after-patch"},
        )
        assert patch_read.wait(5), "PATCH never read its stale connection snapshot"
        deleted = authenticated_client.delete(f"/v1/oauth/connections/{connection_id}")
        release_patch.set()
        patched = patch.result(timeout=5)

    assert deleted.status_code == 204
    assert patched.status_code == 409
    after = authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()
    assert after["status"] == "revoked"


def test_connection_delete_wins_over_stale_active_error(
    authenticated_client,
) -> None:
    """An established request failure cannot rewrite a revoked row to ERROR."""
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    connection_id = uuid4()

    async def _seed_and_read_stale():
        store = OAuthConnectionStore()
        connection = await store.create_api_key(
            account_id=account_id,
            provider="anthropic",
            label="stale-error",
            connection_id=connection_id,
        )
        return store, connection

    store, stale = authenticated_client.portal.call(_seed_and_read_stale)
    deleted = authenticated_client.delete(f"/v1/oauth/connections/{connection_id}")
    marked = authenticated_client.portal.call(store.mark_error, stale, "credential rejected")

    assert deleted.status_code == 204
    assert marked is None
    assert authenticated_client.get(f"/v1/oauth/connections/{connection_id}").json()["status"] == (
        "revoked"
    )

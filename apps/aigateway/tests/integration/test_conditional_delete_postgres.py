"""PostgreSQL races of a conditional Connection delete (OME-1138 close-out, L7c).

# FEATURE: spec `docs/spec/2026-10-29-local-engine-effective-row.md` §2a — a delete with
# `?expected_status=` re-checks the row inside its own transaction, after its pair claim. A sign-in
# that finishes while the delete is in flight is never removed by it.
# INVARIANT: the callback and the delete claim the pair marker first, so one of them commits
# first. The delete that comes second refuses (409) unless the row still has the expected status
# and is not the pair's effective row. The callback that comes second loses, as before.
# WHY bound: fixtures and helpers come from the S2'c module and the native repair lane; run with
# `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import test_native_repair_postgres as repair
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

from aigateway.routes import oauth_connections

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

LABEL = "screamingface"


def _no_effective_row(client: TestClient, account_id: str) -> None:
    """A pair with no marker and no row: the replacement becomes its only Connection."""
    backing._call(client, backing._reset_pair, backing._app(client), account_id)


def _broken_effective_row(client: TestClient, account_id: str) -> None:
    """A migrated pair whose effective row is broken: the replacement becomes effective."""
    repair._broken_pair(client, account_id, backing._fresh_name())


PAIRS: dict[str, Callable[[TestClient, str], None]] = {
    "no-effective-row": _no_effective_row,
    "broken-effective-row": _broken_effective_row,
}


def _conditional_delete(client: TestClient, connection_id: str) -> Any:
    return client.delete(
        f"/v1/oauth/connections/{connection_id}", params={"expected_status": "pending"}
    )


def _hold_the_delete(
    monkeypatch: pytest.MonkeyPatch, *, after_claim: bool
) -> tuple[threading.Event, threading.Event]:
    """Pause the delete just before (or just after) its pair claim, inside its transaction."""
    held, release = threading.Event(), threading.Event()
    claim = oauth_connections.claim_for_connection

    async def held_claim(connection: Any) -> None:
        if after_claim:
            await claim(connection)
        held.set()
        if not await asyncio.to_thread(release.wait, 20):
            raise TimeoutError("the delete was not released")
        if not after_claim:
            await claim(connection)

    monkeypatch.setattr(oauth_connections, "claim_for_connection", held_claim)
    return held, release


@pytest.mark.parametrize("pair", list(PAIRS))
def test_a_sign_in_that_finishes_inside_a_conditional_delete_keeps_its_row_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch, pair: str
) -> None:
    # WHY hold before the claim: the delete has read the row as `pending`; the callback then
    # commits in full, so the delete claims the pair at the callback's generation and the marker
    # fence no longer stops it. Only the re-check inside its transaction can.
    account_id = backing._account_id(pg_client)
    PAIRS[pair](pg_client, account_id)
    flow = repair._start(pg_client, LABEL, "new-tok")
    replacement = flow["connection_id"]
    held, release = _hold_the_delete(monkeypatch, after_claim=False)

    with ThreadPoolExecutor(max_workers=1) as executor:
        deleting = executor.submit(_conditional_delete, pg_client, replacement)
        assert held.wait(20), "the delete never read the row"
        completed = repair._callback(pg_client, flow["state"])
        release.set()
        deleted = deleting.result(timeout=30)

    assert completed.status_code == 200, completed.text
    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["detail"]["code"] == "connection_conflict"
    assert backing._connection(pg_client, account_id, replacement).status == "active"
    assert repair._access_token(pg_client, account_id, replacement) == "new-tok"
    if pair == "broken-effective-row":
        marker = backing._marker(pg_client, account_id)
        assert str(marker.effective_connection_id) == replacement


@pytest.mark.parametrize("pair", list(PAIRS))
def test_a_conditional_delete_that_claims_first_makes_the_sign_in_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch, pair: str
) -> None:
    account_id = backing._account_id(pg_client)
    PAIRS[pair](pg_client, account_id)
    flow = repair._start(pg_client, LABEL, "new-tok")
    replacement = flow["connection_id"]
    before = backing._marker(pg_client, account_id)
    held, release = _hold_the_delete(monkeypatch, after_claim=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(_conditional_delete, pg_client, replacement)
        assert held.wait(20), "the delete never claimed the pair"
        completing = executor.submit(repair._callback, pg_client, flow["state"])
        deadline = time.monotonic() + 10
        while backing._call(pg_client, repair._lock_waiters) < 1:
            assert time.monotonic() < deadline, "the callback never waited on the delete"
            time.sleep(0.05)
        release.set()
        deleted = deleting.result(timeout=30)
        completed = completing.result(timeout=30)

    assert deleted.status_code == 204, deleted.text
    assert completed.status_code == 409, completed.text
    assert backing._connection(pg_client, account_id, replacement).status == "revoked"
    assert repair._access_token(pg_client, account_id, replacement) is None
    after = backing._marker(pg_client, account_id)
    assert after.effective_connection_id == before.effective_connection_id

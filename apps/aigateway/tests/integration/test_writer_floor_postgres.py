"""PostgreSQL races of the G0 writer floor on a legacy-owned pair (OME-1497).

# FEATURE: OME-1138 D18, G0 (contract §5.3) — on PostgreSQL (READ COMMITTED) the pair claim is the
# fence for `none` pairs too: the first marker is an INSERT whose unique-key loser rolls back, a
# later claim is an `UPDATE … WHERE generation = <observed>` whose loser re-evaluates to zero rows.
# INVARIANT: a legacy writer and a native writer racing on one pair never both commit, and the
# loser leaves no document, row, blob or marker behind.
# AIDEV-NOTE: fixtures and helpers are bound from the S2'c module; run with `AIGW_TEST_PG=1`.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import pytest
import test_provider_access_backing_postgres as backing
from fastapi.testclient import TestClient

from aigateway.core.oauth.store import OAuthConnectionStore

pytestmark = pytest.mark.needs_postgres

postgres_database_url = backing.postgres_database_url
pg_client = backing.pg_client

PROVIDER = backing.PROVIDER
KEY = "sk-ant-api03-postgres-floor-key-4321"
NATIVE_KEY = "sk-ant-api03-postgres-floor-native-8765"


def _legacy_put(client: TestClient, name: str) -> Any:
    return client.put(f"/v1/auth/{PROVIDER}/profiles/{name}/api-key", json={"api_key": KEY})


def _native_create(client: TestClient, label: str) -> Any:
    return client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": PROVIDER, "label": label, "api_key": NATIVE_KEY},
    )


def _live_rows(client: TestClient, account_id: str) -> list[Any]:
    return backing._call(client, OAuthConnectionStore().list, account_id, provider=PROVIDER)


def _race(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, first: Any, second: Any
) -> tuple[Any, Any]:
    """Run `first` until it holds the marker, start `second`, then let `first` commit."""
    hold = backing._MarkerHold(monkeypatch, holds=lambda index, _kw: index == 0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        winning = executor.submit(first)
        assert hold.held.wait(20), "the first writer never claimed the pair"
        losing = executor.submit(second)
        assert hold.attempted.wait(20), "the second writer never reached its claim"
        hold.release.set()
        return winning.result(timeout=30), losing.result(timeout=30)


@pytest.mark.parametrize("legacy_first", [True, False], ids=["legacy-first", "native-first"])
def test_a_legacy_and_a_native_writer_on_one_unmarked_pair_commit_exactly_one_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch, legacy_first: bool
) -> None:
    account_id = backing._account_id(pg_client)
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    name = backing._fresh_name()
    legacy = partial(_legacy_put, pg_client, name)
    native = partial(_native_create, pg_client, name)
    first, second = (legacy, native) if legacy_first else (native, legacy)

    won, lost = _race(pg_client, monkeypatch, first, second)

    assert won.status_code in (200, 201), won.text
    assert lost.status_code == 409, lost.text
    pair = backing._marker(pg_client, account_id)
    assert (pair.migration_state, pair.generation) == ("none", 1)
    if legacy_first:
        assert lost.json()["detail"]["code"] == "connection_conflict"
        assert _live_rows(pg_client, account_id) == []
        assert backing._document(pg_client, account_id, name) is not None
    else:
        assert lost.json()["detail"]["code"] == "profile_conflict"
        assert [row.label for row in _live_rows(pg_client, account_id)] == [name]
        assert backing._document(pg_client, account_id, name) is None
        assert backing._profile_blob(pg_client, account_id, name) is None


def test_two_first_marker_writers_commit_exactly_one_and_leave_no_orphan_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    first_name, second_name = backing._fresh_name(), backing._fresh_name()

    won, lost = _race(
        pg_client,
        monkeypatch,
        partial(_legacy_put, pg_client, first_name),
        partial(_legacy_put, pg_client, second_name),
    )

    assert won.status_code == 200, won.text
    assert lost.status_code == 409, lost.text
    assert lost.json()["detail"] == {
        "code": "profile_conflict",
        "provider": PROVIDER,
        "profile": second_name,
    }
    assert backing._marker(pg_client, account_id).generation == 1
    assert backing._document(pg_client, account_id, second_name) is None
    assert backing._profile_blob(pg_client, account_id, second_name) is None
    blob = backing._profile_blob(pg_client, account_id, first_name)
    assert blob is not None and json.loads(blob)["api_key"] == KEY


def test_a_native_key_replacement_holding_a_none_pair_makes_the_legacy_put_lose_on_postgres(
    pg_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account_id = backing._account_id(pg_client)
    backing._call(pg_client, backing._reset_pair, backing._app(pg_client), account_id)
    label, name = backing._fresh_name(), backing._fresh_name()
    created = _native_create(pg_client, label)
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]

    replaced, put = _race(
        pg_client,
        monkeypatch,
        partial(
            pg_client.put, f"/v1/oauth/connections/{connection_id}/api-key", json={"api_key": KEY}
        ),
        partial(_legacy_put, pg_client, name),
    )

    assert replaced.status_code == 200, replaced.text
    assert put.status_code == 409, put.text
    assert put.json()["detail"]["code"] == "profile_conflict"
    pair = backing._marker(pg_client, account_id)
    assert (pair.migration_state, pair.generation) == ("none", 2)
    assert backing._document(pg_client, account_id, name) is None
    assert backing._profile_blob(pg_client, account_id, name) is None

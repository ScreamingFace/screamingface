"""``GET /v1/cache/entries``: the community cache, one NDJSON page at a time (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted cache — optionally only
my models — and load each page into my local gateway, resuming where I stopped.

Pinned here: the route demands an authenticated caller, any account rather than an admin; a page
is a header line (schema, revisions, and ``remaining`` only when asked), one line per row, and a
trailer line carrying the next cursor; the cursor walks every eligible row exactly once; the
model filter and ``limit`` reach the query; bad parameters are 422; the body is gzip'd when the
client accepts it; and nothing on the route may be cached by an intermediary.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.core.request_cache.community_pages import PAGE_FIELDS, PAGE_SCHEMA, PageCursor
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.revisions import active_cache_revisions

_URL = "/v1/cache/entries"
_T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _seed(client: TestClient, *rows: tuple[str, str, int]) -> None:
    """Insert ``(key, model, seconds after _T0)`` rows on the app's own event loop."""

    async def _insert() -> None:
        for key, model, seconds in rows:
            entry = await RequestCacheEntry.create(
                key_hash=key.ljust(64, "0"),
                prompt_hash="p" * 64,
                provider="openrouter",
                model=model,
                response_json='{"choices": []}',
                response_size_bytes=15,
            )
            await RequestCacheEntry.filter(id=entry.id).update(
                updated_at=_T0 + timedelta(seconds=seconds)
            )

    # The portal exists only while the TestClient's lifespan is running, as it is here.
    assert client.portal is not None
    client.portal.call(_insert)


def _lines(response: httpx.Response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines()]


# --- auth ----------------------------------------------------------------------------------------


def test_an_unauthenticated_caller_is_refused(client: TestClient) -> None:
    assert client.get(_URL).status_code == 401


def test_any_signed_in_account_may_read_not_only_admins(
    client: TestClient, provisioned_user_factory
) -> None:
    provisioned_user_factory("reader")
    token = client.post(
        "/v1/auth/login", json={"username": "reader", "password": "test-user-password"}
    ).json()["token"]

    resp = client.get(_URL, headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200


# --- the page ------------------------------------------------------------------------------------


def test_a_page_is_a_header_rows_and_a_trailer(authenticated_client: TestClient) -> None:
    _seed(authenticated_client, ("a", "m1", 0), ("b", "m1", 1))

    resp = authenticated_client.get(_URL)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert resp.headers["cache-control"] == "private, no-store"
    header, *rows, trailer = _lines(resp)
    assert header == {"schema": PAGE_SCHEMA, "revisions": active_cache_revisions()}
    assert [row["key_hash"][0] for row in rows] == ["a", "b"]
    assert all(tuple(row) == PAGE_FIELDS for row in rows)
    assert rows[0]["updated_at"] == _T0.isoformat()
    assert trailer == {"next": None}


def test_remaining_is_reported_only_when_asked(authenticated_client: TestClient) -> None:
    _seed(authenticated_client, ("a", "m1", 0), ("b", "m1", 1), ("c", "m2", 2))
    cursor = PageCursor(updated_at=_T0, key_hash="a".ljust(64, "0")).encode()

    plain = _lines(authenticated_client.get(_URL))[0]
    fresh = _lines(authenticated_client.get(_URL, params={"count": "true"}))[0]
    resumed = _lines(authenticated_client.get(_URL, params={"count": "true", "after": cursor}))[0]
    filtered = _lines(authenticated_client.get(_URL, params={"count": "true", "model": "m1"}))[0]

    assert "remaining" not in plain
    assert fresh["remaining"] == 3
    assert resumed["remaining"] == 2
    assert filtered["remaining"] == 2


def test_following_next_walks_every_row_once(authenticated_client: TestClient) -> None:
    _seed(authenticated_client, *((f"{i:02x}", "m1", i // 3) for i in range(11)))

    keys: list[str] = []
    params: dict[str, str] = {"limit": "4"}
    while True:
        _, *rows, trailer = _lines(authenticated_client.get(_URL, params=params))
        keys.extend(row["key_hash"] for row in rows)
        if trailer["next"] is None:
            break
        params = {"limit": "4", "after": trailer["next"]}

    assert sorted(keys) == sorted(f"{i:02x}".ljust(64, "0") for i in range(11))
    assert len(keys) == len(set(keys))


def test_repeated_model_values_all_reach_the_query(authenticated_client: TestClient) -> None:
    _seed(authenticated_client, ("a", "m1", 0), ("b", "m2", 1), ("c", "m3", 2))

    _, *rows, _ = _lines(authenticated_client.get(_URL, params=[("model", "m1"), ("model", "m3")]))

    assert [row["key_hash"][0] for row in rows] == ["a", "c"]


def test_limit_defaults_to_the_page_cap(authenticated_client: TestClient) -> None:
    _seed(authenticated_client, ("a", "m1", 0), ("b", "m1", 1))

    _, *rows, trailer = _lines(authenticated_client.get(_URL, params={"limit": "1"}))
    assert len(rows) == 1
    assert trailer["next"] is not None

    _, *rows, trailer = _lines(authenticated_client.get(_URL))
    assert len(rows) == 2
    assert trailer["next"] is None


# --- refusals ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "5001"},
        {"after": "not-a-cursor"},
        {"model": ""},
        {"model": "m" * 256},
    ],
)
def test_bad_parameters_are_422(authenticated_client: TestClient, params: dict[str, str]) -> None:
    assert authenticated_client.get(_URL, params=params).status_code == 422


# --- transport -----------------------------------------------------------------------------------


def test_the_body_is_gzipped_when_accepted_and_plain_otherwise(
    authenticated_client: TestClient,
) -> None:
    _seed(authenticated_client, ("a", "m1", 0))

    with authenticated_client.stream("GET", _URL, headers={"Accept-Encoding": "gzip"}) as zipped:
        raw = b"".join(zipped.iter_raw())
    plain = authenticated_client.get(_URL, headers={"Accept-Encoding": "identity"})

    assert zipped.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in zipped.headers["vary"].lower()
    assert gzip.decompress(raw).decode() == plain.text
    assert "content-encoding" not in plain.headers

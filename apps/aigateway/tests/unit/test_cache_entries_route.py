"""``GET /v1/cache/entries``: the community cache, one NDJSON page at a time (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a signed-in user of a local engine, I page through the hosted cache — optionally only
my models — and load each page into my local gateway, resuming where I stopped.

Pinned here: the route demands an authenticated caller, any account rather than an admin; a page
is a header line (schema, revisions, and ``remaining`` only when asked), one line per row, and a
trailer line carrying the next cursor; the cursor walks every eligible row exactly once; the
model filter and ``limit`` reach the query; bad parameters are 422; the body is gzip'd when the
client accepts it; nothing on the route may be cached by an intermediary; and encoding rows and
gzip run off the event loop.
"""

from __future__ import annotations

import gzip
import json
import threading
import types
import zlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from aigateway.core.request_cache.community_pages import PAGE_FIELDS, PAGE_SCHEMA, PageCursor
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.revisions import active_cache_revisions
from aigateway.routes import cache_entries

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


def test_row_encoding_and_gzip_run_off_the_event_loop(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: a page's per-batch work (JSON-encoding rows, gzip) never runs on the event
    # loop. gzip is the route's largest cost (~57 ms per 1,000 rows), and on the loop it would
    # stall every other request on the pod, cache hits included, for each batch.
    _seed(authenticated_client, ("a", "m1", 0), ("b", "m1", 1))
    assert authenticated_client.portal is not None
    loop_thread = authenticated_client.portal.call(threading.get_ident)
    threads: list[int] = []

    real_wire = cache_entries._wire

    def wire(row: dict) -> dict:
        threads.append(threading.get_ident())
        return real_wire(row)

    class Compressor:
        def __init__(self) -> None:
            self._inner = zlib.compressobj(wbits=31)

        def compress(self, data: bytes) -> bytes:
            threads.append(threading.get_ident())
            return self._inner.compress(data)

        def flush(self) -> bytes:
            threads.append(threading.get_ident())
            return self._inner.flush()

    monkeypatch.setattr(cache_entries, "_wire", wire)
    monkeypatch.setattr(
        cache_entries, "zlib", types.SimpleNamespace(compressobj=lambda **_: Compressor())
    )

    with authenticated_client.stream("GET", _URL, headers={"Accept-Encoding": "gzip"}) as zipped:
        raw = b"".join(zipped.iter_raw())

    assert [
        json.loads(line)["key_hash"][0] for line in gzip.decompress(raw).splitlines()[1:-1]
    ] == [
        "a",
        "b",
    ]
    assert threads
    assert loop_thread not in threads


# --- Accept-Encoding (PR #1433 review, finding 3) ------------------------------------------------


@pytest.mark.parametrize(
    ("accept", "gzip_ok"),
    [
        ("gzip", True),
        ("GZip", True),
        ("br, gzip;q=0.5", True),
        ("gzip;q=0", False),
        ("br, gzip;q=0", False),
        ("gzip;q=0.000", False),
        ("*", True),
        ("*;q=0", False),
        ("gzip;q=0, *", False),
        ("identity", False),
        ("", False),
        # A weight outside RFC 9110's qvalue grammar refuses the coding.
        ("gzip;q=2", False),
        ("gzip;q=1.1", False),
        ("gzip;q=+0.5", False),
        ("gzip;q=1e-1", False),
        ("gzip;q=0.0001", False),
        ("gzip;q=1.000", True),
    ],
)
def test_gzip_is_negotiated_by_rfc_9110_rules(accept: str, gzip_ok: bool) -> None:
    request = types.SimpleNamespace(headers={"accept-encoding": accept})

    assert (cache_entries._coding(request) == "gzip") is gzip_ok  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("accept", "coding"),
    [
        ("", "identity"),
        ("identity", "identity"),
        ("br", "identity"),
        ("gzip;q=0", "identity"),
        ("identity;q=0", None),
        ("gzip;q=0, identity;q=0", None),
        ("*;q=0", None),
        ("*;q=0, identity", "identity"),
        ("identity;q=0, gzip", "gzip"),
    ],
)
def test_identity_is_sent_unless_refused(accept: str, coding: str | None) -> None:
    request = types.SimpleNamespace(headers={"accept-encoding": accept})

    assert cache_entries._coding(request) == coding  # type: ignore[arg-type]


def test_a_caller_refusing_every_coding_gets_a_private_406(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get(_URL, headers={"Accept-Encoding": "gzip;q=0, identity;q=0"})

    assert response.status_code == 406
    assert response.headers["cache-control"] == "private, no-store"


# --- the last page (PR #1433 review, non-blocking) -----------------------------------------------


def test_a_last_page_of_exactly_limit_rows_says_so(authenticated_client: TestClient) -> None:
    # WHY: `next` must be null when no row follows, or the client asks for an empty page.
    _seed(authenticated_client, ("a", "m1", 0), ("b", "m1", 1))

    _, *rows, trailer = _lines(
        authenticated_client.get(
            _URL, params={"limit": "2"}, headers={"Accept-Encoding": "identity"}
        )
    )

    assert len(rows) == 2
    assert trailer == {"next": None}

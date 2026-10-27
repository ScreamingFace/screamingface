"""The shared chat cache for configured endpoints, through the real routes and the real store.

# FEATURE: hosted BYOM Unit 1 — one stored answer per identical chat to one configured target,
# shared by every account, as for bundled providers.
# STORY: as a researcher, I re-run a benchmark another account already ran on the same endpoint
# and get its stored answers with no new upstream call, whether or not I hold a grant or a key.
# INVARIANT: a hit needs an enabled endpoint and a declared alias, and nothing else; a miss or a
# bypass still needs the grant and the stored key before any upstream I/O.
# INVARIANT (owner decision, 2026-10-27): `/v1/cache/entries` lists an endpoint's published rows,
# with their provider and model IDs, stored answers and metadata, to every signed-in account. The
# grant filters the working catalog and new upstream calls, not published cache entries.
# WHY restarts on the same stores: `enabled`, grants and aliases are read once at startup, and the
# stored rows live in the database, so a config change is a restart that keeps every row.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import Harness, chat_body, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    ALIAS,
    CHAT_PATH,
    ENDPOINT_A,
    ENDPOINT_B,
    ORIGIN_A,
    ORIGIN_B,
    chat_target,
    document,
    endpoint,
    two_endpoint_document,
)

CACHE = "X-AIGW-Cache"
UNREGISTERED = "byom_" + "c" * 32
KEY = {ENDPOINT_A: "sk-alice-on-a-cache-0001", ENDPOINT_B: "sk-alice-on-b-cache-0001"}
CALL = {
    provider: (origin + CHAT_PATH, f"Bearer {KEY[provider]}")
    for provider, origin in (
        (ENDPOINT_A, ORIGIN_A),
        (ENDPOINT_B, ORIGIN_B),
    )
}


@pytest.fixture(autouse=True)
def _cache_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


def _post(client: TestClient, account: str, body: dict[str, Any]) -> httpx.Response:
    return client.post("/v1/chat/completions", json=body, headers=tenant_headers(account))


def _fill(byom: Harness, doc: dict[str, Any], *bodies: dict[str, Any]) -> list[httpx.Response]:
    """Account A attaches its keys and sends ``bodies`` once each; the upstream log is cleared."""
    with byom.start(doc) as client:
        for provider in (ENDPOINT_A, ENDPOINT_B):
            assert put_key(client, ACCOUNT_A, provider, KEY[provider]).status_code == 200
        byom.upstream.calls.clear()
        filled = [_post(client, ACCOUNT_A, body) for body in bodies]
    assert [r.headers.get(CACHE) for r in filled] == ["miss"] * len(bodies)
    byom.upstream.calls.clear()
    byom.upstream.bodies.clear()
    return filled


def _calls(byom: Harness) -> list[tuple[str, str]]:
    return [(call.url, call.bearer) for call in byom.upstream.calls]


def _cache_status(response: httpx.Response) -> str:
    return response.json()["_aigw"]["usage_accounting"]["cache"]["status"]


# Per-request correlation ids differ on every response, whatever the provider.
_PER_REQUEST = frozenset({"trace_id", "gateway_call_id"})


def _comparable(value: Any, provider: str) -> Any:
    if isinstance(value, dict):
        return {k: _comparable(v, provider) for k, v in value.items() if k not in _PER_REQUEST}
    return value.replace(provider, "<provider>") if isinstance(value, str) else value


def _refusal(response: httpx.Response, provider: str) -> tuple[int, Any]:
    return response.status_code, _comparable(response.json(), provider)


def test_one_account_fills_and_every_account_hits_with_one_upstream_call(byom: Harness) -> None:
    on_a, on_b = chat_body(ENDPOINT_A), chat_body(ENDPOINT_B)

    with byom.start(two_endpoint_document()) as client:
        for provider in (ENDPOINT_A, ENDPOINT_B):
            assert put_key(client, ACCOUNT_A, provider, KEY[provider]).status_code == 200
        byom.upstream.calls.clear()
        filled_a = _post(client, ACCOUNT_A, on_a)
        # Account B is granted endpoint A but holds no key for it.
        granted = _post(client, ACCOUNT_B, on_a)
        filled_b = _post(client, ACCOUNT_A, on_b)
        # Account B holds neither a grant nor a key for endpoint B.
        ungranted = _post(client, ACCOUNT_B, on_b)

    assert [r.headers[CACHE] for r in (filled_a, granted, filled_b, ungranted)] == [
        "miss",
        "hit",
        "miss",
        "hit",
    ]
    assert granted.json()["choices"] == filled_a.json()["choices"]
    assert ungranted.json()["choices"] == filled_b.json()["choices"]
    # INVARIANT: both endpoints declare the same alias and upstream model, and still never share
    # a row: the second endpoint's first chat is a miss that reaches its own origin.
    assert _calls(byom) == [CALL[ENDPOINT_A], CALL[ENDPOINT_B]]
    assert byom.stored_key(ACCOUNT_B, ENDPOINT_A) is None


def test_max_tokens_is_part_of_the_key(byom: Harness) -> None:
    plain = chat_body(ENDPOINT_A)
    five, six = {**plain, "max_tokens": 5}, {**plain, "max_tokens": 6}

    with byom.start(two_endpoint_document()) as client:
        assert put_key(client, ACCOUNT_A, ENDPOINT_A, KEY[ENDPOINT_A]).status_code == 200
        byom.upstream.calls.clear()
        byom.upstream.bodies.clear()
        sent = [
            _post(client, ACCOUNT_A, plain),
            _post(client, ACCOUNT_A, five),
            _post(client, ACCOUNT_B, five),
            _post(client, ACCOUNT_A, six),
            _post(client, ACCOUNT_B, plain),
        ]

    assert [r.headers[CACHE] for r in sent] == ["miss", "miss", "hit", "miss", "hit"]
    assert [body.get("max_tokens") for body in byom.upstream.bodies] == [None, 5, 6]


def test_a_removed_alias_bypasses_the_cache_and_sends_nothing(byom: Harness) -> None:
    body = chat_body(ENDPOINT_A)
    _fill(byom, two_endpoint_document(), body)
    renamed = document(
        endpoint(
            ENDPOINT_A,
            accounts=(ACCOUNT_A, ACCOUNT_B),
            targets=[chat_target(alias="model_v2")],
            validation_target="model_v2",
        )
    )

    with byom.start(renamed) as client:
        keyed, keyless = (_post(client, account, body) for account in (ACCOUNT_A, ACCOUNT_B))

    # INVARIANT: the stored row is not served to anyone, and nothing reaches the origin.
    assert [_cache_status(r) for r in (keyed, keyless)] == ["bypass", "bypass"]
    # WHY two refusals: a bypass resolves the caller's key before the alias check, so the account
    # holding a key learns the alias is gone and the account without one is refused for that.
    assert (keyed.status_code, keyed.json()["detail"]["code"]) == (400, "invalid_model")
    assert keyless.status_code in (404, 409), keyless.text
    assert _calls(byom) == []


def test_a_disabled_endpoint_serves_nothing_and_its_unchanged_return_serves_the_row(
    byom: Harness,
) -> None:
    body = chat_body(ENDPOINT_B)
    (filled,) = _fill(byom, two_endpoint_document(), body)
    absent = {**body, "model": body["model"].replace(ENDPOINT_B, UNREGISTERED)}

    with byom.start(two_endpoint_document(b_enabled=False)) as client:
        disabled = _post(client, ACCOUNT_A, body)
        unregistered = _post(client, ACCOUNT_A, absent)
    with byom.start(two_endpoint_document()) as client:
        granted = _post(client, ACCOUNT_A, body)
        ungranted = _post(client, ACCOUNT_B, body)

    # INVARIANT: while disabled, the stored answer is not served and the grant refuses the bypass
    # as it refuses a provider that is not registered.
    assert _cache_status(disabled) == "bypass"
    assert _refusal(disabled, ENDPOINT_B) == _refusal(unregistered, UNREGISTERED)
    # INVARIANT: disabling touched no row, so the same unchanged endpoint serves it again.
    assert (granted.headers[CACHE], ungranted.headers[CACHE]) == ("hit", "hit")
    assert granted.json()["choices"] == ungranted.json()["choices"] == filled.json()["choices"]
    assert _calls(byom) == []


def test_a_published_row_reaches_an_account_the_catalog_hides_the_endpoint_from(
    byom: Harness,
) -> None:
    (filled,) = _fill(byom, two_endpoint_document(), chat_body(ENDPOINT_B))

    # Account B holds neither a grant nor a key for endpoint B.
    with byom.start(two_endpoint_document()) as client:
        catalog = client.get("/v1/models", headers=tenant_headers(ACCOUNT_B))
        page = client.get("/v1/cache/entries", headers=tenant_headers(ACCOUNT_B))

    assert ENDPOINT_B not in {row["owned_by"] for row in catalog.json()["data"]}
    assert page.status_code == 200, page.text
    _, *rows, _ = [json.loads(line) for line in page.text.splitlines()]
    (row,) = [row for row in rows if row["provider"] == ENDPOINT_B]
    assert row["model"] == f"{ENDPOINT_B}/{ALIAS}"
    assert json.loads(row["response_json"])["choices"] == filled.json()["choices"]
    # WHY the fields and not the block: the accounting block is built for no endpoint call yet,
    # so `metadata_json` is null today; the listing still carries every cache metadata field.
    cache_fields = {"created_at", "updated_at", "expires_at", "response_size_bytes"}
    assert cache_fields | {"metadata_json"} <= row.keys()
    assert _calls(byom) == []

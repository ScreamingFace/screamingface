"""The shared chat cache answers before the grant; only a miss or a bypass needs the grant.

# FEATURE: hosted BYOM Unit 0 — the agreed contract keeps the global chat cache common to every
# account and adds no pre-cache authorization. The account grant guards NEW upstream calls: it
# is checked on a miss or a bypass, before any credential is resolved or any request is sent.
# WHY a test-only projection: it keeps this file on the ORDER of the cache stage and the grant
# check in the real chat route, against the real cache store, whatever the production projection
# (Unit 1, `test_global_cache`) keys.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .conftest import Harness, chat_body, put_key, tenant_headers
from .fixtures import (
    ACCOUNT_A,
    ACCOUNT_B,
    CHAT_PATH,
    ENDPOINT_B,
    ORIGIN_B,
    UPSTREAM_MODEL,
    two_endpoint_document,
)

ABSENT = "byom_" + "f" * 32
KEY = "sk-alice-on-b-cache-0001"
CACHE_HEADER = "X-AIGW-Cache"


def _projection(body: dict[str, Any]) -> dict[str, Any]:
    del body
    return {
        "resolved_model": UPSTREAM_MODEL,
        "provider_adapter_revision": "unit0-order-test",
        "prepared": {},
    }


def _post(client: TestClient, account: str, body: dict[str, Any]) -> httpx.Response:
    return client.post("/v1/chat/completions", json=body, headers=tenant_headers(account))


# Per-request correlation ids differ on every response, whatever the provider.
_PER_REQUEST = frozenset({"trace_id", "gateway_call_id"})


def _comparable(value: Any, provider: str) -> Any:
    if isinstance(value, dict):
        return {k: _comparable(v, provider) for k, v in value.items() if k not in _PER_REQUEST}
    return value.replace(provider, "<provider>") if isinstance(value, str) else value


def _refusal(response: httpx.Response, provider: str) -> tuple[int, Any, dict[str, str]]:
    # WHY not content-length: the bodies are compared field by field above it.
    headers = {
        k: v for k, v in response.headers.items() if k not in ("x-aigw-trace-id", "content-length")
    }
    return response.status_code, _comparable(response.json(), provider), headers


def _reported_cache_status(response: httpx.Response) -> str:
    return response.json()["_aigw"]["usage_accounting"]["cache"]["status"]


def test_an_ungranted_account_gets_a_hit_but_no_new_upstream_call(
    byom: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Endpoint B is granted to account A only; account B has neither a grant nor a key for it.
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    body = chat_body(ENDPOINT_B)
    other = {**body, "messages": [{"role": "user", "content": "a request nobody cached"}]}

    with byom.start(two_endpoint_document()) as client:
        plugin = cast(FastAPI, client.app).state.providers.get(ENDPOINT_B)
        monkeypatch.setattr(plugin, "global_cache_projection", _projection)
        assert put_key(client, ACCOUNT_A, ENDPOINT_B, KEY).status_code == 200
        byom.upstream.calls.clear()

        stored = _post(client, ACCOUNT_A, body)
        hit = _post(client, ACCOUNT_B, body)
        missed = _post(client, ACCOUNT_B, other)
        bypassed = _post(client, ACCOUNT_B, {**body, "cache": {"use-cache": False}})
        absent = _post(
            client, ACCOUNT_B, {**other, "model": other["model"].replace(ENDPOINT_B, ABSENT)}
        )

    assert (stored.status_code, stored.headers[CACHE_HEADER]) == (200, "miss")
    # INVARIANT: the hit is served to an account with no grant and no key, sending nothing new.
    assert (hit.status_code, hit.headers[CACHE_HEADER]) == (200, "hit")
    assert hit.json()["choices"] == stored.json()["choices"]
    assert [(c.url, c.bearer) for c in byom.upstream.calls] == [
        (ORIGIN_B + CHAT_PATH, f"Bearer {KEY}")
    ]
    # INVARIANT: a miss and a bypass need a new upstream call, so the grant refuses both, with
    # the status, detail and headers of a provider that does not exist.
    assert _refusal(bypassed, ENDPOINT_B) == _refusal(absent, ABSENT)
    # WHY a miss differs in ONE field: the cache stage ran for this account, as the shared-cache
    # contract requires, and the existing accounting block reports its outcome. Hiding it would
    # need a private-endpoint switch in the cache path, which the contract forbids; a hit already
    # shows that the endpoint exists.
    assert (_reported_cache_status(missed), _reported_cache_status(absent)) == ("miss", "bypass")
    missed_status, missed_body, missed_headers = _refusal(missed, ENDPOINT_B)
    missed_body["_aigw"]["usage_accounting"]["cache"]["status"] = "bypass"
    assert (missed_status, missed_body, missed_headers) == _refusal(absent, ABSENT)
    assert byom.stored_key(ACCOUNT_B, ENDPOINT_B) is None

"""OME-1323 Stage C (D2): request parameters are the caller's; a saved default never applies.

FEATURE: one globally shared exact-request cache (OME-305), keyed on the caller's hardened body.

STORY: as a caller I send every parameter I want with each request (and system instructions as
system-role messages). A historical Profile default, still stored during the compatibility
window, neither changes my request nor my cache key, and cannot refuse my request.

INVARIANT: the chat route reads no Profile before the cache and merges nothing. A request keys on
what the caller sent — so changes to the default target's historical defaults retain one row for
the same bare body, and that row is the N2 bare digest (`test_chat_global_cache_key_parity.py`).

INVARIANT: N1b is a baseline that passed before and after Stage C. Never "fix" a failure here by
bumping a cache revision — stop and ask the owner.

Retired at OME-1138 Stage E, E5c:
`test_default_target_historical_default_changes_share_one_bare_key` — a Profile default can no
longer be stored, so no default change remains to key on; successor:
`test_chat_global_cache_key_parity.py::test_the_route_builds_the_pinned_material_and_caches_it`.
Retired at OME-1138 Stage E, E5c:
`test_a_stream_on_a_profile_with_historical_defaults_carries_none_of_them` — a Profile default can
no longer be stored, so none can reach the stream; successor:
`test_chat_request_cache.py::test_stream_bypasses_cache`.
Retired at OME-1138 Stage E, E5c:
`test_an_index_unreadable_before_planning_causes_no_bypass_and_no_wrong_hit` — the Profile index it
faults no longer exists, so no pre-cache read remains to fail; successor:
`test_chat_global_cache_effective_request.py::test_a_default_target_that_cannot_authenticate_still_gets_a_hit`.
Retired at OME-1138 Stage E, E5c:
`test_an_invalid_historical_default_neither_refuses_nor_reaches_the_provider` — an invalid Profile
default can no longer be stored; successor:
`test_chat_profile_default_validation.py::test_a_caller_fault_is_reported_alone_beside_an_invalid_historical_default`.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.credential_names import credential_name_for
from aigateway.core.request_cache import RequestCacheWrite
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.codex_provider.auth import (
    credential_service_for as codex_credential_service_for,
)
from tests.unit.migrated_pair_seed import seed_migrated_pair

_CHAT_PATH = "/v1/chat/completions"
_MODEL = "anthropic/claude-haiku-4-5"
_ANTHROPIC_PLUGIN = "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin"


# --- arrangement --------------------------------------------------------------


def _token_blob() -> str:
    return json.dumps(
        {
            "access_token": "sk-ant-oat01-subscription-token",
            "refresh_token": "rt",
            "id_token": "id",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
            "token_type": "Bearer",
        }
    )


def _seed(
    client: TestClient,
    credential_blobs,
    account_id: str,
    *,
    name: str,
    provider: str = "anthropic",
) -> None:
    """The target's blob at the `name` address, beside its pair.

    WHY the pair: since OME-1209 E4a only the pair's Connection dispatches; it sits at the
    credential's name address.
    """
    service_for = (
        credential_service_for if provider == "anthropic" else codex_credential_service_for
    )
    credential_blobs.write(
        service_for(credential_name_for(account_id, name)), "default", _token_blob()
    )
    seed_migrated_pair(client, account_id, provider, name=name)


def _body(*, system: str | None = None, **extra: Any) -> dict[str, Any]:
    messages: list[dict[str, str]] = [
        {"role": "user", "content": "how many primes below one hundred?"}
    ]
    if system is not None:
        messages.insert(0, {"role": "system", "content": system})
    return {"model": _MODEL, "messages": messages, **extra}


def _system_contents(body: dict[str, Any]) -> list[str]:
    return [m["content"] for m in body.get("messages", []) if m.get("role") == "system"]


class _Dispatch:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]) -> Any:
        self.bodies.append(json.loads(json.dumps(body, default=str)))
        n = len(self.bodies)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"resp-{n}",
                "choices": [{"message": {"content": f"ANSWER-{n}"}, "finish_reason": "stop"}],
            }
        )


class _Store:
    """The frozen store contract, in memory; every lookup is logged into ``events``."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.events = events if events is not None else []

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        self.events.append("cache.get")
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> str:
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = entry.response
        return "stored"


@pytest.fixture
def cache_client(monkeypatch, client: TestClient) -> TestClient:
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


def _install(client: TestClient, store: _Store) -> _Store:
    cast(Any, client.app).state.request_cache_store = store
    return store


def _post(client: TestClient, body: dict[str, Any]):
    return client.post(_CHAT_PATH, json=body)


# --- N1b (baseline): the caller's own system messages key and dispatch -------


def test_explicit_system_messages_key_distinctly_and_dispatch_only_the_callers_own(
    credential_blobs, cache_client
) -> None:
    """GREEN before and after: the caller's own system messages key and dispatch as sent."""
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed(cache_client, credential_blobs, account_id, name="default")
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with patch(f"{_ANTHROPIC_PLUGIN}.chat_completion", new=dispatch):
        terse = _post(cache_client, _body(system="be terse"))
        verbose = _post(cache_client, _body(system="be verbose"))
        shared = _post(cache_client, _body(system="be terse"))

    assert [r.headers["X-AIGW-Cache"] for r in (terse, verbose, shared)] == ["miss", "miss", "hit"]
    assert terse.headers["X-AIGW-Cache-Key"] != verbose.headers["X-AIGW-Cache-Key"]
    assert terse.headers["X-AIGW-Cache-Key"] == shared.headers["X-AIGW-Cache-Key"]
    assert len(store.rows) == 2
    assert [_system_contents(b) for b in dispatch.bodies] == [["be terse"], ["be verbose"]]

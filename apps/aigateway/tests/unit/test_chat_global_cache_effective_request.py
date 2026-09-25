"""The global key is built from the caller's request — and nothing about the Profile.

FEATURE: one globally shared exact-request cache (OME-305). "Exact" means the request that
actually reaches the provider, which since OME-1323 (D2) is exactly what the caller sent:
request parameters are the caller's, and system instructions arrive as system-role messages.

STORY: as a caller I send every parameter I want with each request. Whichever Profile I send
it through, an identical request shares one row with every other caller who sent it — and a
Profile that cannot authenticate is still served from that row.

INVARIANT under test: Profile identity, the Profile NAME, the account, and anything a Profile
still stores (its historical defaults) are absent from the key. Transport-only fields such as
``timeout`` are dispatched but do not key.

AIDEV-NOTE: the trap this file guards is pinned by
``test_a_profile_that_cannot_authenticate_still_gets_a_hit``: the CREDENTIAL TARGET is never
resolved before the cache, because that helper raises 404/409/401 and those raises would
preempt a cache hit — destroying the inversion OME-305 exists for. Stage C (OME-1323) removed
the pre-cache Profile read entirely; do not add one back. The key parity itself is pinned by
``test_chat_global_cache_key_parity.py`` and the defaults cutover by
``test_chat_saved_defaults_are_not_merged.py``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.core.request_cache import RequestCacheWrite
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_CHAT_PATH = "/v1/chat/completions"
_MODEL = "anthropic/claude-haiku-4-5"
_PATCH_TARGET = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)

_WriteStatus = Literal["stored", "race_lost", "not_stored"]


# --- arrangement --------------------------------------------------------------


def _token_blob() -> str:
    return json.dumps(
        {
            "access_token": "sk-ant-oat01-subscription-token",
            "refresh_token": "rt",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
            "token_type": "Bearer",
        }
    )


def _seed_credential(credential_blobs, account_id: str, *, name: str) -> None:
    """Give a profile NAME a dispatchable credential.

    WHY keyed on ``credential_name_for(account_id, name)``: once the profile exists in
    the index, ``_credential_target_for_chat`` resolves the PROFILE (not a connection),
    and injection reads the per-profile credential under that name. A miss has to
    reach a real dispatch for these tests to observe the body that was sent.
    """
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, name)),
        "default",
        _token_blob(),
    )


def _seed_profile(
    credential_blobs,
    account_id: str,
    *,
    name: str,
    defaults: ProfileDefaults,
    state: ProfileState = ProfileState.AUTHENTICATED,
) -> None:
    async def _upsert() -> None:
        idx = ProfileIndexStore(credential_store=credential_blobs.store)
        await idx.upsert(
            Profile(
                id=profile_id_for(account_id, "anthropic", name),
                account_id=account_id,
                provider="anthropic",
                name=name,
                state=state,
                defaults=defaults,
            )
        )

    import asyncio

    asyncio.run(_upsert())


def _bare_body(**overrides) -> dict[str, Any]:
    """The whole point: a body that names nothing but the model and the question."""
    body = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


class _Dispatch:
    """Records every body that actually reached the provider."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body):
        # An INSTANCE patched over the method is not a descriptor, so it is called
        # with the body alone — no ``self`` from the plugin.
        self.bodies.append(json.loads(json.dumps(body, default=str)))
        from types import SimpleNamespace

        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"resp-{len(self.bodies)}",
                "choices": [
                    {
                        "message": {"content": f"ANSWER-{len(self.bodies)}"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )


class _Store:
    """The frozen store contract, in memory (mirrors test_chat_global_cache_route)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> _WriteStatus:
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = entry.response
        return "stored"


@pytest.fixture
def _cache_env(monkeypatch):
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")


@pytest.fixture
def cache_client(_cache_env, client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


def _install(client: TestClient, store: _Store) -> _Store:
    cast(Any, client.app).state.request_cache_store = store
    return store


def _post(client: TestClient, body: dict[str, Any], *, profile: str):
    return client.post(_CHAT_PATH, json=body, headers={"X-Profile": profile})


def _system_contents(body: dict[str, Any]) -> list[str]:
    return [m["content"] for m in body.get("messages", []) if m.get("role") == "system"]


# --- the trap: a profile that cannot authenticate is still served -------------


@pytest.mark.parametrize(
    ("profile_name", "state"),
    [
        ("ghost", None),
        ("waiting", ProfileState.PENDING),
        ("broken", ProfileState.ERROR),
    ],
    ids=["absent", "pending", "errored"],
)
def test_a_profile_that_cannot_authenticate_still_gets_a_hit(
    credential_blobs, cache_client, profile_name: str, state: ProfileState | None
) -> None:
    """REGRESSION GUARD: the credential target is never resolved before the cache.

    ``_credential_target_for_chat`` raises 404 for an absent profile, 409 for a PENDING
    one and 401 for an ERRORED one. Hoisting it ahead of the cache lookup would let all
    three PREEMPT a cache hit, and a caller who is served today would start getting an
    error. Stage C (OME-1323) leaves no pre-cache Profile read at all, so nothing ahead of
    the lookup can refuse a request the cache can serve.

    The three cases are served here WITHOUT any credential of their own: the row was
    filled by a different profile entirely.
    """
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed_credential(credential_blobs, account_id, name="plain")
    _seed_profile(credential_blobs, account_id, name="plain", defaults=ProfileDefaults())
    if state is not None:
        _seed_profile(
            credential_blobs,
            account_id,
            name=profile_name,
            defaults=ProfileDefaults(),
            state=state,
        )
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with patch(_PATCH_TARGET, new=dispatch):
        filled = _post(cache_client, _bare_body(), profile="plain")
        served = _post(cache_client, _bare_body(), profile=profile_name)

    assert filled.headers["X-AIGW-Cache"] == "miss"
    assert served.status_code == 200, served.text
    assert served.headers["X-AIGW-Cache"] == "hit"
    assert served.json()["choices"][0]["message"]["content"] == "ANSWER-1"
    assert len(store.rows) == 1
    assert len(dispatch.bodies) == 1


# --- transport-only fields stay out of the key -------------------------------


def test_a_caller_timeout_changes_no_key_and_causes_no_bypass(
    credential_blobs, cache_client
) -> None:
    """A caller's ``timeout`` is transport rather than content, and the key IGNORES it.

    ``timeout`` is in ``EXCLUDED_TRANSPORT_FIELDS``, so the key skips it with a
    ``continue`` instead of bypassing on it. Two callers who differ only in timeout are
    asking the same question and must share the answer.

    INVARIANT: the "zero ``transport_only`` cache dispositions" property still holds —
    nothing was added to the parameter contract to make this pass.
    """
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed_credential(credential_blobs, account_id, name="plain")
    _seed_credential(credential_blobs, account_id, name="slow")
    _seed_profile(credential_blobs, account_id, name="plain", defaults=ProfileDefaults())
    _seed_profile(credential_blobs, account_id, name="slow", defaults=ProfileDefaults())
    store = _install(cache_client, _Store())
    dispatch = _Dispatch()

    with patch(_PATCH_TARGET, new=dispatch):
        first = _post(cache_client, _bare_body(), profile="plain")
        second = _post(cache_client, _bare_body(timeout=9.0), profile="slow")

    assert first.headers["X-AIGW-Cache"] == "miss"
    assert second.headers["X-AIGW-Cache"] == "hit"
    assert second.headers["X-AIGW-Cache-Reason"] == ""
    assert first.headers["X-AIGW-Cache-Key"] == second.headers["X-AIGW-Cache-Key"]
    assert len(store.rows) == 1


def test_a_caller_timeout_still_reaches_the_provider_on_a_miss(
    credential_blobs, cache_client
) -> None:
    """Excluded from the KEY is not excluded from the REQUEST.

    A field the key ignores must still be dispatched, or "ignored" would quietly mean
    "dropped" — and the caller's timeout would stop applying.
    """
    account_id = cache_client.get("/v1/auth/me").json()["id"]
    _seed_credential(credential_blobs, account_id, name="slow")
    _seed_profile(credential_blobs, account_id, name="slow", defaults=ProfileDefaults())
    _install(cache_client, _Store())
    dispatch = _Dispatch()

    with patch(_PATCH_TARGET, new=dispatch):
        response = _post(cache_client, _bare_body(timeout=9.0), profile="slow")

    assert response.headers["X-AIGW-Cache"] == "miss"
    assert dispatch.bodies[0]["timeout"] == 9.0

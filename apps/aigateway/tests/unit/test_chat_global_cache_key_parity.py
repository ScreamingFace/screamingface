"""OME-1323 Stage C: the global chat-cache key stays byte-identical across the defaults cutover.

FEATURE: one globally shared exact-request cache (OME-305).

STORY: as an operator whose Profiles hold no saved defaults, every row my callers already
filled keeps hitting after Stage C removes the saved-defaults merge from the chat route.

INVARIANT: this is a BASELINE, not a RED test. It passes on the pre-change code
(``origin/main`` 634f8e7e) and must stay green, unmodified, through the implementation. For
three synthetic requests it pins:
- the exact canonical key material, as a literal mapping;
- its SHA-256, which can be recomputed with nothing but ``hashlib`` and ``json``;
- the route's cacheability: 200 then 200, ``miss`` then ``hit``, one dispatch, one row.

AIDEV-NOTE: if this goes red, a Stage C change has moved a cache key. Stop and ask the owner.
Never bump ``KEY_REVISION`` or ``PARAMETER_CONTRACT_REVISION``, and never edit these literals
to make it pass.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, cast
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
from aigateway.core.request_cache import RequestCacheWrite, global_keys
from aigateway.core.request_cache.canonical import canonical_digest
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_CHAT_PATH = "/v1/chat/completions"
_MODEL = "anthropic/claude-haiku-4-5"
_PROFILE = "default"
_DISPATCH_TARGET = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
_QUESTION = "how many primes below one hundred?"

# WHY a literal and not a call into global_keys: the point is to catch the gateway building a
# DIFFERENT mapping. A value computed by the code under test cannot pin that code.
_BASE_MATERIAL: dict[str, Any] = {
    "schema": "aigw-global-chat-cache-2026-08",
    "operation": "chat.completions",
    "provider": "anthropic",
    "requested_model": _MODEL,
    "resolved_model": _MODEL,
    "messages": [{"role": "user", "content": _QUESTION}],
    "system": {"present": False},
    "keyed_parameters": {},
    "prepared_request": {},
    "parameter_contract_revision": "aigw-parameter-contract-2026-08b",
    "provider_adapter_revision": "anthropic-global-cache-2026-08-9d5b38785f3a",
}

# Each case: (extra request-body members, its keyed_parameters member, pinned SHA-256).
_CASES = [
    pytest.param(
        {},
        {},
        "e8a63c0715d7a9ff8a8f202bc3f5f37b4d135df5750d5c0dd57e3c33cc2b3ef2",
        id="bare",
    ),
    pytest.param(
        {"temperature": 0.2},
        {"temperature": {"value": 0.2, "revision": "anthropic-2026-07"}},
        "cb5b9348d874933dabb05fbb705482864ec9b75bd5050d3a48aef1cb8e787ac7",
        id="explicit-temperature",
    ),
    pytest.param(
        {"max_tokens": 64},
        {"max_tokens": {"value": 64, "revision": "anthropic-2026-07"}},
        "c117ecca8862a8c22eb99a99f3c9c6b789e63c335ec84a6cd4ee10d305d274ff",
        id="explicit-max-tokens",
    ),
]


def _material(keyed: dict[str, Any]) -> dict[str, Any]:
    return {**_BASE_MATERIAL, "keyed_parameters": keyed}


def _body(extra: dict[str, Any]) -> dict[str, Any]:
    """The exact HTTP body sent to the route: the model, one user question, and ``extra``."""
    return {"model": _MODEL, "messages": [{"role": "user", "content": _QUESTION}], **extra}


# --- arrangement --------------------------------------------------------------


class _Dispatch:
    """Records every body that reached the provider and answers with a numbered reply."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def __call__(self, body: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        self.bodies.append(json.loads(json.dumps(body, default=str)))
        n = len(self.bodies)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": f"resp-{n}",
                "choices": [{"message": {"content": f"ANSWER-{n}"}, "finish_reason": "stop"}],
            }
        )


class _Store:
    """The frozen store contract, in memory."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> dict[str, Any] | None:
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


def _seed_empty_default_profile(credential_blobs, client: TestClient) -> None:
    # WHY empty defaults: the retained dev Profiles all hold ProfileDefaults(), and parity is
    # claimed exactly for them. A Profile with non-empty defaults changes on purpose (N1a).
    account_id = client.get("/v1/auth/me").json()["id"]
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, _PROFILE)),
        "default",
        json.dumps(
            {
                "access_token": "sk-ant-oat01-subscription-token",
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )

    async def _upsert() -> None:
        await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
            Profile(
                id=profile_id_for(account_id, "anthropic", _PROFILE),
                account_id=account_id,
                provider="anthropic",
                name=_PROFILE,
                state=ProfileState.AUTHENTICATED,
                defaults=ProfileDefaults(),
            )
        )

    asyncio.run(_upsert())


# --- the digest, with no gateway code at all ----------------------------------


@pytest.mark.parametrize(("extra", "keyed", "digest"), _CASES)
def test_the_pinned_material_hashes_to_the_pinned_digest(
    extra: dict[str, Any], keyed: dict[str, Any], digest: str
) -> None:
    # INVARIANT: the canonical form is JSON with sorted keys, no whitespace, UTF-8 text kept
    # as-is and no NaN. Anyone can recompute these three digests from the literals above.
    material = json.dumps(
        _material(keyed),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert hashlib.sha256(material.encode("utf-8")).hexdigest() == digest
    assert canonical_digest(_material(keyed)) == digest


# --- the route builds exactly that material and serves it ---------------------


@pytest.mark.parametrize(("extra", "keyed", "digest"), _CASES)
def test_the_route_builds_the_pinned_material_and_caches_it(
    credential_blobs,
    cache_client: TestClient,
    extra: dict[str, Any],
    keyed: dict[str, Any],
    digest: str,
) -> None:
    _seed_empty_default_profile(credential_blobs, cache_client)
    store = _Store()
    cast(Any, cache_client.app).state.request_cache_store = store
    dispatch = _Dispatch()
    built: list[dict[str, Any]] = []
    real_builder = global_keys.build_global_cache_key_dto

    def _spy(**kwargs: Any) -> Any:
        dto = real_builder(**kwargs)
        assert isinstance(dto, global_keys.GlobalChatCacheKey), dto
        built.append(global_keys._canonical_mapping(dto))
        return dto

    headers = {"X-Profile": _PROFILE}
    with (
        patch(_DISPATCH_TARGET, new=dispatch),
        patch.object(global_keys, "build_global_cache_key_dto", _spy),
    ):
        miss = cache_client.post(_CHAT_PATH, json=_body(extra), headers=headers)
        hit = cache_client.post(_CHAT_PATH, json=_body(extra), headers=headers)

    assert (miss.status_code, hit.status_code) == (200, 200), (miss.text, hit.text)
    assert (miss.headers["X-AIGW-Cache"], hit.headers["X-AIGW-Cache"]) == ("miss", "hit")
    # WHY a prefix here: the response header carries only the first 12 characters of the key
    # (chat_cache_stage.KEY_PREFIX_LENGTH). The full digest is pinned through the stored row.
    assert miss.headers["X-AIGW-Cache-Key"] == hit.headers["X-AIGW-Cache-Key"] == digest[:12]
    assert built == [_material(keyed), _material(keyed)]
    assert list(store.rows) == [digest]
    assert len(dispatch.bodies) == 1
    assert hit.json()["choices"][0]["message"]["content"] == "ANSWER-1"
    # An explicit caller value reaches the provider under its own name; a bare request
    # carries none of the three.
    for name, value in extra.items():
        assert dispatch.bodies[0][name] == value
    if not extra:
        assert not {"temperature", "max_tokens", "system"} & set(dispatch.bodies[0])

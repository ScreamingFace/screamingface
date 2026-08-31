"""OME-1026 final pass F4 — one request, ONE credential generation.

FEATURE: an honest parameter contract for a privately discovered model. Following a
private row's advertised URL returns that model's contract — or a retryable refusal —
never a document assembled from two different credential contexts.

STORY: as a profile owner replacing my API key while a colleague's dashboard is
loading a contract page, that page either shows the contract or asks to retry. It
never shows a document validated against the key I just revoked.

INVARIANT (the TOCTOU this closes): the route reads the profile index TWICE. The
first read (``_private_catalog_ids``) decides whether the model id exists at all, by
fetching the caller's snapshot under generation N. The second
(``_credential_target_for_chat``) resolves the credential context the whole document
is then built from. A credential replacement committing between them produced a 200
whose id was admitted under generation N and whose contract described N+1 — a
mixed-generation answer, and the one shape that must never be returned.

INVARIANT (the fence is scoped to the rescue path): a seeded or admitted id never
reads a private catalog, so it has no generation to mix and must not pay for a
recheck. Widening the fence to every request would add an index read — which decrypts
a credential blob — to the common path for nothing.

AIDEV-NOTE: the rotation here is a BARRIER, not a sleep. It is injected at the exact
seam by wrapping ``_credential_target_for_chat``, so "between validation and
resolution" is a structural property of the test rather than a timing hope.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.api_key_validation import (
    ApiKeyValidationResult,
    ApiKeyValidationStage,
    ApiKeyValidationState,
)
from aigateway.core.api_key_validation_service import ApiKeyValidationService
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from aigateway.routes import model_parameters as model_parameters_module

_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_PARAMS_URL = "/v1/model-parameters"
_NAME = "work"
_KEY = "sk-ant-fence-rotate"
# Exists ONLY in the canned private catalog, so nothing but the snapshot resolves it.
_DISCOVERED = "claude-rotation-only-4-9"
_PRIVATE_ID = f"anthropic/{_DISCOVERED}"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    def __init__(self) -> None:
        self.keys_seen: list[str] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "the private catalog must be dialed WITH a credential"
        self.keys_seen.append(headers["x-api-key"])
        assert url == _FIRST_PAGE, url
        body = json.dumps({"data": [{"id": _DISCOVERED, "type": "model"}], "has_more": False})
        return RawResponse(status=200, content_type="application/json", body=body)


def _setup(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> _CatalogClient:
    """A profile with a stored key and a canned private catalog behind it."""
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    http = _CatalogClient()
    cast(FastAPI, client.app).state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    stored = client.put(f"/v1/auth/anthropic/profiles/{_NAME}/api-key", json={"api_key": _KEY})
    assert stored.status_code == 200, stored.text
    # The premise: this id is not a compiled seed, so only the private snapshot has it.
    seeds = {entry.model_name for entry in anthropic_plugin_module.PLUGIN.register_models()}
    assert _DISCOVERED not in seeds, seeds
    return http


def _rotate_at_the_seam(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace the credential's identity EXACTLY between validation and resolution.

    # WHY the generation bump IS the credential replacement: every private cache
    # identity is ``(account, provider, profile, auth_type@genN)``, so advancing the
    # durable generation is precisely what a key replacement does to every key derived
    # from that credential. Bumping through the profile index — the app's own store, on
    # the app's own loop — keeps the write on one connection and avoids racing SQLite's
    # writer lock from the test thread.
    """
    real = model_parameters_module._credential_target_for_chat
    rotations = {"n": 0}

    async def _wrapper(request: Any, **kwargs: Any):
        if rotations["n"] == 0:
            rotations["n"] += 1
            index = request.app.state.profile_index
            profile = await index.get(
                kwargs["account_id"], kwargs["provider"], kwargs["profile_name"]
            )
            assert profile is not None, "the barrier needs an existing profile to rotate"
            await index.upsert(profile)
        return await real(request, **kwargs)

    monkeypatch.setattr(model_parameters_module, "_credential_target_for_chat", _wrapper)
    return rotations


def _contract(client: TestClient, model: str):
    return client.get(_PARAMS_URL, params={"model": model}, headers={"X-Profile": _NAME})


# ── the mixed-generation 200 must be unreachable ───────────────────────────────


def test_a_rotation_between_validation_and_resolution_is_refused(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline: a retryable refusal, never a document built from two contexts."""
    _setup(authenticated_client, monkeypatch)
    rotations = _rotate_at_the_seam(monkeypatch)

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert rotations["n"] == 1, "the barrier did not fire — the test proves nothing"
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "credential_generation_changed", detail
    # Sanitized: a code and the caller's own names, never key material or upstream text.
    assert detail["provider"] == "anthropic" and detail["profile"] == _NAME, detail
    assert "api_key" not in response.text and _KEY not in response.text


def test_the_refusal_still_carries_the_private_cache_policy(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1 and F4 compose: a new refusal is uncacheable like every other exit."""
    _setup(authenticated_client, monkeypatch)
    _rotate_at_the_seam(monkeypatch)

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert response.status_code == 409, response.text
    assert response.headers.get("cache-control") == "private, no-store", dict(response.headers)


def test_a_retry_after_the_rotation_settles_resolves_under_one_generation(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Retryable" has to mean something: the second attempt succeeds.

    The barrier fires ONCE, so the retry runs with a stable generation and must produce
    the contract — entirely under the new one.
    """
    _setup(authenticated_client, monkeypatch)
    rotations = _rotate_at_the_seam(monkeypatch)
    assert _contract(authenticated_client, _PRIVATE_ID).status_code == 409

    retry = _contract(authenticated_client, _PRIVATE_ID)

    assert rotations["n"] == 1, "the barrier must not fire again"
    assert retry.status_code == 200, retry.text
    assert retry.json()["model"]["id"] == _PRIVATE_ID, retry.json()["model"]


# ── the fence must not tax the common path ────────────────────────────────────


def test_a_private_id_resolves_normally_when_nothing_rotates(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recheck must not refuse a request that never had a problem."""
    _setup(authenticated_client, monkeypatch)

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert response.status_code == 200, response.text
    assert response.json()["model"]["upstream_id"] == _DISCOVERED, response.json()["model"]


def test_a_seeded_id_does_not_pay_for_the_recheck(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A compiled seed never reads a private catalog, so it has no generation to mix.

    # WHY assert this rather than leave it implied: a fence applied to every request
    # would add an index read — which decrypts a credential blob — to the hot path, and
    # would turn an ordinary key rotation into a 409 for models whose contract does not
    # depend on any credential at all.
    """
    _setup(authenticated_client, monkeypatch)
    rotations = _rotate_at_the_seam(monkeypatch)
    seeded = next(iter(anthropic_plugin_module.PLUGIN.register_models())).model_name

    response = _contract(authenticated_client, f"anthropic/{seeded}")

    assert rotations["n"] == 1, "the barrier fired, so a rotation really did happen"
    assert response.status_code == 200, response.text
    assert response.json()["model"]["upstream_id"] == seeded, response.json()["model"]


def test_a_profile_deleted_at_the_seam_is_refused_not_described(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generation is GONE rather than changed — still not a 200.

    # WHY it needs its own case: comparing two integers passes vacuously when the
    # second read finds nothing. A document validated against a deleted profile's
    # snapshot is exactly as wrong as one validated against a replaced credential.
    """
    _setup(authenticated_client, monkeypatch)
    real = model_parameters_module._credential_target_for_chat
    deleted = {"n": 0}

    async def _wrapper(request: Any, **kwargs: Any):
        if deleted["n"] == 0:
            deleted["n"] += 1
            index = request.app.state.profile_index
            profile = await index.get(
                kwargs["account_id"], kwargs["provider"], kwargs["profile_name"]
            )
            assert profile is not None
            await index.remove(profile.id)
        return await real(request, **kwargs)

    monkeypatch.setattr(model_parameters_module, "_credential_target_for_chat", _wrapper)

    response = _contract(authenticated_client, _PRIVATE_ID)

    assert deleted["n"] == 1
    assert response.status_code in {404, 409}, response.text
    assert response.json()["detail"]["code"] in {
        "credential_generation_changed",
        "profile_not_found",
    }, response.json()

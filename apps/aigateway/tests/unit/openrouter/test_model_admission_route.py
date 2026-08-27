"""OME-879: dynamic OpenRouter model admission — ``POST /v1/models/admit``.

FEATURE: run any OpenRouter model (OME-878). The engine asks this endpoint "does
this model actually exist on OpenRouter?" before refusing a run. A real catalog
model is admitted live (in-memory, deployment lifetime); everything else is
refused pre-spend with a diagnostic code naming which knob to turn.

INVARIANT: admission never persists anything and never touches the seeded
``default_models`` — a restart forgets every admission.
INVARIANT (§5.2): every catalog fetch goes through the bounded discovery
transport under an INJECTED client. No test in this file reaches the network.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.openrouter_provider.discovery import MODELS_URL, OPENAPI_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

from ._openapi_document import _OPENAPI, _RoutingClient

_SEED_UPSTREAM = "google/gemini-2.0-flash-001"
_SEED = f"openrouter/{_SEED_UPSTREAM}"
_TARGET_UPSTREAM = "qwen/qwen2.5-7b-instruct"
_TARGET = f"openrouter/{_TARGET_UPSTREAM}"

# Both the seed and the admission target are present, so the same document serves
# the admit route and the /v1/model-parameters follow-up.
_CATALOG = {
    "data": [
        {"id": _SEED_UPSTREAM, "supported_parameters": ["temperature", "max_tokens"]},
        {"id": _TARGET_UPSTREAM, "supported_parameters": ["temperature", "max_tokens"]},
    ]
}


@pytest.fixture
def openrouter_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patches the singleton INSTANCE, not the environment: `load_plugins` hands the
    # same object to every app, so env vars set after import cannot reach it.
    from aigateway.plugins.openrouter_provider import plugin as plugin_module

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        # OME-972 setup-only amendment: this suite exercises ADMISSION and its
        # canned two-document client; live listing discovery is not under test,
        # and leaving it on made /v1/models dial an unrouted catalog URL whose
        # KeyError was silently absorbed into a seed fallback. Assertions untouched.
        OpenRouterPluginSettings(enabled=True, live_models=False, default_models=[_SEED]),
    )


class _Clock:
    def now(self) -> float:
        return 1000.0


def _install_runtime(client: TestClient, http: DiscoveryHttpClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


async def _credential(
    credential_blobs, client: TestClient, state: ProfileState = ProfileState.AUTHENTICATED
) -> None:
    account_id = client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "openrouter", "default"),
            account_id=account_id,
            provider="openrouter",
            name="default",
            state=state,
            auth_type="api_key",
        )
    )


def _admit(client: TestClient, model_id: str) -> dict:
    resp = client.post("/v1/models/admit", json={"model_id": model_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- the happy path ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_real_catalog_model_is_admitted_and_listed(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is True
    assert body["model_id"] == _TARGET
    assert body["code"] is None

    listed = {row["id"] for row in authenticated_client.get("/v1/models").json()["data"]}
    assert _TARGET in listed
    assert _SEED in listed


@pytest.mark.asyncio
async def test_an_admitted_model_resolves_on_model_parameters(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    before = authenticated_client.get("/v1/model-parameters", params={"model": _TARGET})
    assert before.status_code == 404

    assert _admit(authenticated_client, _TARGET)["admitted"] is True
    after = authenticated_client.get("/v1/model-parameters", params={"model": _TARGET})
    assert after.status_code == 200, after.text


@pytest.mark.asyncio
async def test_re_admission_is_idempotent_and_reuses_the_catalog_fetch(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    assert _admit(authenticated_client, _TARGET)["admitted"] is True
    assert _admit(authenticated_client, _TARGET)["admitted"] is True

    # WHY one dial: the catalog id set is TTL-cached per app, so a burst of
    # admissions (a notebook re-run) costs one upstream fetch, not N.
    assert http.calls.count(MODELS_URL) == 1
    rows = [
        row for row in authenticated_client.get("/v1/models").json()["data"] if row["id"] == _TARGET
    ]
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_an_already_seeded_model_is_admitted_without_a_catalog_dial(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, _SEED)
    assert body["admitted"] is True
    assert http.calls == []


# --- the refusal ladder (all pre-spend, all $0) ------------------------------


@pytest.mark.asyncio
async def test_the_flag_off_refuses_before_anything_else(
    monkeypatch: pytest.MonkeyPatch, authenticated_client, credential_blobs
) -> None:
    from aigateway.plugins.openrouter_provider import plugin as plugin_module

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        OpenRouterPluginSettings(enabled=True, default_models=[_SEED], dynamic=False),
    )
    http = _RoutingClient({MODELS_URL: _CATALOG})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "dynamic_admission_disabled"
    assert http.calls == []


@pytest.mark.asyncio
async def test_a_disabled_provider_refuses_with_its_own_code(
    monkeypatch: pytest.MonkeyPatch, authenticated_client, credential_blobs
) -> None:
    from aigateway.plugins.openrouter_provider import plugin as plugin_module

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        OpenRouterPluginSettings(enabled=False, default_models=[_SEED]),
    )
    http = _RoutingClient({MODELS_URL: _CATALOG})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "provider_disabled"
    assert http.calls == []


def test_a_missing_credential_refuses_before_the_catalog_dial(
    openrouter_enabled, authenticated_client
) -> None:
    # No profile upserted: the account has no OpenRouter credential.
    http = _RoutingClient({MODELS_URL: _CATALOG})
    _install_runtime(authenticated_client, http)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "provider_not_credentialed"
    assert http.calls == []


@pytest.mark.asyncio
async def test_a_model_absent_from_the_catalog_is_refused(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: {"data": [{"id": _SEED_UPSTREAM}]}})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "model_not_on_openrouter"
    listed = {row["id"] for row in authenticated_client.get("/v1/models").json()["data"]}
    assert _TARGET not in listed


@pytest.mark.asyncio
async def test_a_catalog_outage_is_its_own_refusal_not_a_typo_verdict(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG}, fail=MODELS_URL)
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "openrouter_catalog_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_id",
    [
        "openrouter/qwen",  # one upstream segment
        "openrouter/qwen/qwen2.5-7b-instruct:free",  # ':variant' — cache/search bypass risk
        "openrouter/x-ai/grok-4~fast",  # '~' — engine colon escape, never admissible
        "openrouter/~alias/model",  # '~' author alias marker
    ],
)
async def test_variant_and_malformed_ids_are_refused_by_shape(
    openrouter_enabled, authenticated_client, credential_blobs, model_id: str
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    body = _admit(authenticated_client, model_id)
    assert body["admitted"] is False
    assert body["code"] == "invalid_model_id"
    assert http.calls == []


def test_an_unknown_provider_prefix_is_refused(openrouter_enabled, authenticated_client) -> None:
    body = _admit(authenticated_client, "nope/some/model")
    assert body["admitted"] is False
    assert body["code"] == "unknown_provider"


def test_a_provider_without_dynamic_admission_is_refused(
    openrouter_enabled, authenticated_client
) -> None:
    # The anthropic plugin exists but does not implement dynamic admission.
    body = _admit(authenticated_client, "anthropic/claude-nonexistent-model")
    assert body["admitted"] is False
    assert body["code"] == "dynamic_admission_unsupported"


def test_the_endpoint_requires_authentication(openrouter_enabled, client) -> None:
    resp = client.post("/v1/models/admit", json={"model_id": _TARGET})
    assert resp.status_code == 401


# --- PR #633 review fixes ----------------------------------------------------


@pytest.mark.asyncio
async def test_an_errored_profile_relays_reauth_not_no_key(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # STORY (review F6): a user with an EXPIRED key must be told to reconnect the
    # profile they have — "connect a key first" would loop them on re-adding the
    # same dead key forever.
    http = _RoutingClient({MODELS_URL: _CATALOG})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client, state=ProfileState.ERROR)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "auth_required"
    assert "reconnected" in body["message"]
    assert http.calls == []


@pytest.mark.asyncio
async def test_a_pending_profile_relays_finish_connecting(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    http = _RoutingClient({MODELS_URL: _CATALOG})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client, state=ProfileState.PENDING)

    body = _admit(authenticated_client, _TARGET)
    assert body["admitted"] is False
    assert body["code"] == "profile_pending_auth"
    assert "still connecting" in body["message"]
    assert http.calls == []


@pytest.mark.asyncio
async def test_a_full_admitted_set_refuses_without_a_catalog_dial(
    monkeypatch: pytest.MonkeyPatch, openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # INVARIANT (review F7): the admitted set is bounded — one caller looping over
    # OpenRouter's catalog cannot permanently fatten every tenant's listing and
    # every scheduled run's env. At capacity, refusal costs nothing upstream.
    from aigateway.routes import model_admission as route_module

    monkeypatch.setattr(route_module, "_MAX_ADMITTED_MODELS", 1)
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    assert _admit(authenticated_client, _TARGET)["admitted"] is True
    body = _admit(authenticated_client, "openrouter/mistralai/ministral-3b-2512")
    assert body["admitted"] is False
    assert body["code"] == "admission_capacity_reached"
    assert "capacity" in body["message"]
    assert http.calls.count(MODELS_URL) == 1  # only the grant dialed


@pytest.mark.asyncio
async def test_an_already_admitted_model_readmits_even_at_capacity(
    monkeypatch: pytest.MonkeyPatch, openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # WHY: idempotence outranks the cap — a saved notebook re-running against a
    # full deployment must keep working for the models it already admitted.
    from aigateway.routes import model_admission as route_module

    monkeypatch.setattr(route_module, "_MAX_ADMITTED_MODELS", 1)
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    assert _admit(authenticated_client, _TARGET)["admitted"] is True
    assert _admit(authenticated_client, _TARGET)["admitted"] is True


@pytest.mark.asyncio
async def test_the_catalog_cache_is_namespaced_per_provider(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # INVARIANT (review F9): each plugin gets its own compartment. OpenRouter's
    # generic "ids"/"expires_at" keys land under "openrouter", so a second
    # provider implementing `admit_model` can never read them as its own catalog.
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    assert _admit(authenticated_client, _TARGET)["admitted"] is True

    cache = cast(FastAPI, authenticated_client.app).state.admission_catalog_cache
    assert set(cache) == {"openrouter"}
    assert "ids" in cache["openrouter"]


@pytest.mark.asyncio
async def test_a_concurrent_admission_cannot_bypass_the_cap(
    monkeypatch: pytest.MonkeyPatch, openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # THE RACE (PR #633 follow-up): the route's cap pre-check and its dict insert are
    # separated by two awaits (credential resolution, the catalog dial). A rival
    # admission landing INSIDE that window used to slip past the pre-check and
    # overshoot the cap. The rival is simulated deterministically: the awaited
    # plugin decision itself fills the last slot before returning its grant —
    # the insert-time guard, not the pre-check, must hold the line.
    from aigateway.plugins.openrouter_provider import plugin as plugin_module
    from aigateway.routes import model_admission as route_module

    monkeypatch.setattr(route_module, "_MAX_ADMITTED_MODELS", 1)
    http = _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    _install_runtime(authenticated_client, http)
    await _credential(credential_blobs, authenticated_client)

    app = cast(FastAPI, authenticated_client.app)
    real_admit = plugin_module.PLUGIN.admit_model

    async def rival_wins_the_window(model_id: str, **kwargs):
        app.state.admitted_models["openrouter/rival/model"] = object()
        return await real_admit(model_id, **kwargs)

    monkeypatch.setattr(plugin_module.PLUGIN, "admit_model", rival_wins_the_window)

    body = _admit(authenticated_client, _TARGET)

    assert body["admitted"] is False
    assert body["code"] == "admission_capacity_reached"
    assert _TARGET not in app.state.admitted_models
    # INVARIANT: the cap holds — exactly the rival's slot, never cap+1.
    assert len(app.state.admitted_models) == 1


def test_the_insert_time_guard_is_idempotent_and_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aigateway.routes import model_admission as route_module
    from aigateway.routes.model_admission import _store_admission

    monkeypatch.setattr(route_module, "_MAX_ADMITTED_MODELS", 1)
    admitted: dict = {"openrouter/a/b": object()}

    # An id a rival admitted during the window is a grant (idempotence outranks
    # the cap), while a NEW id at capacity is refused.
    assert _store_admission(admitted, "openrouter/a/b", object()) is True
    assert _store_admission(admitted, "openrouter/c/d", object()) is False
    assert len(admitted) == 1

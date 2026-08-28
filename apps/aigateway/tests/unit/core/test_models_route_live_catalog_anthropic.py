"""OME-1026 U7 — /v1/models snapshot-or-fallback for Anthropic, at the public boundary.

INVARIANT (snapshot-or-fallback, inherited from OME-972): a healthy snapshot IS the
provider's listing (operator-explicit entries first, discovered next; compiled defaults
absent from it are NOT listed); a cold or degraded catalog lists the compiled seeds
byte-identically to today's behavior.

INVARIANT (opt-in): each of the three off-switches — no discovery key, ``live_models=false``,
and the global ``AIGW_DISCOVERY_ENABLED=false`` kill switch — means the exact seed listing and
ZERO Anthropic catalog egress.

INVARIANT (credential hygiene at the boundary): the discovery key rides only the allowlisted
Anthropic origin, and appears in no row, no error, no cache identity, and no log line.
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog, ModelListingProvider
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    RawResponse,
)
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelEntry
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import (
    ANTHROPIC_MODELS_DISCOVERY_SOURCE,
    MODELS_LIST_URL,
)
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings

_FAKE_KEY = "sk-ant-fixture-not-a-real-key"
_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
# Published ONLY by the live snapshot — in no compiled seed list.
_DISCOVERED_ONLY = "claude-opus-6-20270101"
# A compiled seed the canned catalog deliberately omits: retired upstream, so a healthy
# snapshot must drop it.
_RETIRED_SEED = "anthropic/claude-haiku-4-5"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _MutableClock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


def _body(ids: list[str], *, has_more: bool = False, last_id: str | None = None) -> str:
    payload: dict[str, Any] = {
        "data": [{"id": model_id, "type": "model"} for model_id in ids],
        "has_more": has_more,
    }
    if last_id is not None:
        payload["last_id"] = last_id
    return json.dumps(payload)


class _CatalogClient:
    """Canned Anthropic catalog. Asserts credentials on every dial; loud otherwise."""

    def __init__(self, bodies: list[str] | None = None, *, fail: bool = False) -> None:
        self._bodies = list(bodies) if bodies else [_body(["claude-opus-5", _DISCOVERED_ONLY])]
        self._fail = fail
        self.dialed: list[str] = []
        self.headers_seen: list[dict[str, str]] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        self.dialed.append(url)
        if url != _FIRST_PAGE:
            raise AssertionError(f"unexpected dial: {url}")
        assert headers is not None, "the Anthropic catalog dial must carry credentials"
        assert headers["x-api-key"] == _FAKE_KEY
        self.headers_seen.append(dict(headers))
        if self._fail:
            raise DiscoveryError("unreachable")
        body = self._bodies.pop(0) if len(self._bodies) > 1 else self._bodies[0]
        return RawResponse(status=200, content_type="application/json", body=body)


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> AnthropicPluginSettings:
    settings = AnthropicPluginSettings(**overrides)
    monkeypatch.setattr(anthropic_plugin_module.PLUGIN, "settings", settings)
    return settings


def _discovery_on(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> AnthropicPluginSettings:
    return _configure(monkeypatch, discovery_api_key=SecretStr(_FAKE_KEY), **overrides)


def _install(client: TestClient, http: Any, *, clock: Any = None) -> None:
    the_clock = clock if clock is not None else _Clock()
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=the_clock, limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=the_clock)


def _anthropic_ids(client: TestClient) -> list[str]:
    response = client.get("/v1/models")
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()["data"] if row["owned_by"] == "anthropic"]


def _seed_ids(settings: AnthropicPluginSettings) -> list[str]:
    return [f"anthropic/{entry.model_name}" for entry in settings.models]


async def _upsert_anthropic_profile(client: TestClient, credential_blobs: Any) -> None:
    """The detail route resolves a model only for a caller with a provider profile.

    # WHY needed here: ``/v1/model-parameters`` answers 404 ``profile_not_found`` before it
    # ever reports on the model, so without this the resolvability assertion would be
    # measuring the absence of a credential rather than the presence of a discovered id.
    """
    account_id = client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )


# --------------------------------------------------------------------------------------
# Acceptance 1 — the discovered listing.
# --------------------------------------------------------------------------------------


def test_a_healthy_snapshot_publishes_live_anthropic_ids(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _discovery_on(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)

    ids = _anthropic_ids(authenticated_client)

    # Rows keep today's shape; only the ID SET became live.
    assert ids == ["anthropic/claude-opus-5", f"anthropic/{_DISCOVERED_ONLY}"]
    # INVARIANT: a compiled seed upstream no longer serves DISAPPEARS — half the
    # product outcome is that a retired alias stops being advertised.
    assert _RETIRED_SEED not in ids
    assert http.dialed == [_FIRST_PAGE]


def test_a_published_row_keeps_the_established_shape(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Preserve the stable row shape that the historical SF-284 consumer relied on;
    # live discovery may change only the id set.
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())

    rows = authenticated_client.get("/v1/models").json()["data"]
    row = next(r for r in rows if r["id"] == f"anthropic/{_DISCOVERED_ONLY}")

    assert row["object"] == "model"
    assert row["owned_by"] == "anthropic"
    assert "supported_parameters" in row and "unsupported_parameter_behavior" in row
    # INVARIANT: no credential material can reach a published row.
    assert _FAKE_KEY not in json.dumps(row)


def test_operator_explicit_models_lead_and_survive_a_healthy_snapshot(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = ModelEntry(
        model_name="claude-operator-pinned",
        litellm_params={"model": "anthropic/claude-operator-pinned"},
    )
    _discovery_on(monkeypatch, models=[pinned])
    _install(authenticated_client, _CatalogClient())

    assert _anthropic_ids(authenticated_client) == [
        "anthropic/claude-operator-pinned",
        "anthropic/claude-opus-5",
        f"anthropic/{_DISCOVERED_ONLY}",
    ]


# --------------------------------------------------------------------------------------
# Acceptance 2 — opt-in only: three off-switches, each with ZERO egress.
# --------------------------------------------------------------------------------------


def test_no_discovery_key_lists_seeds_byte_identically_with_zero_dials(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)

    # INVARIANT: the default deployment is byte-identical to pre-OME-1026 behavior.
    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_live_models_false_lists_seeds_with_zero_dials(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _discovery_on(monkeypatch, live_models=False)
    http = _CatalogClient()
    _install(authenticated_client, http)

    # The fast off-switch: the key stays configured, discovery goes silent.
    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_the_discovery_kill_switch_serves_seeds_with_zero_dials(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MINOR-1: ``AIGW_DISCOVERY_ENABLED=false`` silences Anthropic with everything else."""
    settings = _discovery_on(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)
    app = cast(FastAPI, authenticated_client.app)
    app.state.model_catalog = None  # the shape build_model_catalog returns when disabled

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == []


def test_an_oauth_only_deployment_never_dials_the_catalog(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The locked refutation at the public boundary: OAuth is Anthropic's normal auth path,
    # but a subscription token is never a discovery credential.
    settings = _configure(monkeypatch)
    http = _CatalogClient()
    _install(authenticated_client, http)

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.headers_seen == []


# --------------------------------------------------------------------------------------
# Acceptance 3 — fail-closed: never a partial catalog cached as fresh.
# --------------------------------------------------------------------------------------


def test_a_malformed_refresh_never_replaces_the_last_good_snapshot(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The discriminating body rule: a LENIENT parser would have salvaged this page.

    # WHY this exact second body: it carries one unusable row (no ``id``) plus one good
    # id, with a well-formed envelope. A row-skipping parser would publish
    # ``claude-drifted`` as a complete fresh catalog and REPLACE the snapshot. A body that
    # fails under both readings (e.g. ``{}``) would let this test pass without the
    # all-or-nothing rule, so it would guard nothing.
    """
    _discovery_on(monkeypatch)
    clock = _MutableClock()
    salvageable = json.dumps(
        {
            "data": [
                {"display_name": "a drifted row with no id"},
                {"id": "claude-drifted", "type": "model"},
            ],
            "has_more": False,
        }
    )
    http = _CatalogClient([_body(["claude-opus-5"]), salvageable])
    _install(authenticated_client, http, clock=clock)

    healthy = _anthropic_ids(authenticated_client)
    assert healthy == ["anthropic/claude-opus-5"]

    # Past the provider-declared live-source TTL, the next request refreshes and gets junk.
    clock.value += ANTHROPIC_MODELS_DISCOVERY_SOURCE.ttl_s + 1.0
    after = _anthropic_ids(authenticated_client)

    # INVARIANT: a malformed catalog is a FAILED attempt, never a new snapshot — the last
    # good one keeps serving through the stale window.
    assert after == healthy
    assert "anthropic/claude-drifted" not in after
    assert len(http.dialed) == 2


def test_a_cold_malformed_refresh_falls_back_to_seeds(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _discovery_on(monkeypatch)
    # ``has_more`` missing entirely: unverifiable completeness, no last-good snapshot.
    http = _CatalogClient([json.dumps({"data": [{"id": "claude-opus-5"}]})])
    _install(authenticated_client, http)

    # With nothing good cached, the honest answer is the compiled seed listing — never
    # the salvaged rows of a page whose completeness cannot be established.
    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)


def test_a_cold_transport_failure_falls_back_to_seeds(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient(fail=True))

    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)


def test_a_revoked_operator_key_degrades_the_listing_and_not_the_route(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CC-10/D10: a 401 on the discovery key is a LISTING problem, never an outage."""
    settings = _discovery_on(monkeypatch)

    class _RevokedClient:
        def __init__(self) -> None:
            self.dialed: list[str] = []

        async def get(
            self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
        ) -> RawResponse:
            self.dialed.append(url)
            return RawResponse(
                status=401,
                content_type="application/json",
                body=json.dumps({"type": "error", "error": {"type": "authentication_error"}}),
            )

    http = _RevokedClient()
    _install(authenticated_client, http)

    # 200 with seeds — the operator's key problem must not become the caller's error.
    assert _anthropic_ids(authenticated_client) == _seed_ids(settings)
    assert http.dialed == [_FIRST_PAGE]


# --------------------------------------------------------------------------------------
# Acceptance 4 — credential hygiene in logs.
# --------------------------------------------------------------------------------------


def test_no_credential_material_appears_in_captured_logs(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    _discovery_on(monkeypatch)
    clock = _MutableClock()
    http = _CatalogClient([_body(["claude-opus-5"]), json.dumps({"data": "not-a-list"})])
    _install(authenticated_client, http, clock=clock)

    with caplog.at_level(logging.DEBUG):
        _anthropic_ids(authenticated_client)
        clock.value += ANTHROPIC_MODELS_DISCOVERY_SOURCE.ttl_s + 1.0
        _anthropic_ids(authenticated_client)

    captured = "\n".join(record.getMessage() for record in caplog.records)
    # INVARIANT: not on the happy path, and not on the degraded path either — the
    # failure log lines carry a reason token and a status, never headers.
    assert _FAKE_KEY not in captured
    assert "x-api-key" not in captured


def test_the_cache_identity_carries_no_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # INVARIANT: the snapshot is DEPLOYMENT-wide. A credential in the cache key would
    # silently shard it per key and quietly multiply upstream traffic.
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    _anthropic_ids(authenticated_client)

    assert _FAKE_KEY not in ANTHROPIC_MODELS_DISCOVERY_SOURCE.key
    assert _FAKE_KEY not in ANTHROPIC_MODELS_DISCOVERY_SOURCE.revision


# --------------------------------------------------------------------------------------
# Acceptance 5 — single-flight and tier logging, inherited and pinned once.
# --------------------------------------------------------------------------------------


def test_concurrent_callers_share_one_upstream_fetch_chain(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _discovery_on(monkeypatch)

    class _SlowClient:
        def __init__(self) -> None:
            self.dialed: list[str] = []

        async def get(
            self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
        ) -> RawResponse:
            self.dialed.append(url)
            await asyncio.sleep(0.2)
            return RawResponse(
                status=200, content_type="application/json", body=_body(["claude-opus-5"])
            )

    http = _SlowClient()
    _install(authenticated_client, http)

    # WHY instrument the catalog rather than time the client: every caller enters
    # ``entries_for`` and all but the winner park on the single-flight, so its peak depth
    # IS the concurrency. Client-side stamps prove nothing — the pool starts all threads
    # at ~t0 even if the server answered them strictly one at a time.
    depth = {"now": 0, "peak": 0}
    unwrapped = ModelCatalog.entries_for

    async def _counting_entries_for(
        self: ModelCatalog,
        plugin: ModelListingProvider,
        *,
        client: DiscoveryHttpClient,
        limits: DiscoveryLimits | None,
    ) -> tuple[ModelEntry, ...] | None:
        depth["now"] += 1
        depth["peak"] = max(depth["peak"], depth["now"])
        try:
            return await unwrapped(self, plugin, client=client, limits=limits)
        finally:
            depth["now"] -= 1

    monkeypatch.setattr(ModelCatalog, "entries_for", _counting_entries_for)

    callers = 6
    with ThreadPoolExecutor(max_workers=callers) as pool:
        statuses = list(
            pool.map(lambda _n: authenticated_client.get("/v1/models").status_code, range(callers))
        )

    assert statuses == [200] * callers
    # INVARIANT: one refresh serves every contemporaneous caller, so a burst of listings
    # costs ONE credentialed upstream fetch — which also protects a paid, rate-limited API.
    assert http.dialed == [_FIRST_PAGE]
    assert depth["peak"] == callers


def test_served_tier_transitions_are_logged_once_per_change(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """CC-10: an operator must be able to tell "still live" from "collapsed to seeds"."""
    _discovery_on(monkeypatch)
    clock = _MutableClock()
    http = _CatalogClient([_body(["claude-opus-5"]), json.dumps({"data": "junk"})])
    _install(authenticated_client, http, clock=clock)

    with caplog.at_level(logging.INFO):
        _anthropic_ids(authenticated_client)  # fresh
        fresh_lines = [r for r in caplog.records if "tier=fresh" in r.getMessage()]
        _anthropic_ids(authenticated_client)  # cache hit — must NOT re-log
        assert len([r for r in caplog.records if "tier=fresh" in r.getMessage()]) == len(
            fresh_lines
        )

        clock.value += ANTHROPIC_MODELS_DISCOVERY_SOURCE.ttl_s + 1.0
        _anthropic_ids(authenticated_client)  # failed refresh -> stale
        clock.value += ANTHROPIC_MODELS_DISCOVERY_SOURCE.stale_ttl_s + 1.0
        _anthropic_ids(authenticated_client)  # stale expired -> seeds

    text = "\n".join(r.getMessage() for r in caplog.records if "tier=" in r.getMessage())
    assert "provider=anthropic tier=fresh" in text
    assert "provider=anthropic tier=stale" in text
    assert "provider=anthropic tier=seeds" in text


# --------------------------------------------------------------------------------------
# Acceptance 6 — resolvability and the dispatch boundary.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_discovered_only_id_resolves_on_model_parameters(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, credential_blobs: Any
) -> None:
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    await _upsert_anthropic_profile(authenticated_client, credential_blobs)
    canonical = f"anthropic/{_DISCOVERED_ONLY}"

    # The id is published ONLY by the snapshot — it appears in no seed list.
    assert canonical not in _seed_ids(AnthropicPluginSettings())
    assert canonical in _anthropic_ids(authenticated_client)

    response = authenticated_client.get("/v1/model-parameters", params={"model": canonical})

    # INVARIANT: what /v1/models publishes, /v1/model-parameters resolves — a listed id
    # that 404s on its own detail URL is a broken published contract.
    assert response.status_code == 200, response.text
    assert response.json()["model"]["id"] == canonical


@pytest.mark.asyncio
async def test_the_static_parameter_evidence_is_unchanged_for_a_discovered_id(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch, credential_blobs: Any
) -> None:
    """Acceptance 7: ``anthropic:static`` evidence stays byte-identical (D4).

    # WHY compare a discovered id against a seeded one: OME-479 §6.3 is superseded for the
    # model LIST only. Parameter discovery remains credential-free and static, so both ids
    # must present exactly the same observation source.
    """
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    await _upsert_anthropic_profile(authenticated_client, credential_blobs)

    discovered = authenticated_client.get(
        "/v1/model-parameters", params={"model": f"anthropic/{_DISCOVERED_ONLY}"}
    ).json()
    seeded = authenticated_client.get(
        "/v1/model-parameters", params={"model": "anthropic/claude-opus-5"}
    ).json()

    assert discovered["parameters"] == seeded["parameters"]


def test_a_discovered_only_model_reaches_the_dispatch_boundary_with_a_credential(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end of the acceptance chain: listed -> resolvable -> actually dispatched."""
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())

    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    created = authenticated_client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "anthropic", "label": "chat", "api_key": "sk-ant-profile-key"},
    )
    assert created.status_code == 201, created.text

    canonical = f"anthropic/{_DISCOVERED_ONLY}"
    assert canonical in _anthropic_ids(authenticated_client)

    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda: {
                "id": "gen-live",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }
        )

    with patch("litellm.acompletion", _fake_acompletion):
        response = authenticated_client.post(
            "/v1/chat/completions",
            json={"model": canonical, "messages": [{"role": "user", "content": "hi"}]},
        )

    assert response.status_code == 200, response.text
    assert captured["model"] == canonical
    # INVARIANT: dispatch used the CALLER's profile credential. The deployment discovery
    # key is a listing credential and must never reach a chat request.
    assert _FAKE_KEY not in json.dumps(captured, default=str)


# --------------------------------------------------------------------------------------
# Coexistence — Anthropic discovery must not disturb any other provider.
# --------------------------------------------------------------------------------------


def test_anthropic_discovery_leaves_other_providers_untouched(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())

    rows = authenticated_client.get("/v1/models").json()["data"]
    openai_rows = [row["id"] for row in rows if row["owned_by"] == "openai"]

    assert openai_rows, "other providers must still publish their own seeds"


def test_anthropic_rows_coexist_with_admitted_rows_deduplicated(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CC-10: the merged listing keeps discovered, seeded and admitted rows distinct-but-once."""
    _discovery_on(monkeypatch)
    _install(authenticated_client, _CatalogClient())
    canonical = f"anthropic/{_DISCOVERED_ONLY}"
    app = cast(FastAPI, authenticated_client.app)
    app.state.admitted_models[canonical] = ModelEntry(
        model_name=canonical, litellm_params={"model": canonical}
    )

    ids = _anthropic_ids(authenticated_client)

    # An id arriving from BOTH the snapshot and admission still publishes exactly once.
    assert ids.count(canonical) == 1


def test_the_no_egress_tripwire_stays_loud_for_a_credentialed_listing(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CC-1 at route level: forbidden real egress must FAIL, not degrade to seeds.

    # WHY this matters more for Anthropic than for OpenRouter: the dial carries headers, and
    # a tripwire that raised TypeError instead of AssertionError would be sanitized by
    # ModelCatalog into ``internal_error`` -> a quiet seed listing, leaving a test that
    # really reached the internet passing green.
    """
    _discovery_on(monkeypatch)
    # No runtime/catalog installed: the app's DEFAULT wiring (real adapter, no transport).
    with pytest.raises(AssertionError, match="discovery egress"):
        authenticated_client.get("/v1/models")

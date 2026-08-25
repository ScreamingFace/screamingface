"""OME-972 U5 — /v1/models snapshot-or-fallback merge through the live catalog.

INVARIANT (snapshot-or-fallback): a healthy snapshot IS the provider's listing
(operator-explicit entries first, discovered next; compiled defaults absent
from it are NOT listed); a cold or degraded catalog lists the compiled seeds
byte-identically to today's behavior. Admitted models always join, deduplicated.
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import DiscoveryError, DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelEntry
from aigateway.plugins.openrouter_provider import plugin as plugin_module
from aigateway.plugins.openrouter_provider.live_models import (
    LIVE_MODELS_DISCOVERY_SOURCE,
    LIVE_MODELS_URL,
)
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

# A compiled default seed (factory list) that the canned live catalog below
# deliberately omits — retired upstream, so a healthy snapshot must drop it.
_COMPILED_SEED = "openrouter/anthropic/claude-fable-5"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CatalogClient:
    """Canned live catalog; records dials; optionally fails every dial."""

    def __init__(self, ids: list[str] | None = None, *, fail: bool = False) -> None:
        rows = list(ids or [])
        # Strict envelope: the live parser requires links.next + total_count.
        self._body = json.dumps(
            {"data": [{"id": i} for i in rows], "links": {"next": None}, "total_count": len(rows)}
        )
        self._fail = fail
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        if self._fail:
            raise DiscoveryError("unreachable")
        return RawResponse(status=200, content_type="application/json", body=self._body)


def _enable_openrouter(monkeypatch: pytest.MonkeyPatch, settings: OpenRouterPluginSettings) -> None:
    monkeypatch.setattr(plugin_module.PLUGIN, "settings", settings)


def _install(client: TestClient, http: _CatalogClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())


def _openrouter_ids(client: TestClient) -> list[str]:
    response = client.get("/v1/models")
    assert response.status_code == 200
    return [row["id"] for row in response.json()["data"] if row["owned_by"] == "openrouter"]


def test_app_wiring_installs_the_model_catalog(authenticated_client: TestClient) -> None:
    # WHY: the catalog must be app-lifetime state (deployment-wide cache), not
    # per-request — this pins the main.py wiring next to discovery_runtime.
    app = cast(FastAPI, authenticated_client.app)
    assert isinstance(app.state.model_catalog, ModelCatalog)


def test_healthy_snapshot_replaces_compiled_seeds(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    http = _CatalogClient(["qwen/qwen3-coder", "openai/gpt-5", "zed/zeta:free"])
    _install(authenticated_client, http)
    ids = _openrouter_ids(authenticated_client)
    # INVARIANT: discovered plain ids only, sorted; the colon variant is never
    # auto-published; a compiled default absent from the healthy snapshot is
    # NOT listed (retired models disappear).
    assert ids == ["openrouter/openai/gpt-5", "openrouter/qwen/qwen3-coder"]
    assert _COMPILED_SEED not in ids
    assert http.dialed == [LIVE_MODELS_URL]


def test_other_providers_are_untouched_by_the_live_catalog(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    _install(authenticated_client, _CatalogClient(["openai/gpt-5"]))
    response = authenticated_client.get("/v1/models")
    rows = response.json()["data"]
    anthropic = [row["id"] for row in rows if row["owned_by"] == "anthropic"]
    assert "anthropic/claude-opus-4-8" in anthropic


def test_explicit_operator_models_survive_a_healthy_snapshot_first(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(
        monkeypatch,
        OpenRouterPluginSettings(
            enabled=True,
            default_models=["openrouter/deepseek/deepseek-chat-v3.1:free"],
        ),
    )
    _install(authenticated_client, _CatalogClient(["openai/gpt-5"]))
    # INVARIANT: operator-explicit config (colon variant included) is listed
    # FIRST and survives every healthy snapshot.
    assert _openrouter_ids(authenticated_client) == [
        "openrouter/deepseek/deepseek-chat-v3.1:free",
        "openrouter/openai/gpt-5",
    ]


def test_cold_failure_falls_back_to_compiled_seeds_byte_identically(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = OpenRouterPluginSettings(enabled=True)
    _enable_openrouter(monkeypatch, settings)
    _install(authenticated_client, _CatalogClient(fail=True))
    # INVARIANT: cold/degraded == today's static behavior, exactly.
    assert _openrouter_ids(authenticated_client) == list(settings.default_models)


def test_live_models_disabled_means_seeds_and_zero_egress(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = OpenRouterPluginSettings(enabled=True, live_models=False)
    _enable_openrouter(monkeypatch, settings)
    http = _CatalogClient(["openai/gpt-5"])
    _install(authenticated_client, http)
    assert _openrouter_ids(authenticated_client) == list(settings.default_models)
    # INVARIANT (owner decision): the opt-out restores static behavior with
    # ZERO catalog egress — not one dial.
    assert http.dialed == []


def test_missing_catalog_state_falls_back_to_seeds(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = OpenRouterPluginSettings(enabled=True)
    _enable_openrouter(monkeypatch, settings)
    http = _CatalogClient(["openai/gpt-5"])
    _install(authenticated_client, http)
    app = cast(FastAPI, authenticated_client.app)
    app.state.model_catalog = None  # AIGW_DISCOVERY_ENABLED=false shape
    assert _openrouter_ids(authenticated_client) == list(settings.default_models)
    assert http.dialed == []


def test_admitted_models_join_once_even_when_also_discovered(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    _install(authenticated_client, _CatalogClient(["openai/gpt-5"]))
    app = cast(FastAPI, authenticated_client.app)
    app.state.admitted_models["openrouter/openai/gpt-5"] = ModelEntry(
        model_name="openrouter/openai/gpt-5",
        litellm_params={"model": "openrouter/openai/gpt-5"},
    )
    app.state.admitted_models["openrouter/moon/kimi-k2:free"] = ModelEntry(
        model_name="openrouter/moon/kimi-k2:free",
        litellm_params={"model": "openrouter/moon/kimi-k2:free"},
    )
    ids = _openrouter_ids(authenticated_client)
    # WHY once: an id can now arrive from BOTH the snapshot and admission —
    # the row set stays deduplicated on the canonical id.
    assert ids.count("openrouter/openai/gpt-5") == 1
    assert ids.count("openrouter/moon/kimi-k2:free") == 1


def test_repeat_requests_reuse_one_fetch_chain_and_stay_deterministic(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    http = _CatalogClient(["b/y", "a/x"])
    _install(authenticated_client, http)
    first = authenticated_client.get("/v1/models").json()
    second = authenticated_client.get("/v1/models").json()
    # INVARIANT: one upstream fetch chain per TTL window regardless of request
    # volume, and a byte-stable listing between refreshes.
    assert first == second
    assert http.dialed == [LIVE_MODELS_URL]


def test_the_no_egress_tripwire_stays_loud_through_the_whole_stack(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    # No runtime/catalog installed: the app's DEFAULT wiring (real discovery
    # client, no transport) is what a forgetful future test would hit.
    with pytest.raises(AssertionError, match="discovery egress"):
        authenticated_client.get("/v1/models")
    # INVARIANT: the conftest tripwire's AssertionError must surface as a test
    # failure — a catalog or route that absorbed it would convert forbidden
    # real egress into a silent seed fallback and the suite would stay green.


# --- OME-972 correction pass: acceptance completion --------------------------


class _MutableClock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


class _ScriptedClient:
    """Serves a different canned body per dial, in order."""

    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        body = self._bodies.pop(0) if len(self._bodies) > 1 else self._bodies[0]
        return RawResponse(status=200, content_type="application/json", body=body)


def _strict_body(ids: list[str]) -> str:
    return json.dumps(
        {"data": [{"id": i} for i in ids], "links": {"next": None}, "total_count": len(ids)}
    )


def test_a_malformed_refresh_never_replaces_the_last_good_snapshot(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    clock = _MutableClock()
    # Second dial answers 200 with a page missing its completeness metadata —
    # the shape that silently looked like a complete catalog before this pass.
    http = _ScriptedClient([_strict_body(["openai/gpt-5"]), json.dumps({"data": []})])
    app = cast(FastAPI, authenticated_client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=clock, limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=clock)

    healthy = _openrouter_ids(authenticated_client)
    assert healthy == ["openrouter/openai/gpt-5"]

    # Past the LIVE-SOURCE ttl (300 s, declared by the provider — not the
    # runtime cache's own limits): the next request refreshes and gets junk.
    clock.value += LIVE_MODELS_DISCOVERY_SOURCE.ttl_s + 1.0
    after = _openrouter_ids(authenticated_client)

    # INVARIANT: a malformed catalog is a FAILED attempt, never a fresh empty
    # one — the last good snapshot keeps serving inside the stale window.
    assert after == healthy
    assert len(http.dialed) == 2


def test_a_page_without_completeness_metadata_falls_back_to_seeds_when_cold(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = OpenRouterPluginSettings(enabled=True)
    _enable_openrouter(monkeypatch, settings)
    http = _ScriptedClient([json.dumps({"data": [{"id": "openai/gpt-5"}]})])
    app = cast(FastAPI, authenticated_client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())
    # With no last-good snapshot to fall back to, the honest answer is the
    # compiled seed listing — never the salvaged rows of an unverifiable page.
    assert _openrouter_ids(authenticated_client) == list(settings.default_models)


def test_concurrent_callers_share_one_upstream_fetch_chain_and_all_get_200(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))

    class _SlowClient:
        def __init__(self) -> None:
            self.dialed: list[str] = []

        async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
            self.dialed.append(url)
            await asyncio.sleep(0.2)
            return RawResponse(
                status=200, content_type="application/json", body=_strict_body(["openai/gpt-5"])
            )

    http = _SlowClient()
    app = cast(FastAPI, authenticated_client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    app.state.model_catalog = ModelCatalog(clock=_Clock())

    def _timed_get(_n: int) -> tuple[int, float, float]:
        started = time.monotonic()
        response = authenticated_client.get("/v1/models")
        return response.status_code, started, time.monotonic()

    callers = 6
    with ThreadPoolExecutor(max_workers=callers) as pool:
        results = list(pool.map(_timed_get, range(callers)))

    assert [status for status, _s, _e in results] == [200] * callers
    # INVARIANT: single-flight — one refresh serves every contemporaneous caller,
    # so a burst of listings costs ONE upstream fetch chain, not N.
    assert http.dialed == [LIVE_MODELS_URL]
    # ...and they really were contemporaneous: the last request to start did so
    # before the first one finished (otherwise this would only prove caching).
    latest_start = max(start for _s, start, _e in results)
    earliest_end = min(end for _s, _st, end in results)
    assert latest_start < earliest_end, "requests did not overlap; concurrency unproven"


def test_a_raising_discovery_source_stays_loud_on_the_listing_route(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    _install(authenticated_client, _CatalogClient(["openai/gpt-5"]))

    def _boom() -> None:
        raise ValueError("provider bug in the source declaration")

    monkeypatch.setattr(plugin_module.PLUGIN, "model_discovery_source", _boom)
    # INVARIANT (plan D21): a PROGRAMMING error in the cheap synchronous hook is
    # not an upstream failure and must never be laundered into a quiet seed
    # fallback — that would hide a permanently broken provider behind a listing
    # that looks merely degraded.
    with pytest.raises(ValueError, match="provider bug"):
        authenticated_client.get("/v1/models")


def test_a_raising_discovery_source_stays_loud_on_the_detail_route(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_openrouter(monkeypatch, OpenRouterPluginSettings(enabled=True))
    _install(authenticated_client, _CatalogClient(["openai/gpt-5"]))

    def _boom() -> None:
        raise ValueError("provider bug in the source declaration")

    monkeypatch.setattr(plugin_module.PLUGIN, "model_discovery_source", _boom)
    # The lazy 404-rescue reaches the same hook; the same rule applies there.
    with pytest.raises(ValueError, match="provider bug"):
        authenticated_client.get(
            "/v1/model-parameters", params={"model": "openrouter/nope/not-here"}
        )

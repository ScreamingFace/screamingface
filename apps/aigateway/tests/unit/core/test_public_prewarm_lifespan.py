"""OME-1026 final pass — startup prewarm, through a REAL app lifespan.

FEATURE: a warm first request. The gateway starts one background refresh per public
provider catalog while it boots, so the first caller reads a snapshot instead of
paying the first upstream fetch.

STORY: as the first user after a deploy I get the live model list, not the seeds,
because the gateway fetched it while it was starting.

INVARIANT (why this file exists at all): the shared unit suite DISABLES startup
prewarm, because several suites enable a public provider through a fixture that runs
before the app is built and prewarm would then dial the real internet. Disabling a
production behaviour for the suite is only safe if something still pins it — this is
that something, through the ``public_catalog_prewarm`` opt-in.

INVARIANT (startup never waits): prewarm STARTS refreshes and returns. The lifespan
must not block on an upstream catalog, so a provider that never answers cannot delay
readiness.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.openrouter_provider import plugin as plugin_module
from aigateway.plugins.openrouter_provider.live_models import LIVE_MODELS_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from tests.conftest import TEST_SECRET_KEY

_LIVE_ID = "openai/gpt-5-prewarmed"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CannedCatalog:
    """OpenRouter's public listing document, served in process."""

    def __init__(self, ids: list[str]) -> None:
        self._body = json.dumps(
            {"data": [{"id": i} for i in ids], "links": {"next": None}, "total_count": len(ids)}
        )
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return RawResponse(status=200, content_type="application/json", body=self._body)


class _NeverAnswers:
    """A catalog that accepts the dial and never returns."""

    def __init__(self) -> None:
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


@pytest.fixture
def prewarmed_app(
    monkeypatch: pytest.MonkeyPatch,
    public_catalog_prewarm: None,
    credential_blobs: Any,
):
    """Build the app with a CANNED discovery runtime already in place at startup.

    # WHY the runtime is patched at its BUILDER rather than assigned afterwards:
    # prewarm runs inside the lifespan, so a transport installed after
    # ``TestClient.__enter__`` would arrive too late to serve it. That is also why this
    # file cannot use the shared ``client`` fixture — the patch has to precede
    # ``create_app``.
    """
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", f"sqlite://{credential_blobs.db_path}")
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(TEST_SECRET_KEY).decode())
    monkeypatch.setenv("AIGW_ALLOWED_NETWORKS", "10.0.0.0/8")

    def _build(http: Any):
        def _factory(_settings: Any) -> DiscoveryRuntime:
            return DiscoveryRuntime(
                client=http,
                cache=ObservationCache(
                    clock=_Clock(),
                    limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8),
                ),
                limits=DiscoveryLimits(timeout_s=1.0),
            )

        from aigateway import discovery_lifecycle

        monkeypatch.setattr(discovery_lifecycle, "build_discovery_runtime", _factory)

    return _build


def _enable_openrouter(monkeypatch: pytest.MonkeyPatch) -> OpenRouterPluginSettings:
    settings = OpenRouterPluginSettings(
        enabled=True, default_models=["openrouter/openai/seed-only"]
    )
    monkeypatch.setattr(plugin_module.PLUGIN, "settings", settings)
    return settings


def _openrouter_ids(client: TestClient) -> list[str]:
    listing = client.get("/v1/models")
    assert listing.status_code == 200, listing.text
    return [row["id"] for row in listing.json()["data"] if row["owned_by"] == "openrouter"]


def test_startup_prewarm_makes_the_first_request_a_warm_one(
    monkeypatch: pytest.MonkeyPatch, prewarmed_app
) -> None:
    """The payoff, end to end: ONE dial, made at startup, serving the first caller."""
    _enable_openrouter(monkeypatch)
    http = _CannedCatalog([_LIVE_ID])
    prewarmed_app(http)
    from aigateway.main import create_app

    with TestClient(create_app(), client=("10.1.2.3", 50000)) as client:
        login = client.post(
            "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
        )
        assert login.status_code == 200, login.text
        client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
        # Barrier, not a sleep: finish the refresh prewarm started, in the app's loop.
        client.portal.call(client.app.state.public_refreshes.drain)  # type: ignore[union-attr]

        ids = _openrouter_ids(client)
        # The live row is present on the FIRST request — that is what "warm" means.
        # (The provider merges operator-configured models with discovered ids, so the
        # configured seed is expected alongside it.)
        assert f"openrouter/{_LIVE_ID}" in ids, ids
        assert "openrouter/openai/seed-only" in ids, ids
        # INVARIANT: prewarm and the request share ONE refresh identity, so the request
        # observed prewarm's work instead of dialing again.
        assert http.dialed == [LIVE_MODELS_URL], http.dialed


def test_startup_does_not_wait_for_the_catalog_it_prewarms(
    monkeypatch: pytest.MonkeyPatch, prewarmed_app
) -> None:
    """A provider that never answers must not delay readiness by one second.

    # WHY this is the load-bearing half: prewarm's value is latency, but its RISK is
    # boot time. The refresh is started and never awaited, so entering the lifespan
    # returns while the dial is still open.
    """
    _enable_openrouter(monkeypatch)
    http = _NeverAnswers()
    prewarmed_app(http)
    from aigateway.main import create_app

    with TestClient(create_app(), client=("10.1.2.3", 50000)) as client:
        # Readiness is provable without any auth: the app answered while the dial hangs.
        assert client.get("/healthz").status_code == 200
        assert http.dialed == [LIVE_MODELS_URL], "prewarm must have started the dial"
        state = client.app.state  # type: ignore[union-attr]
        assert state.public_refreshes.inflight == 1, "the refresh must still be running"
    # Leaving the context runs the lifespan's bounded shutdown, which cancels it.


def test_the_suite_default_is_prewarm_disabled(client: TestClient) -> None:
    """The opt-in above is meaningful only because the default is off.

    # WHY assert it rather than trust it: without the opt-out, every suite whose
    # fixture enables a public provider before app construction dials for real at
    # startup, and the suite-wide background-error assertion (F6) fails everywhere.
    """
    assert client.app.state.public_refreshes.tracked_keys() == ()  # type: ignore[union-attr]

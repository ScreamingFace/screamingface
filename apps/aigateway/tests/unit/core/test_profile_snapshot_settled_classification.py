"""OME-1026 adversarial B5 — a refused refresh must not resurrect an expired snapshot.

FEATURE: an honest freshness label on a private listing. ``status`` is the caller's
whole basis for trusting the rows, so it must describe the rows actually being served.

STORY: as a profile owner whose catalog outgrew this worker's row budget I am told the
list is not advancing — I am never handed hours-old rows labelled ``fresh``.

INVARIANT (the defect this closes): ``settled_answer`` assumed that any snapshot
present after a refresh we waited for was written BY that refresh, so it returned it
as ``fresh`` with no reason. That is true only when the attempt was accepted. When the
attempt FAILED — an oversized snapshot refused for the row budget above all — the
entries in the record are the PREVIOUS ones, whose age may be anything at all, and an
independent probe was served rows past ``ttl + stale_ttl`` labelled ``fresh``.

INVARIANT (one classifier): freshness is decided by the same TTL arithmetic an
ordinary read uses. ``entries is not None`` is not a freshness test.

AIDEV-NOTE: the clock is test-owned, so TTL expiry is a STEP and never a wait.
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
from aigateway.core.parameter_discovery import DiscoveryError, DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.plugin_base import ModelDiscoverySource
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.core.profile_snapshot_store import (
    CACHE_BUDGET_REASON,
    ProfileCacheKey,
    ProfileSnapshotStore,
)
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from tests.conftest import drain_private_catalog

_KEY: ProfileCacheKey = ("acct", "anthropic", "work", "api_key@gen1")
_SOURCE = ModelDiscoverySource(
    key="anthropic:models",
    revision="test",
    ttl_s=60.0,
    stale_ttl_s=120.0,
    failure_ttl_s=30.0,
)
_MAX_ROWS = 6
_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_LIST_URL = "/v1/auth/anthropic/profiles/{name}/models"
_API_KEY = "sk-ant-settled"


class _Clock:
    """A clock the test advances, so TTL expiry is a step and not a wait."""

    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


def _rows(count: int) -> tuple[Any, ...]:
    """``count`` opaque rows. The store counts them; it never inspects them."""
    return tuple(object() for _ in range(count))


def _store_with_a_snapshot(rows: int = 4) -> tuple[ProfileSnapshotStore, _Clock]:
    clock = _Clock()
    store = ProfileSnapshotStore(clock=clock, max_identities=8, max_rows=_MAX_ROWS)
    store.store(_KEY, _rows(rows))
    return store, clock


def _refuse_an_oversized_replacement(store: ProfileSnapshotStore) -> None:
    """The premise of every case below: the newest attempt was REFUSED."""
    with pytest.raises(DiscoveryError):
        store.store(_KEY, _rows(_MAX_ROWS + 1))


# ── the classifier itself ─────────────────────────────────────────────────────


def test_an_accepted_store_settles_as_fresh() -> None:
    """The unchanged half: rows this very attempt wrote are fresh by construction."""
    store, _clock = _store_with_a_snapshot()

    answer = store.settled_answer(_KEY, source=_SOURCE, reason=None)

    assert answer.status == "fresh", answer
    assert answer.reason is None
    assert answer.entries is not None and len(answer.entries) == 4


def test_a_refused_replacement_settles_as_stale_inside_the_stale_window() -> None:
    """Servable, but honestly labelled — and carrying WHY it is not advancing."""
    store, clock = _store_with_a_snapshot()
    clock.value += _SOURCE.ttl_s + 1.0
    _refuse_an_oversized_replacement(store)

    answer = store.settled_answer(_KEY, source=_SOURCE, reason=CACHE_BUDGET_REASON)

    assert answer.status == "stale", answer
    assert answer.reason == CACHE_BUDGET_REASON, answer
    assert answer.entries is not None and len(answer.entries) == 4
    assert store.retained_rows <= store.max_rows


def test_a_refused_replacement_past_the_stale_window_is_never_served() -> None:
    """The reproduced defect: expired rows were handed back labelled ``fresh``."""
    store, clock = _store_with_a_snapshot()
    clock.value += _SOURCE.ttl_s + _SOURCE.stale_ttl_s + 1.0
    _refuse_an_oversized_replacement(store)

    answer = store.settled_answer(_KEY, source=_SOURCE, reason=CACHE_BUDGET_REASON)

    assert answer.status == "fallback", answer
    assert answer.entries is None, "rows past the stale window must not be served at all"
    assert answer.reason == CACHE_BUDGET_REASON, answer


def test_no_snapshot_at_all_settles_as_seeds_with_the_reason() -> None:
    """Nothing to serve is a fallback, not an empty ``fresh`` listing."""
    clock = _Clock()
    store = ProfileSnapshotStore(clock=clock, max_identities=8, max_rows=_MAX_ROWS)
    store.record_failure(_KEY, DiscoveryError("bad_status", status=401))

    answer = store.settled_answer(_KEY, source=_SOURCE, reason="bad_status")

    assert answer.status == "fallback" and answer.entries is None, answer
    assert answer.reason == "bad_status", answer


def test_an_ordinary_failed_refresh_classifies_the_previous_snapshot_too() -> None:
    """Not only the row-budget refusal: ANY failed attempt leaves the OLD rows."""
    store, clock = _store_with_a_snapshot()
    clock.value += _SOURCE.ttl_s + _SOURCE.stale_ttl_s + 1.0
    store.record_failure(_KEY, DiscoveryError("bad_status", status=401))

    answer = store.settled_answer(_KEY, source=_SOURCE, reason="bad_status")

    assert answer.status == "fallback", answer
    assert answer.reason == "bad_status", answer


def test_the_row_bound_still_holds_through_every_classification() -> None:
    """B5 must not have loosened B/F7: the hard cap is unchanged."""
    store, clock = _store_with_a_snapshot()
    for step in range(4):
        clock.value += _SOURCE.ttl_s + 1.0
        _refuse_an_oversized_replacement(store)
        assert store.retained_rows <= store.max_rows, step
        store.settled_answer(_KEY, source=_SOURCE, reason=CACHE_BUDGET_REASON)
        assert store.retained_rows <= store.max_rows, step


# ── the same schedule, through the real route ─────────────────────────────────


class _SizedCatalog:
    """A credentialed catalog whose SIZE the test controls between dials."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.dials = 0

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "the private catalog must be dialed WITH a credential"
        assert url == _FIRST_PAGE, url
        self.dials += 1
        body = json.dumps(
            {
                "data": [{"id": f"claude-settled-{i}", "type": "model"} for i in range(self.count)],
                "has_more": False,
            }
        )
        return RawResponse(status=200, content_type="application/json", body=body)


def _setup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, http: _SizedCatalog
) -> tuple[ProfileModelCatalog, _Clock]:
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )

    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )
    clock = _Clock()
    catalog = ProfileModelCatalog(
        clock=clock, max_identities=64, max_inflight_refreshes=8, max_rows=_MAX_ROWS
    )
    app.state.profile_model_catalog = catalog
    return catalog, clock


def _listing(client: TestClient, *, name: str) -> dict:
    response = client.get(_LIST_URL.format(name=name))
    assert response.status_code == 200, response.text
    return response.json()


def test_the_route_never_serves_expired_rows_as_fresh(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The independent probe's exact schedule, end to end.

    A good snapshot ages out of its whole stale window; the replacement is refused for
    the row budget. The answer must be the compiled seeds with the sanitized reason —
    not the aged rows, and above all not ``fresh``.
    """
    http = _SizedCatalog(count=4)
    catalog, clock = _setup(authenticated_client, monkeypatch, http)
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _API_KEY}
    )
    assert stored.status_code == 200, stored.text
    drain_private_catalog(authenticated_client)
    assert _listing(authenticated_client, name="work")["status"] == "fresh"

    http.count = 50
    source = anthropic_plugin_module.PLUGIN.model_discovery_source()
    assert source is not None
    clock.value += source.ttl_s + source.stale_ttl_s + 1.0

    body = _listing(authenticated_client, name="work")

    assert body["status"] == "fallback", body
    assert body["reason"] == CACHE_BUDGET_REASON, body
    ids = {row["id"] for row in body["data"]}
    assert not any(row_id.startswith("anthropic/claude-settled-") for row_id in ids), ids
    assert catalog.retained_rows <= catalog.max_rows


def test_the_route_does_not_redial_while_the_refusal_is_damped(
    authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Honest classification must not cost an upstream dial per page load."""
    http = _SizedCatalog(count=4)
    _catalog, clock = _setup(authenticated_client, monkeypatch, http)
    stored = authenticated_client.put(
        "/v1/auth/anthropic/profiles/work/api-key", json={"api_key": _API_KEY}
    )
    assert stored.status_code == 200, stored.text
    drain_private_catalog(authenticated_client)

    http.count = 50
    source = anthropic_plugin_module.PLUGIN.model_discovery_source()
    assert source is not None
    clock.value += source.ttl_s + source.stale_ttl_s + 1.0
    _listing(authenticated_client, name="work")
    drain_private_catalog(authenticated_client)
    dials = http.dials

    for _ in range(4):
        assert _listing(authenticated_client, name="work")["reason"] == CACHE_BUDGET_REASON
        drain_private_catalog(authenticated_client)

    assert http.dials == dials, "a refused catalog must stay damped, not re-dialed"

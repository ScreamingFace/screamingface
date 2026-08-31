"""OME-1026 adversarial B2 (F3) — a stale refresh must lose to the new owner, in BOTH stores.

FEATURE: profile credential refresh that is safe against concurrent ownership change.

STORY: as an owner who replaces a profile's credential — a new API key, a fresh OAuth
login, or a delete — my change wins, even against a refresh that was already talking to
the provider when I made it. The stale refresh does not restore the previous owner's
token, metadata, or listing.

INVARIANT (the reproduced defect): removing the routine-refresh generation bump was not
enough, because the provider strategy PERSISTED the refreshed credential during
``_refresh_credential`` — before the profile-index publication was even attempted. The
schedule that reproduced it:

  1. refresh A reads generation N
  2. A parks inside the provider token call
  3. replacement B publishes at N+1 (credential bytes AND profile metadata)
  4. A resumes and writes ITS credential blob, overwriting B's
  5. A publishes with the presence-only ``credential_owner_unchanged=True`` upsert
  6. owner/profile A is restored while the durable generation still reads N+1

INVARIANT (the fix these tests pin): nothing is persisted during the provider call. The
refreshed bytes are BUFFERED, and the publication is one transaction containing the
index CAS (presence + expected generation + expected auth type) and the credential CAS
(the bytes must still be the ones read before the network call). Either check failing
rolls back both. A check performed after the credential has already been written would
not be enough, which is why the write is deferred rather than guarded in place.

AIDEV-NOTE: the barrier is a ``threading.Event`` released by the test, never a sleep, and
the stores are the REAL ``ORMStore``/``ProfileIndexStore`` against the suite's SQLite
file. No provider egress: the token endpoint is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx
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
from aigateway.core.parameter_discovery_cache import (
    CacheLimits,
    ObservationCache,
    SystemMonotonicClock,
)
from aigateway.core.profile_model_catalog import ProfileModelCatalog
from aigateway.core.profile_models import credential_name_for
from aigateway.plugins.anthropic_provider import plugin as anthropic_plugin_module
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from aigateway.plugins.anthropic_provider.settings import AnthropicPluginSettings
from tests.conftest import drain_private_catalog

_PROFILE = "work"
_REFRESH_URL = f"/v1/auth/anthropic/profiles/{_PROFILE}/refresh"
_PROFILE_URL = f"/v1/auth/anthropic/profiles/{_PROFILE}"
_LISTING_URL = f"/v1/auth/anthropic/profiles/{_PROFILE}/models"
_API_KEY_URL = f"/v1/auth/anthropic/profiles/{_PROFILE}/api-key"
_STALE_TOKEN = "oauth-A-refreshed-must-not-persist"
_REPLACEMENT_KEY = "sk-ant-replacement-B-0000WXYZ"
_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"


@contextmanager
def _server_errors_as_responses(client: TestClient) -> Iterator[None]:
    """Observe what the ASGI server would send instead of re-raising into this thread."""
    transport = client._transport  # noqa: SLF001 - the documented TestClient seam
    previous = transport.raise_server_exceptions
    transport.raise_server_exceptions = False
    try:
        yield
    finally:
        transport.raise_server_exceptions = previous


def _token_factory(
    token: str,
    *,
    stall: threading.Event | None = None,
    started: threading.Event | None = None,
):
    """A canned OAuth token endpoint that can PARK deterministically.

    # AIDEV-NOTE: ``asyncio.to_thread`` for the wait, so the app's event loop stays free
    # while A is parked — otherwise request B could not run at all and the schedule
    # would be untestable rather than safe.
    """

    async def token_handler(_request: httpx.Request) -> httpx.Response:
        if started is not None:
            started.set()
        if stall is not None and not await asyncio.to_thread(stall.wait, 5):
            raise TimeoutError("the parked refresh was never released")
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": f"refresh-{token}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    return lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(token_handler), timeout=httpx.Timeout(5.0)
    )


class _CountingCatalog:
    """A canned private model catalog that counts credentialed dials."""

    def __init__(self) -> None:
        self.dials = 0

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert headers is not None, "a private catalog dial must carry a credential"
        assert url == _FIRST_PAGE, url
        self.dials += 1
        body = json.dumps({"data": [{"id": "claude-owner-b", "type": "model"}], "has_more": False})
        return RawResponse(status=200, content_type="application/json", body=body)


def _account_id(client: TestClient) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _service(client: TestClient) -> str:
    return credential_service_for(credential_name_for(_account_id(client), _PROFILE))


def _durable(client: TestClient) -> tuple[dict | None, int]:
    """The COMMITTED profile row and its ownership generation, read on the app's loop.

    # AIDEV-NOTE: through ``client.portal`` deliberately. The app holds its Tortoise
    # connection on that loop; a read issued from pytest's own loop against the same
    # SQLite file contends with the writer lock and hangs instead of failing.
    """
    index = cast(FastAPI, client.app).state.profile_index
    account_id = _account_id(client)

    async def _read() -> tuple[dict | None, int]:
        found = await index.get_with_credential_generation(account_id, "anthropic", _PROFILE)
        if found is None:
            return None, 0
        profile, generation = found
        return profile.model_dump(mode="json"), generation

    portal = client.portal
    assert portal is not None, "the TestClient must be running its lifespan"
    return portal.call(_read)


def _authenticate_oauth_profile(client: TestClient, *, token: str = "oauth-A") -> None:
    """Bring the profile to AUTHENTICATED/oauth through the real OAuth routes."""
    cast(FastAPI, client.app).state.anthropic_http_factory = _token_factory(token)
    start = client.post("/v1/auth/anthropic/profiles", json={"name": _PROFILE})
    assert start.status_code == 201, start.text
    callback = client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-A", "state": start.json()["state"]},
        follow_redirects=False,
    )
    assert callback.status_code == 200, callback.text


def _accept_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


def _enable_private_discovery(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> _CountingCatalog:
    monkeypatch.setattr(
        anthropic_plugin_module.PLUGIN, "settings", AnthropicPluginSettings(live_models=True)
    )
    http = _CountingCatalog()
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=SystemMonotonicClock(),
            limits=CacheLimits(ttl_s=600.0, stale_ttl_s=600.0, max_entries=8),
        ),
        limits=DiscoveryLimits(),
    )
    app.state.profile_model_catalog = ProfileModelCatalog(
        max_identities=64, max_inflight_refreshes=8
    )
    return http


@dataclass
class _Observed:
    """What the durable stores hold once the stale refresh has been released."""

    status: int
    body: dict
    blob: str | None
    profile: dict | None
    generation: int


def _run_stale_refresh_against(
    client: TestClient,
    replacement: Any,
) -> _Observed:
    """Park refresh A inside the provider call, run ``replacement``, then release A.

    ``replacement`` is the owner-changing operation B, executed while A is parked.
    """
    started = threading.Event()
    release = threading.Event()
    cast(FastAPI, client.app).state.anthropic_http_factory = _token_factory(
        _STALE_TOKEN, stall=release, started=started
    )
    service = _service(client)

    with ThreadPoolExecutor(max_workers=1) as executor:
        refresh_a = executor.submit(client.post, _REFRESH_URL)
        assert started.wait(5), "refresh A never reached the provider token call"
        replacement()
        release.set()
        response_a = refresh_a.result(timeout=10)

    profile, generation = _durable(client)
    content_type = response_a.headers.get("content-type", "")
    return _Observed(
        status=response_a.status_code,
        body=response_a.json() if content_type.startswith("application/json") else {},
        blob=_read_blob(client, service),
        profile=profile,
        generation=generation,
    )


def _read_blob(client: TestClient, service: str) -> str | None:
    probe = getattr(client, "_credential_probe", None)
    assert probe is not None, "the schedule helper needs the credential probe attached"
    return probe.read(service, "default")


def _replace_with_api_key(client: TestClient) -> None:
    response = client.put(_API_KEY_URL, json={"api_key": _REPLACEMENT_KEY})
    assert response.status_code == 200, response.text


def _reauthenticate_with_oauth(client: TestClient) -> None:
    cast(FastAPI, client.app).state.anthropic_http_factory = _token_factory("oauth-B-token")
    start = client.post("/v1/auth/anthropic/profiles", json={"name": _PROFILE})
    assert start.status_code == 201, start.text
    callback = client.get(
        "/v1/auth/anthropic/callback",
        params={"code": "code-B", "state": start.json()["state"]},
        follow_redirects=False,
    )
    assert callback.status_code == 200, callback.text


def _delete_the_profile(client: TestClient) -> None:
    response = client.delete(_PROFILE_URL)
    assert response.status_code == 204, response.text


# ── schedule 1: an API-key replacement wins ───────────────────────────────────


@pytest.fixture
def oauth_client(
    authenticated_client: TestClient, credential_blobs: Any, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    """An authenticated OAuth profile, with the credential probe attached for reads."""
    _accept_api_keys(monkeypatch)
    _authenticate_oauth_profile(authenticated_client)
    authenticated_client._credential_probe = credential_blobs  # noqa: SLF001 - test wiring
    return authenticated_client


def test_a_stale_refresh_is_refused_deterministically(oauth_client: TestClient) -> None:
    """The headline: A loses, with a stable machine-readable code and no 500."""
    observed = _run_stale_refresh_against(oauth_client, lambda: _replace_with_api_key(oauth_client))

    assert observed.status == 409, (observed.status, observed.body)
    assert observed.body["detail"]["code"] == "credential_owner_changed", observed.body


def test_a_stale_refresh_cannot_overwrite_the_replacement_credential(
    oauth_client: TestClient,
) -> None:
    """Step 4 of the schedule: A's refreshed token must never reach the durable blob."""
    observed = _run_stale_refresh_against(oauth_client, lambda: _replace_with_api_key(oauth_client))

    assert observed.blob is not None, "the replacement's credential vanished"
    assert _REPLACEMENT_KEY in observed.blob, observed.blob[:40]
    assert _STALE_TOKEN not in observed.blob


def test_a_stale_refresh_cannot_restore_the_previous_owner_metadata(
    oauth_client: TestClient,
) -> None:
    """Step 6: the profile row must still describe owner B, auth type included."""
    observed = _run_stale_refresh_against(oauth_client, lambda: _replace_with_api_key(oauth_client))

    assert observed.profile is not None
    assert observed.profile["auth_type"] == "api_key", observed.profile
    assert observed.profile["state"] == "authenticated", observed.profile
    assert observed.profile["account_label"] == "API key ····WXYZ", observed.profile


def test_a_stale_refresh_cannot_rewind_the_ownership_generation(
    oauth_client: TestClient,
) -> None:
    """The generation is the private cache's fence, so it must stay at B's value."""
    before, generation_before = _durable(oauth_client)
    assert before is not None

    observed = _run_stale_refresh_against(oauth_client, lambda: _replace_with_api_key(oauth_client))

    assert observed.generation == generation_before + 1, (generation_before, observed.generation)


def test_a_stale_refresh_does_not_retire_the_replacement_private_listing(
    oauth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused refresh must not cost B a re-dial with B's own credential."""
    http = _enable_private_discovery(oauth_client, monkeypatch)

    observed = _run_stale_refresh_against(oauth_client, lambda: _replace_with_api_key(oauth_client))
    assert observed.status == 409, observed.body
    drain_private_catalog(oauth_client)
    warm = oauth_client.get(_LISTING_URL)
    assert warm.status_code == 200, warm.text
    assert warm.json()["status"] == "fresh", warm.json()
    dials = http.dials

    again = oauth_client.get(_LISTING_URL)

    assert again.json()["status"] == "fresh", again.json()
    assert http.dials == dials, "the refused refresh retired a listing it does not own"


# ── schedule 2 and 3: re-authentication and delete also win ───────────────────


def test_an_oauth_reauthentication_wins_against_a_stale_refresh(
    oauth_client: TestClient,
) -> None:
    """B re-authenticates the same profile: B's tokens and generation must survive."""
    _before, generation_before = _durable(oauth_client)

    observed = _run_stale_refresh_against(
        oauth_client, lambda: _reauthenticate_with_oauth(oauth_client)
    )

    assert observed.status == 409, (observed.status, observed.body)
    assert observed.blob is not None
    assert "oauth-B-token" in observed.blob, observed.blob[:60]
    assert _STALE_TOKEN not in observed.blob
    assert observed.generation > generation_before
    assert observed.profile is not None and observed.profile["auth_type"] == "oauth"


def test_a_delete_wins_against_a_stale_refresh(oauth_client: TestClient) -> None:
    """A deleted profile must not be resurrected, and no orphan credential left."""
    observed = _run_stale_refresh_against(oauth_client, lambda: _delete_the_profile(oauth_client))

    assert observed.status == 409, (observed.status, observed.body)
    assert observed.profile is None, observed.profile
    assert observed.blob is None, "the stale refresh resurrected a deleted credential"
    assert oauth_client.get(_PROFILE_URL).status_code == 404


# ── the uncontended path must not regress ─────────────────────────────────────


def test_an_uncontended_same_owner_refresh_still_succeeds(oauth_client: TestClient) -> None:
    """The fence must not break the ordinary case it exists to protect."""
    cast(FastAPI, oauth_client.app).state.anthropic_http_factory = _token_factory("oauth-A-2")

    response = oauth_client.post(_REFRESH_URL)

    assert response.status_code == 200, response.text
    blob = _read_blob(oauth_client, _service(oauth_client))
    assert blob is not None and "oauth-A-2" in blob, "the refreshed token was not published"


def test_an_uncontended_refresh_does_not_bump_the_ownership_generation(
    oauth_client: TestClient,
) -> None:
    """Owner decision 6: a routine same-owner refresh is not an ownership event."""
    _before, generation_before = _durable(oauth_client)
    cast(FastAPI, oauth_client.app).state.anthropic_http_factory = _token_factory("oauth-A-2")

    assert oauth_client.post(_REFRESH_URL).status_code == 200

    _after, generation_after = _durable(oauth_client)
    assert generation_after == generation_before, (generation_before, generation_after)


def test_an_uncontended_refresh_keeps_the_private_listing_warm(
    oauth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same-owner refresh keeps a snapshot that is still exactly correct."""
    _accept_api_keys(monkeypatch)
    http = _enable_private_discovery(oauth_client, monkeypatch)
    _replace_with_api_key(oauth_client)
    drain_private_catalog(oauth_client)
    assert oauth_client.get(_LISTING_URL).json()["status"] == "fresh"
    dials = http.dials

    assert oauth_client.post(_REFRESH_URL).status_code == 200

    assert oauth_client.get(_LISTING_URL).json()["status"] == "fresh"
    assert http.dials == dials, "a same-owner refresh must not force a re-dial"


# ── cancellation before publication ───────────────────────────────────────────


def test_a_cancelled_refresh_changes_neither_durable_store(
    oauth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is persisted before the publication, so a cancellation leaves no trace.

    # INVARIANT: this is the reason the refreshed bytes are BUFFERED rather than written
    # during the provider call. A credential written mid-refresh would survive the
    # cancellation while the profile row did not — exactly the split state the OME-307
    # publication ordering exists to prevent.
    """
    from aigateway.plugins.anthropic_provider.auth import AnthropicOAuth

    service = _service(oauth_client)
    blob_before = _read_blob(oauth_client, service)
    profile_before, generation_before = _durable(oauth_client)

    async def _cancelled(self: Any, creds: dict) -> dict:
        # A refreshed credential is ready to publish, and then the request dies.
        await self._write_to_store({**creds, "access_token": _STALE_TOKEN})
        raise asyncio.CancelledError

    monkeypatch.setattr(AnthropicOAuth, "_refresh_credential", _cancelled)

    with _server_errors_as_responses(oauth_client):
        oauth_client.post(_REFRESH_URL)

    assert _read_blob(oauth_client, service) == blob_before, "a cancelled refresh persisted bytes"
    profile_after, generation_after = _durable(oauth_client)
    assert profile_after == profile_before
    assert generation_after == generation_before

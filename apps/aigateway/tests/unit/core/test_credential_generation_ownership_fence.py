"""OME-1026 final pass F3 — what ``credential_generation`` actually versions.

FEATURE: a private model catalog that can never be served across a change of the
credential's OWNER, and is not thrown away for no reason when it has not changed.

STORY: as a profile owner my model list survives my access token being refreshed in
the background, and is discarded the moment I replace the key or re-authenticate.

INVARIANT (the contract this file pins): ``credential_generation`` is an
OWNERSHIP/AUTHENTICATION fence, not a version of every refreshed access-token byte.
  * a routine OAuth token refresh for the SAME authenticated owner does NOT bump it;
  * API-key replacement, OAuth re-authentication, an auth-type switch and
    delete/recreate DO bump it, atomically with publication.

INVARIANT (why the narrower reading is the CORRECT one, not merely the cheaper one):
under "version every byte", a manual refresh had to write the credential blob and
then bump the index generation — two durable writes with no transaction around them.
A crash in between left a blob holding a new token while the cached snapshot's
identity still named the old generation. Making a routine refresh a non-event removes
the window instead of trying to make two writes atomic: the entitlements a catalog
describes belong to the OWNER, and rotating that owner's token does not change them.

AIDEV-NOTE: seed the index BEFORE the first HTTP call in each case. The app holds its
Tortoise connection on the TestClient's loop, so a write issued from pytest's loop
after a request has opened that connection blocks on SQLite's writer lock and the test
hangs rather than fails. Post-request reads and writes go through ``client.portal``.
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent import futures
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
from aigateway.core.oauth_base import BaseOAuthStrategy
from aigateway.core.parameter_discovery import DiscoveryLimits, RawResponse
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.anthropic_provider.live_models import MODELS_LIST_URL
from tests.conftest import drain_private_catalog

_NAME = "fenced"
_FIRST_PAGE = f"{MODELS_LIST_URL}?limit=1000"
_LISTING_URL = f"/v1/auth/anthropic/profiles/{_NAME}/models"
_REFRESH_URL = f"/v1/auth/anthropic/profiles/{_NAME}/refresh"
_API_KEY_URL = f"/v1/auth/anthropic/profiles/{_NAME}/api-key"
_KEY = "sk-ant-fence-kept"


class _Clock:
    def now(self) -> float:
        return 1_000.0


class _CountingCatalog:
    """The credentialed catalog dial, counted. Answers the same rows every time."""

    def __init__(self) -> None:
        self.dials: list[dict[str, str]] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        assert url == _FIRST_PAGE, url
        assert headers, "a private catalog dial must carry a credential"
        self.dials.append(dict(headers))
        body = json.dumps({"data": [{"id": "claude-fenced-1", "type": "model"}], "has_more": False})
        return RawResponse(status=200, content_type="application/json", body=body)


def _token_factory():
    """An OAuth token endpoint that always mints a DIFFERENT access token."""
    minted = {"n": 0}

    def _respond(_request: httpx.Request) -> httpx.Response:
        minted["n"] += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"rotated-tok-{minted['n']}",
                "refresh_token": f"rotated-rt-{minted['n']}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    transport = httpx.MockTransport(_respond)
    return lambda: httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))


def _account_id(client: TestClient) -> str:
    return client.get("/v1/auth/me").json()["id"]


async def _seed_oauth_profile(credential_blobs: Any, account_id: str, *, name: str = _NAME) -> None:
    """An AUTHENTICATED oauth profile whose token is already expired."""
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, name)),
        "default",
        json.dumps(
            {
                "access_token": "original-tok",
                "refresh_token": "original-rt",
                "expires_at_ms": int(time.time() * 1000) - 60_000,
                "token_type": "Bearer",
            }
        ),
    )
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", name),
            account_id=account_id,
            provider="anthropic",
            name=name,
            state=ProfileState.AUTHENTICATED,
            auth_type="oauth",
        )
    )


def _generation(client: TestClient, credential_blobs: Any, account_id: str, name: str = _NAME):
    """The DURABLE generation, read through the app's own loop (see module note)."""

    async def _read() -> int | None:
        store = ProfileIndexStore(credential_store=credential_blobs.store)
        found = await store.get_with_credential_generation(account_id, "anthropic", name)
        return None if found is None else found[1]

    portal = client.portal
    assert portal is not None
    return portal.call(_read)


def _blob(credential_blobs: Any, account_id: str, name: str = _NAME) -> dict[str, Any] | None:
    raw = credential_blobs.read(
        credential_service_for(credential_name_for(account_id, name)), "default"
    )
    return None if raw is None else json.loads(raw)


def _stored_token(credential_blobs: Any, account_id: str, name: str = _NAME) -> str | None:
    blob = _blob(credential_blobs, account_id, name)
    return None if blob is None else blob["access_token"]


def _stored_api_key(credential_blobs: Any, account_id: str, name: str = _NAME) -> str | None:
    blob = _blob(credential_blobs, account_id, name)
    return None if blob is None else blob["api_key"]


def _accept_any_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _valid(_self: Any, _plugin: Any, _provider: Any, _api_key: Any):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


# ── a routine refresh is not an ownership change ──────────────────────────────


@pytest.mark.asyncio
async def test_a_no_op_api_key_refresh_does_not_bump_the_generation(
    credential_blobs: Any, authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sharpest form of the defect: a PROVABLY no-op refresh invalidated the cache.

    ``ApiKeyStrategy.refresh_credentials`` only re-reads the stored key — a raw key
    cannot be refreshed, only replaced. The credential is byte-identical afterwards, so
    a generation bump here can only mean "throw away a still-valid catalog".
    """
    _accept_any_api_key(monkeypatch)
    assert authenticated_client.put(_API_KEY_URL, json={"api_key": _KEY}).status_code == 200
    account_id = _account_id(authenticated_client)
    before = _generation(authenticated_client, credential_blobs, account_id)

    refreshed = authenticated_client.post(_REFRESH_URL)

    assert refreshed.status_code == 200, refreshed.text
    assert _stored_api_key(credential_blobs, account_id) == _KEY, "the credential is unchanged"
    assert _generation(authenticated_client, credential_blobs, account_id) == before


@pytest.mark.asyncio
async def test_a_no_op_refresh_keeps_serving_the_same_owners_snapshot(
    credential_blobs: Any,
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    anthropic_live_discovery: Any,
) -> None:
    """The payoff: the cached catalog survives a refresh. ONE upstream fetch, total.

    # WHY this is the test that matters: the generation is not an accounting figure, it
    # is a CACHE KEY. "Does not bump" is only meaningful if the snapshot filed under the
    # old value is still the one served afterwards.
    """
    _accept_any_api_key(monkeypatch)
    app = cast(FastAPI, authenticated_client.app)
    http = _CountingCatalog()
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(timeout_s=1.0),
    )
    assert authenticated_client.put(_API_KEY_URL, json={"api_key": _KEY}).status_code == 200
    drain_private_catalog(authenticated_client)
    warm = authenticated_client.get(_LISTING_URL).json()
    assert warm["status"] == "fresh", warm
    assert len(http.dials) == 1, http.dials

    assert authenticated_client.post(_REFRESH_URL).status_code == 200
    drain_private_catalog(authenticated_client)

    after = authenticated_client.get(_LISTING_URL).json()
    assert after["status"] == "fresh", after
    assert [row["id"] for row in after["data"]] == ["anthropic/claude-fenced-1"], after
    assert len(http.dials) == 1, "a no-op refresh must not re-dial the same owner's catalog"


@pytest.mark.asyncio
async def test_a_routine_oauth_token_refresh_does_not_bump_the_generation(
    credential_blobs: Any, authenticated_client: TestClient
) -> None:
    """The same rule where the token really does rotate.

    # AIDEV-NOTE: no cache assertion here — Anthropic's private discovery declares
    # ``unsupported_auth_type`` for oauth profiles, so an oauth profile has no private
    # catalog to preserve. The generation contract still has to hold for it, because it
    # is the profile index's contract and not one provider's.
    """
    account_id = _account_id(authenticated_client)
    await _seed_oauth_profile(credential_blobs, account_id)
    cast(FastAPI, authenticated_client.app).state.anthropic_http_factory = _token_factory()
    before = _generation(authenticated_client, credential_blobs, account_id)

    refreshed = authenticated_client.post(_REFRESH_URL)

    assert refreshed.status_code == 200, refreshed.text
    # The token really rotated — this is not a no-op passing by accident.
    assert _stored_token(credential_blobs, account_id) == "rotated-tok-1"
    assert _generation(authenticated_client, credential_blobs, account_id) == before


@pytest.mark.asyncio
async def test_a_crash_after_the_credential_write_leaves_no_half_published_identity(
    credential_blobs: Any, authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancellation schedule the split write used to lose data on.

    The worker dies AFTER the provider handed over the rotated token and BEFORE the
    route published anything. Adversarial B2 replaced the split write with a buffered
    one, so that token was never made durable: a death before publication leaves the
    store exactly as it was — previous token, same owner, same generation, profile still
    AUTHENTICATED. Nothing is half-published because nothing was published at all.
    """
    account_id = _account_id(authenticated_client)
    await _seed_oauth_profile(credential_blobs, account_id)
    cast(FastAPI, authenticated_client.app).state.anthropic_http_factory = _token_factory()
    before = _generation(authenticated_client, credential_blobs, account_id)
    real_refresh = BaseOAuthStrategy.refresh_credentials

    async def _write_then_die(self: Any) -> None:
        await real_refresh(self)
        raise asyncio.CancelledError("worker killed after the credential write")

    monkeypatch.setattr(BaseOAuthStrategy, "refresh_credentials", _write_then_die)

    # AIDEV-NOTE: the portal marshals the app loop's cancellation across the thread
    # boundary as ``concurrent.futures.CancelledError``, which in 3.12 is a DISTINCT
    # class from ``asyncio.CancelledError`` (an ``Exception``, not a ``BaseException``).
    # Both are accepted so this pins the schedule rather than TestClient's plumbing.
    with pytest.raises((asyncio.CancelledError, futures.CancelledError)):
        authenticated_client.post(_REFRESH_URL)

    assert _stored_token(credential_blobs, account_id) == "original-tok", (
        "the buffered token never became durable"
    )
    assert _generation(authenticated_client, credential_blobs, account_id) == before
    profile = authenticated_client.get(f"/v1/auth/anthropic/profiles/{_NAME}").json()
    assert profile["state"] == "authenticated", profile


# ── an ownership change must bump, atomically with publication ────────────────


@pytest.mark.asyncio
async def test_an_api_key_replacement_bumps_the_generation(
    credential_blobs: Any, authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _accept_any_api_key(monkeypatch)

    first = authenticated_client.put(_API_KEY_URL, json={"api_key": "sk-ant-fence-1"})
    assert first.status_code == 200, first.text
    account_id = _account_id(authenticated_client)
    before = _generation(authenticated_client, credential_blobs, account_id)

    second = authenticated_client.put(_API_KEY_URL, json={"api_key": "sk-ant-fence-2"})

    assert second.status_code == 200, second.text
    after = _generation(authenticated_client, credential_blobs, account_id)
    assert before is not None and after is not None and after > before


@pytest.mark.asyncio
async def test_an_auth_type_switch_bumps_the_generation(
    credential_blobs: Any, authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """oauth → api_key is a new credential owner even at the same profile name."""
    _accept_any_api_key(monkeypatch)
    account_id = _account_id(authenticated_client)
    await _seed_oauth_profile(credential_blobs, account_id)
    before = _generation(authenticated_client, credential_blobs, account_id)

    switched = authenticated_client.put(_API_KEY_URL, json={"api_key": "sk-ant-switched"})

    assert switched.status_code == 200, switched.text
    after = _generation(authenticated_client, credential_blobs, account_id)
    assert before is not None and after is not None and after > before


@pytest.mark.asyncio
async def test_a_failed_api_key_publication_bumps_nothing(
    credential_blobs: Any, authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The atomicity claim: the bump and the credential write are ONE transaction.

    # WHY it must be all-or-nothing: a bump that committed without its credential
    # would retire the cached snapshot in favour of a generation whose credential is
    # the OLD one — a needless refetch at best, and at worst a cache identity that no
    # write will ever fill.
    """
    _accept_any_api_key(monkeypatch)
    assert (
        authenticated_client.put(_API_KEY_URL, json={"api_key": "sk-ant-keep"}).status_code == 200
    )
    account_id = _account_id(authenticated_client)
    before = _generation(authenticated_client, credential_blobs, account_id)

    from aigateway.routes import auth as auth_routes

    async def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("credential write failed inside the transaction")

    monkeypatch.setattr(auth_routes, "persist_credentials_or_503", _explode)

    with pytest.raises(RuntimeError):
        authenticated_client.put(_API_KEY_URL, json={"api_key": "sk-ant-never-lands"})

    assert _generation(authenticated_client, credential_blobs, account_id) == before


def test_an_oauth_reauthentication_bumps_the_generation(
    credential_blobs: Any, authenticated_client: TestClient
) -> None:
    """A completed OAuth round-trip replaces the owner, so it must fence."""
    client = authenticated_client
    cast(FastAPI, client.app).state.anthropic_http_factory = _token_factory()
    account_id = _account_id(client)
    started = client.post("/v1/auth/anthropic/profiles", json={"name": _NAME})
    assert started.status_code == 201, started.text
    before = _generation(client, credential_blobs, account_id)

    header = client.headers.pop("Authorization")
    try:
        callback = client.get(
            "/callback",
            params={"code": "auth-code-fence", "state": started.json()["state"]},
            follow_redirects=False,
        )
    finally:
        client.headers["Authorization"] = header
    assert callback.status_code == 200, callback.text

    after = _generation(client, credential_blobs, account_id)
    assert before is not None and after is not None and after > before

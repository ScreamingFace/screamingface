"""OME-632: the detail ROUTE serves Gemini's live schema evidence — api-key only.

FEATURE: auth-correct dynamic evidence, end to end. The projection is pinned by
``test_gemini_schema_evidence``; this proves the seam — that the route binds the
RESOLVED auth mode before observing, so the public document reaches the api-key
contract and never the Code Assist one.

INVARIANT: the runtime is driven through an INJECTED client. No test reaches
Google (the suite-wide egress guard in ``conftest`` fails loudly if one tries),
and the model reaching discovery is one the canonical inventory already validated.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.auth_types import AuthType
from aigateway.core.credential_names import profile_id_for
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    RawResponse,
)
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState

_PROVIDER = "gemini-cli"
_MODEL = "gemini-cli/gemini-2.5-pro"

# `candidateCount` is absent and `responseMimeType` is present — the two cells that
# make the api-key contract observably different from the Code Assist one.
_DOC: dict[str, Any] = {
    "schemas": {
        "GenerateContentRequest": {
            "properties": {"generationConfig": {"$ref": "GenerationConfig"}}
        },
        "GenerationConfig": {
            "properties": {
                "temperature": {"type": "number"},
                "topP": {"type": "number"},
                "topK": {"type": "integer"},
                "maxOutputTokens": {"type": "integer"},
                "stopSequences": {"type": "array", "items": {"type": "string"}},
                "frequencyPenalty": {"type": "number"},
                "presencePenalty": {"type": "number"},
                "seed": {"type": "integer"},
                "responseMimeType": {"type": "string"},
            }
        },
    }
}


class _DiscoveryClient(DiscoveryHttpClient):
    """Injected transport: serves the fixture document, or fails on demand."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        return RawResponse(status=200, content_type="application/json", body=json.dumps(_DOC))


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _install_runtime(client: TestClient, discovery_client: _DiscoveryClient, clock: _Clock) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=discovery_client,
        cache=ObservationCache(
            clock=clock, limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


async def _seed_profile(credential_blobs, account_id: str, *, auth_type: AuthType) -> None:
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, _PROVIDER, "default"),
            account_id=account_id,
            provider=_PROVIDER,
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type=auth_type,
        )
    )


async def _contract(credential_blobs, client: TestClient, *, auth_type: AuthType) -> dict:
    account_id = client.get("/v1/auth/me").json()["id"]
    await _seed_profile(credential_blobs, account_id, auth_type=auth_type)
    resp = client.get("/v1/model-parameters", params={"model": _MODEL})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- the api-key path observes ------------------------------------------------


@pytest.mark.asyncio
async def test_an_api_key_read_reports_live_schema_evidence(
    authenticated_client, credential_blobs
) -> None:
    _install_runtime(authenticated_client, _DiscoveryClient(), _Clock())

    body = await _contract(credential_blobs, authenticated_client, auth_type="api_key")

    assert body["parameters"]["temperature"]["provider"]["source"] == "gemini:discovery"
    assert body["parameters"]["temperature"]["provider"]["stale"] is False
    assert body["freshness"]["observed_at"] is not None
    assert body["freshness"]["degraded"] is False


@pytest.mark.asyncio
async def test_a_field_the_live_schema_dropped_is_reported_unsupported(
    authenticated_client, credential_blobs
) -> None:
    # THE reason this unit exists: the reviewed list still names `candidateCount`,
    # and the document no longer declares it. The contract now says so instead of
    # repeating our own constant back to the caller.
    _install_runtime(authenticated_client, _DiscoveryClient(), _Clock())

    body = await _contract(credential_blobs, authenticated_client, auth_type="api_key")

    assert body["parameters"]["provider_params.candidateCount"]["provider"]["support"] == (
        "unsupported"
    )


# --- the OAuth path does not ---------------------------------------------------


@pytest.mark.asyncio
async def test_an_oauth_read_never_dials_the_public_document(
    authenticated_client, credential_blobs
) -> None:
    discovery = _DiscoveryClient()
    _install_runtime(authenticated_client, discovery, _Clock())

    body = await _contract(credential_blobs, authenticated_client, auth_type="oauth")

    assert discovery.calls == []
    assert body["parameters"]["temperature"]["provider"]["source"] == "gemini:code-assist"


@pytest.mark.asyncio
async def test_an_oauth_read_publishes_the_never_observed_window(
    authenticated_client, credential_blobs
) -> None:
    # Not degraded — nothing failed. This upstream simply publishes no schema, and
    # its reviewed evidence is as good as it will ever be.
    _install_runtime(authenticated_client, _DiscoveryClient(), _Clock())

    body = await _contract(credential_blobs, authenticated_client, auth_type="oauth")

    assert body["freshness"] == {
        "observed_at": None,
        "expires_at": None,
        "stale": False,
        "degraded": False,
    }


@pytest.mark.asyncio
async def test_public_evidence_never_leaks_into_the_code_assist_contract(
    authenticated_client, credential_blobs
) -> None:
    # `responseMimeType` exists only in the public document. Its appearance on the
    # OAuth contract would mean we had inferred one upstream's surface from another.
    _install_runtime(authenticated_client, _DiscoveryClient(), _Clock())

    body = await _contract(credential_blobs, authenticated_client, auth_type="oauth")

    assert "provider_params.responseMimeType" not in body["parameters"]


# --- the policy axis does not move --------------------------------------------


@pytest.mark.asyncio
async def test_the_gateway_projection_is_identical_under_both_modes(
    authenticated_client, credential_blobs
) -> None:
    # Evidence axis only: Gemini's rules apply under both auth modes, so every
    # shared path must carry the same gateway decision whichever mode was read.
    _install_runtime(authenticated_client, _DiscoveryClient(), _Clock())
    with_key = await _contract(credential_blobs, authenticated_client, auth_type="api_key")
    with_oauth = await _contract(credential_blobs, authenticated_client, auth_type="oauth")

    shared = set(with_key["parameters"]) & set(with_oauth["parameters"])
    assert {p: with_key["parameters"][p]["gateway"] for p in shared} == {
        p: with_oauth["parameters"][p]["gateway"] for p in shared
    }


@pytest.mark.asyncio
async def test_the_models_summary_does_not_move(authenticated_client, credential_blobs) -> None:
    # The inline summary is served without discovery at all; a dropped field must
    # not silently shrink it, because only a rule authorizes dispatch.
    _install_runtime(authenticated_client, _DiscoveryClient(), _Clock())
    before = {r["id"]: r for r in authenticated_client.get("/v1/models").json()["data"]}[_MODEL]

    await _contract(credential_blobs, authenticated_client, auth_type="api_key")

    after = {r["id"]: r for r in authenticated_client.get("/v1/models").json()["data"]}[_MODEL]
    assert after["supported_parameters"] == before["supported_parameters"]


# --- degradation ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_outage_degrades_to_the_reviewed_static_evidence(
    authenticated_client, credential_blobs
) -> None:
    # No last-good value to fall back on: the contract must still serve, from the
    # reviewed labelled-static evidence, and say so — never a fabricated negative.
    _install_runtime(
        authenticated_client, _DiscoveryClient(error=DiscoveryError("unreachable")), _Clock()
    )

    body = await _contract(credential_blobs, authenticated_client, auth_type="api_key")

    assert body["freshness"]["degraded"] is True
    assert body["parameters"]["provider_params.candidateCount"]["provider"]["support"] == (
        "supported"
    )


@pytest.mark.asyncio
async def test_the_stale_window_serves_the_last_good_verdict_flagged(
    authenticated_client, credential_blobs
) -> None:
    # fresh read → TTL expiry → outage: the observed negative still stands, but the
    # client is told it is stale rather than being handed a silent fabrication.
    clock = _Clock()
    _install_runtime(authenticated_client, _DiscoveryClient(), clock)
    fresh = await _contract(credential_blobs, authenticated_client, auth_type="api_key")
    assert fresh["parameters"]["provider_params.candidateCount"]["provider"]["stale"] is False

    runtime: DiscoveryRuntime = cast(FastAPI, authenticated_client.app).state.discovery_runtime
    # swap ONLY the transport, keeping the warm cache — that is the outage shape.
    runtime._client = _DiscoveryClient(error=DiscoveryError("unreachable"))  # noqa: SLF001
    clock.advance(61.0)

    stale = await _contract(credential_blobs, authenticated_client, auth_type="api_key")

    assert stale["freshness"]["stale"] is True
    assert stale["parameters"]["provider_params.candidateCount"]["provider"]["support"] == (
        "unsupported"
    )
    assert stale["parameters"]["provider_params.candidateCount"]["provider"]["stale"] is True

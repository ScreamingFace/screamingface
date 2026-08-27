"""OME-647: the OpenAPI endpoint source as the ROUTE actually serves it.

FEATURE: OpenRouter's source pair, reaching a client. The parser half is covered in
``test_openrouter_openapi_endpoint_source``; these tests walk the real
``/v1/model-parameters`` route with an injected discovery runtime.

WHY this is a separate concern and not more parser tests:
``parse_openapi_endpoint_observations`` returns () for a schema name it cannot find.
A wiring that used the wrong component name would raise nothing, log nothing, and
pass every fixture test in the parser file while publishing an empty endpoint
source. Only a test that walks the real route can catch that.

INVARIANT (evidence only): a schema published here describes what the ENDPOINT
accepts and a deprecation verdict describes what the PROVIDER declares. Neither
enables a parameter, moves gateway.status, changes the /v1/models summary, or
touches dispatch — only a rule does.
INVARIANT (§5.2): every fetch goes through the bounded transport under an INJECTED
client. No test in this file reaches the network.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.chat_parameters import ProviderParameterObservation
from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import DiscoveryHttpClient, DiscoveryLimits
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.plugins.openrouter_provider.discovery import MODELS_URL, OPENAPI_URL
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings

from ._openapi_document import _CATALOG, _MODEL, _OPENAPI, _RoutingClient

# --- production wiring: the route, not a fixture -----------------------------
#
# WHY this section exists: `parse_openapi_endpoint_observations` returns () for a
# schema name it cannot find. A wiring that used the wrong component name would
# raise nothing, log nothing, and pass every fixture test above while publishing an
# empty endpoint source. Only a test that walks the real route can catch that.


@pytest.fixture
def openrouter_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # patches the singleton INSTANCE, not the environment: `load_plugins` hands the
    # same object to every app, so env vars set after import cannot reach it.
    from aigateway.plugins.openrouter_provider import plugin as plugin_module

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        # OME-972 setup-only amendment: this suite pins the OpenAPI-source
        # decision surface, not live listing discovery. Assertions untouched.
        OpenRouterPluginSettings(enabled=True, live_models=False, default_models=[_MODEL]),
    )


def _install_runtime(client: TestClient, http: DiscoveryHttpClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=http,
        cache=ObservationCache(
            clock=_Clock(), limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


class _Clock:
    def now(self) -> float:
        return 1000.0


async def _contract(credential_blobs, client: TestClient) -> dict[str, Any]:
    account_id = client.get("/v1/auth/me").json()["id"]
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "openrouter", "default"),
            account_id=account_id,
            provider="openrouter",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )
    resp = client.get("/v1/model-parameters", params={"model": _MODEL})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_the_route_publishes_evidence_sourced_from_the_openapi_document(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    _install_runtime(
        authenticated_client, _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    )
    body = await _contract(credential_blobs, authenticated_client)
    sources = {row["provider"]["source"] for row in body["parameters"].values()}
    assert "openrouter:openapi" in sources


@pytest.mark.asyncio
async def test_the_route_publishes_the_declared_shape_of_an_unprojected_field(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # service_tier has no gateway rule, so this row is visible-but-DISABLED — and the
    # endpoint schema is the only shape a client can see for it.
    _install_runtime(
        authenticated_client, _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    )
    row = (await _contract(credential_blobs, authenticated_client))["parameters"]["service_tier"]
    assert row["gateway"]["status"] == "disabled"
    assert row["gateway"]["reason"] == "projection_not_implemented"
    assert row["schema"] == {"type": "string", "enum": ["auto", "default", "flex"]}


@pytest.mark.asyncio
async def test_the_route_publishes_the_providers_deprecation_verdict(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    _install_runtime(
        authenticated_client, _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    )
    params = (await _contract(credential_blobs, authenticated_client))["parameters"]
    assert params["route"]["provider"]["deprecated"] is True
    assert params["temperature"]["provider"]["deprecated"] is False


@pytest.mark.asyncio
async def test_a_gateway_owned_rule_schema_still_outranks_the_endpoints(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # the endpoint declares a bare `{"type": "number"}` for temperature; the gateway's
    # own rule carries the bounds it VALIDATES against. Evidence must never displace
    # the schema the gateway actually enforces.
    _install_runtime(
        authenticated_client, _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    )
    row = (await _contract(credential_blobs, authenticated_client))["parameters"]["temperature"]
    assert row["gateway"]["status"] == "enabled"
    assert row["schema"]["maximum"] is not None


def test_the_source_revision_and_lifecycle_both_reach_contract_identity() -> None:
    """Reading DIFFERENT documents must move the opaque ids, even byte-for-byte.

    Two distinct inputs, one property: a contract_id that did not move would tell a
    client "nothing changed" while the evidence underneath it came from a different
    source, or carried a lifecycle verdict it did not carry before.
    """
    from aigateway.core.model_parameter_contract import build_model_parameter_document

    def _document(*, source_revision: str, deprecated: bool | None) -> dict[str, Any]:
        return build_model_parameter_document(
            canonical_id=_MODEL,
            gateway_provider="openrouter",
            auth_mode="api_key",
            scope="account_profile",
            context_identity="acct:test|prof:1",
            rules=(),
            observations=(
                ProviderParameterObservation(
                    request_path="route",
                    support="supported",
                    source="openrouter:openapi",
                    deprecated=deprecated,
                ),
            ),
            tools=(),
            transport=(),
            freshness={"stale": False, "degraded": False},
            source_revision=source_revision,
        )

    baseline = _document(source_revision="rev-a", deprecated=False)

    # 1. the source pair changed; the observations are byte-identical.
    moved_source = _document(source_revision="rev-b", deprecated=False)
    assert moved_source["contract_id"] != baseline["contract_id"]
    assert moved_source["context"]["revision"] != baseline["context"]["revision"]

    # 2. the lifecycle verdict changed; everything else is identical. Both
    #    transitions count — including the one OUT of silence, which is why the
    #    tri-state is encoded distinctly rather than collapsed to a bool.
    for verdict in (True, None):
        moved_lifecycle = _document(source_revision="rev-a", deprecated=verdict)
        assert moved_lifecycle["contract_id"] != baseline["contract_id"], verdict
        assert moved_lifecycle["context"]["revision"] != baseline["context"]["revision"], verdict


@pytest.mark.asyncio
async def test_the_new_source_moves_no_gateway_decision(
    openrouter_enabled, authenticated_client, credential_blobs
) -> None:
    # F12 semantics, owner-locked: dynamic observations move the EVIDENCE axis only.
    # A deprecated, endpoint-observed `route` must not become dispatchable, and the
    # summary must not learn anything from a document the gateway merely read.
    _install_runtime(
        authenticated_client, _RoutingClient({MODELS_URL: _CATALOG, OPENAPI_URL: _OPENAPI})
    )
    params = (await _contract(credential_blobs, authenticated_client))["parameters"]
    assert params["route"]["gateway"]["status"] == "disabled"

    row = next(
        r for r in authenticated_client.get("/v1/models").json()["data"] if r["id"] == _MODEL
    )
    assert set(row["supported_parameters"]).isdisjoint({"route", "service_tier", "tool_choice_x"})

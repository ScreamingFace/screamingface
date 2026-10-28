"""OME-631: the detail ROUTE carries the observed HF backend verdict, consistently.

FEATURE: per-backend capability evidence, end to end. The pure projection is pinned
by ``test_huggingface_backend_evidence``; this proves the seam — that
``/v1/model-parameters`` folds the runtime's snapshot into BOTH the parameters and
the tools section, which is the only thing that makes one document self-consistent.

INVARIANT: the runtime is driven through an INJECTED client. No test reaches the
public router (the suite-wide egress guard in ``conftest`` fails loudly if one
tries), and the models reaching discovery are ones the canonical inventory
already validated.
"""

from __future__ import annotations

import json
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigateway.core.discovery_runtime import DiscoveryRuntime
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryHttpClient,
    DiscoveryLimits,
    RawResponse,
)
from aigateway.core.parameter_discovery_cache import CacheLimits, ObservationCache
from aigateway.plugins.huggingface_provider.settings import HuggingFacePluginSettings

_NO_TOOLS = "huggingface/meta-llama/Llama-3.1-8B-Instruct:nscale"
_NO_JSON = "huggingface/openai/gpt-oss-120b:cerebras"

_CATALOG = {
    "data": [
        {
            "id": "meta-llama/Llama-3.1-8B-Instruct",
            "providers": [
                {
                    "provider": "nscale",
                    "supports_tools": False,
                    "supports_structured_output": True,
                }
            ],
        },
        {
            "id": "openai/gpt-oss-120b",
            "providers": [
                {
                    "provider": "cerebras",
                    "supports_tools": True,
                    "supports_structured_output": False,
                }
            ],
        },
    ]
}


class _RouterClient(DiscoveryHttpClient):
    """Injected transport: serves the fixture catalog, or fails on demand."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        return RawResponse(status=200, content_type="application/json", body=json.dumps(_CATALOG))


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def huggingface_seeded(monkeypatch) -> None:
    """Seed exactly the two models the fixture catalog holds.

    # WHY: patches the plugin INSTANCE, not the environment — ``PLUGIN`` is a
    # module-level singleton built at import time, so ``AIGW_HUGGINGFACE_*`` set
    # after any test has imported the module cannot reach it.
    """
    from aigateway.plugins.huggingface_provider import plugin as plugin_module

    monkeypatch.setattr(
        plugin_module.PLUGIN,
        "settings",
        HuggingFacePluginSettings(default_models=[_NO_TOOLS, _NO_JSON]),
    )


def _install_runtime(client: TestClient, router_client: _RouterClient, clock: _Clock) -> None:
    app = cast(FastAPI, client.app)
    app.state.discovery_runtime = DiscoveryRuntime(
        client=router_client,
        cache=ObservationCache(
            clock=clock, limits=CacheLimits(ttl_s=60.0, stale_ttl_s=120.0, max_entries=8)
        ),
        limits=DiscoveryLimits(),
    )


async def _contract(client: TestClient, model: str) -> dict:
    resp = client.get("/v1/model-parameters", params={"model": model})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_the_route_serves_the_seeded_huggingface_models(
    huggingface_seeded, authenticated_client, credential_blobs
) -> None:
    # Guards the precondition the rest of this module depends on: without these
    # models registered every assertion below would 404 and prove nothing.
    ids = {row["id"] for row in authenticated_client.get("/v1/models").json()["data"]}
    assert {_NO_TOOLS, _NO_JSON} <= ids


@pytest.mark.asyncio
async def test_all_three_tool_cells_agree_within_one_document(
    huggingface_seeded, authenticated_client
) -> None:
    # THE consistency requirement: `tools` and `tool_choice` are request paths and
    # `function` is a tool type, but they describe ONE capability. A document that
    # reported them differently would be self-contradictory.
    _install_runtime(authenticated_client, _RouterClient(), _Clock())

    body = await _contract(authenticated_client, _NO_TOOLS)

    assert body["parameters"]["tools"]["provider"]["support"] == "unsupported"
    assert body["parameters"]["tool_choice"]["provider"]["support"] == "unsupported"
    assert body["tools"]["function"]["provider_support"] == "unsupported"


@pytest.mark.asyncio
async def test_the_gateway_still_forwards_what_the_backend_lacks(
    huggingface_seeded, authenticated_client
) -> None:
    # Evidence axis only. The gateway's projection is unchanged, so dispatch keeps
    # behaving identically whether this read hit a warm cache, a cold one, or an
    # outage — only the reported provider evidence moves.
    _install_runtime(authenticated_client, _RouterClient(), _Clock())

    body = await _contract(authenticated_client, _NO_TOOLS)

    assert body["parameters"]["tools"]["gateway"]["status"] == "enabled"
    assert body["tools"]["function"]["gateway_status"] == "enabled"


@pytest.mark.asyncio
async def test_the_models_summary_does_not_move(huggingface_seeded, authenticated_client) -> None:
    # The inline summary is served without discovery at all; this pins that a
    # backend reporting no tool support cannot silently shrink it.
    _install_runtime(authenticated_client, _RouterClient(), _Clock())
    await _contract(authenticated_client, _NO_TOOLS)

    rows = {r["id"]: r for r in authenticated_client.get("/v1/models").json()["data"]}
    assert rows[_NO_TOOLS]["supported_tools"] == rows[_NO_JSON]["supported_tools"] == ["function"]


@pytest.mark.asyncio
async def test_two_backends_get_different_evidence_from_one_catalog(
    huggingface_seeded, authenticated_client
) -> None:
    _install_runtime(authenticated_client, _RouterClient(), _Clock())

    no_tools = await _contract(authenticated_client, _NO_TOOLS)
    no_json = await _contract(authenticated_client, _NO_JSON)

    assert no_tools["tools"]["function"]["provider_support"] == "unsupported"
    assert no_json["tools"]["function"]["provider_support"] == "supported"
    # …and the two flags stay independent: cerebras does tools, not JSON mode.
    assert no_json["parameters"]["response_format"]["provider"]["support"] == "unsupported"
    assert no_tools["parameters"]["response_format"]["provider"]["support"] == "supported"
    # the RULE projection is untouched: same statuses for every shared path.
    shared = set(no_tools["parameters"]) & set(no_json["parameters"])
    assert {p: no_tools["parameters"][p]["gateway"] for p in shared} == {
        p: no_json["parameters"][p]["gateway"] for p in shared
    }


@pytest.mark.asyncio
async def test_a_router_outage_degrades_to_labelled_static_evidence(
    huggingface_seeded, authenticated_client
) -> None:
    # No last-good value to fall back on: the contract must still serve, from the
    # provider's reviewed labelled-static evidence, and say so — never a fabricated
    # negative and never an emptied tools section.
    _install_runtime(
        authenticated_client, _RouterClient(error=DiscoveryError("unreachable")), _Clock()
    )

    body = await _contract(authenticated_client, _NO_TOOLS)

    assert body["freshness"]["degraded"] is True
    assert body["tools"]["function"]["provider_support"] == "supported"
    assert body["parameters"]["tools"]["provider"]["source"] == "huggingface:static"


@pytest.mark.asyncio
async def test_the_stale_window_serves_the_last_good_verdict_flagged(
    huggingface_seeded, authenticated_client
) -> None:
    # fresh read → TTL expiry → outage: the observed negative still stands, but the
    # client is told it is stale rather than being handed a silent fabrication.
    clock = _Clock()
    _install_runtime(authenticated_client, _RouterClient(), clock)
    fresh = await _contract(authenticated_client, _NO_TOOLS)
    assert fresh["parameters"]["tools"]["provider"]["stale"] is False

    runtime: DiscoveryRuntime = cast(FastAPI, authenticated_client.app).state.discovery_runtime
    # swap ONLY the transport, keeping the warm cache — that is the outage shape.
    runtime._client = _RouterClient(error=DiscoveryError("unreachable"))  # noqa: SLF001
    clock.advance(61.0)

    stale = await _contract(authenticated_client, _NO_TOOLS)
    assert stale["freshness"]["stale"] is True
    assert stale["parameters"]["tools"]["provider"]["support"] == "unsupported"
    assert stale["parameters"]["tools"]["provider"]["stale"] is True
    # the tools section follows the same last-good verdict — no split brain.
    assert stale["tools"]["function"]["provider_support"] == "unsupported"

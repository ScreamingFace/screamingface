"""OME-1134: the two UNCOALESCED catalog calls carry the caller's traceparent; `fetch` does not.

FEATURE: trace correlation into aigateway (the correlation ladder `OME-1119` started).

STORY: as a user quoting the `trace_id` of a failed model-parameter lookup, I find the gateway's
half of that lookup in the same trace instead of a gap.

INVARIANT (the trap this file exists to catch): the traceparent is threaded as an explicit
argument, never put on `Credential`. `Credential` derives the catalog cache key, so a per-request
field on it would give every request its own entry and silently destroy the cache.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from screamingface_engine.app import create_app
from screamingface_engine.catalog import build_catalog_service
from screamingface_engine.catalog.admission import AdmissionAnswer, AdmittedModels
from screamingface_engine.catalog.aigateway import AigatewayCatalogSource
from screamingface_engine.catalog.cache import CachedCatalog
from screamingface_engine.catalog.executable import ExecutableModelParameterSource
from screamingface_engine.catalog.port import Credential, ModelParameterResponse
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
_OTHER_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
_MODEL = "openrouter/openai/gpt-5.5"
_DYNAMIC = "openrouter/meta/llama-4"
_IDENTITY = {"X-User-Email": "alice@example.com"}
_CATALOG = {"object": "list", "data": [{"id": _MODEL, "object": "model"}]}


def _contract(model: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "model": {"id": model},
        "parameters": {},
        "tools": {},
        "transport": {},
    }


def _gateway(seen: list[httpx.Request]) -> httpx.MockTransport:
    """A fake aigateway answering all three catalog paths, recording every request."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json=_CATALOG)
        if request.url.path == "/v1/models/admit":
            return httpx.Response(200, json={"admitted": True})
        return httpx.Response(200, json=_contract(request.url.params["model"]))

    return httpx.MockTransport(handle)


def _adapter() -> tuple[AigatewayCatalogSource, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    client = httpx.AsyncClient(base_url="http://aigateway.test", transport=_gateway(seen))
    return AigatewayCatalogSource(client), seen


# --- the adapter -------------------------------------------------------------------------------


async def test_model_parameters_forward_the_given_traceparent() -> None:
    adapter, seen = _adapter()
    await adapter.fetch_model_parameters(
        Credential.derive(_IDENTITY), _MODEL, traceparent=_TRACEPARENT
    )
    assert seen[0].headers["traceparent"] == _TRACEPARENT
    # The identity still leaves beside it — the trace is added, nothing is displaced.
    assert seen[0].headers["X-User-Email"] == "alice@example.com"


async def test_admit_model_forwards_the_given_traceparent() -> None:
    adapter, seen = _adapter()
    answer = await adapter.admit_model(
        Credential.derive(_IDENTITY), _DYNAMIC, traceparent=_TRACEPARENT
    )
    assert answer.outcome == "admitted"
    assert seen[0].url.path == "/v1/models/admit"
    assert seen[0].headers["traceparent"] == _TRACEPARENT


async def test_no_traceparent_given_means_no_header_sent() -> None:
    adapter, seen = _adapter()
    credential = Credential.derive(_IDENTITY)
    await adapter.fetch_model_parameters(credential, _MODEL)
    await adapter.admit_model(credential, _DYNAMIC)
    assert [request.headers.get("traceparent") for request in seen] == [None, None]


async def test_fetch_never_sends_a_traceparent() -> None:
    """INVARIANT: the coalesced call carries no trace. Its result serves N callers, so any one
    caller's trace on it would be a plausible, wrong attribution (see `_headers`' AIDEV-NOTE)."""
    adapter, seen = _adapter()
    await adapter.fetch(Credential.derive(_IDENTITY))
    assert "traceparent" not in seen[0].headers


async def test_identity_cannot_smuggle_a_profile_or_displace_the_traceparent() -> None:
    adapter, seen = _adapter()
    await adapter.fetch_model_parameters(
        Credential.derive({**_IDENTITY, "X-Profile": "research"}),
        _MODEL,
        traceparent=_TRACEPARENT,
    )
    assert "X-Profile" not in seen[0].headers
    assert seen[0].headers["traceparent"] == _TRACEPARENT


# --- the executable projection threads it to every upstream call -------------------------------


class _RecordingDetails:
    def __init__(self, responses: list[ModelParameterResponse] | None = None) -> None:
        self._responses = responses
        self.traceparents: list[str | None] = []

    async def fetch_model_parameters(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> ModelParameterResponse:
        self.traceparents.append(traceparent)
        if self._responses:
            return self._responses.pop(0)
        return ModelParameterResponse(status=200, content=b"{}")


class _RecordingAdmitter:
    def __init__(self) -> None:
        self.traceparents: list[str | None] = []

    async def admit_model(
        self, credential: Credential, model: str, *, traceparent: str | None = None
    ) -> AdmissionAnswer:
        self.traceparents.append(traceparent)
        return AdmissionAnswer(outcome="admitted")


async def test_a_declared_model_lookup_threads_the_traceparent() -> None:
    details = _RecordingDetails()
    source = ExecutableModelParameterSource(details, frozenset({_MODEL}))
    await source.fetch_model_parameters(
        Credential.derive(_IDENTITY), _MODEL, traceparent=_TRACEPARENT
    )
    assert details.traceparents == [_TRACEPARENT]


async def test_an_admission_threads_the_traceparent_to_admit_and_to_the_fetch() -> None:
    details = _RecordingDetails()
    admitter = _RecordingAdmitter()
    source = ExecutableModelParameterSource(
        details, frozenset(), admitted=AdmittedModels(), admission_source=admitter
    )
    await source.fetch_model_parameters(
        Credential.derive(_IDENTITY), _DYNAMIC, traceparent=_TRACEPARENT
    )
    assert admitter.traceparents == [_TRACEPARENT]
    assert details.traceparents == [_TRACEPARENT]


async def test_the_overlay_heal_path_threads_the_traceparent_to_every_call() -> None:
    """The stale-overlay heal makes three upstream calls for one request; all are its calls."""
    admitted = AdmittedModels()
    admitted.add(_DYNAMIC)
    details = _RecordingDetails(
        [
            ModelParameterResponse(status=404, content=b"{}"),
            ModelParameterResponse(status=200, content=b"{}"),
        ]
    )
    admitter = _RecordingAdmitter()
    source = ExecutableModelParameterSource(
        details, frozenset(), admitted=admitted, admission_source=admitter
    )
    await source.fetch_model_parameters(
        Credential.derive(_IDENTITY), _DYNAMIC, traceparent=_TRACEPARENT
    )
    assert details.traceparents == [_TRACEPARENT, _TRACEPARENT]
    assert admitter.traceparents == [_TRACEPARENT]


# --- the REST edge, end to end over the production wiring --------------------------------------


def _wired_app() -> tuple[FastAPI, list[httpx.Request], CachedCatalog]:
    seen: list[httpx.Request] = []

    def client_factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, transport=_gateway(seen))

    settings = Settings(jwt_secret="traceparent-test", aigateway_base_url="http://aigateway.test")
    service = build_catalog_service(settings, client_factory=client_factory)
    assert service is not None
    app = create_app(
        settings,
        stream=InMemoryEventStream(),
        catalog=service,
        model_parameters=service.model_parameter_source,
    )
    return app, seen, service


async def _get(app: FastAPI, path: str, headers: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path, params={"model": _MODEL}, headers=headers)


async def test_the_model_parameters_route_forwards_the_inbound_traceparent() -> None:
    app, seen, _ = _wired_app()
    response = await _get(app, "/v1/model-parameters", {**_IDENTITY, "traceparent": _TRACEPARENT})
    assert response.status_code == 200
    assert seen[0].url.path == "/v1/model-parameters"
    assert seen[0].headers["traceparent"] == _TRACEPARENT


@pytest.mark.parametrize(
    "inbound",
    [
        "not-a-traceparent",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
        "",
    ],
)
async def test_a_malformed_inbound_traceparent_degrades_to_absent(inbound: str) -> None:
    """Same rule as `rest/connections.py`: a bad trace header never fails the request, and is
    never forwarded — it would join nothing while looking correct."""
    app, seen, _ = _wired_app()
    response = await _get(app, "/v1/model-parameters", {**_IDENTITY, "traceparent": inbound})
    assert response.status_code == 200
    assert "traceparent" not in seen[0].headers


async def test_no_inbound_traceparent_sends_none() -> None:
    app, seen, _ = _wired_app()
    response = await _get(app, "/v1/model-parameters", dict(_IDENTITY))
    assert response.status_code == 200
    assert "traceparent" not in seen[0].headers


async def test_requests_differing_only_in_traceparent_share_one_catalog_cache_entry() -> None:
    """INVARIANT: the catalog cache key ignores the trace. This is the assertion that fails if
    the traceparent is ever moved onto `Credential` — each request would then miss, refetch, and
    take its own entry."""
    app, seen, service = _wired_app()
    first = await _get(app, "/v1/models", {**_IDENTITY, "traceparent": _TRACEPARENT})
    second = await _get(app, "/v1/models", {**_IDENTITY, "traceparent": _OTHER_TRACEPARENT})

    assert first.status_code == second.status_code == 200
    assert first.headers["ETag"] == second.headers["ETag"]
    catalog_calls = [request for request in seen if request.url.path == "/v1/models"]
    assert len(catalog_calls) == 1
    assert service.entry_count == 1
    # ...and the one coalesced upstream fetch carries neither caller's trace.
    assert "traceparent" not in catalog_calls[0].headers

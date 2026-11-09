from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

import screamingface as sf
from screamingface import _default_client


def _sync_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
    )


def _async_client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
    )


def _models(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {
                    "id": "anthropic/claude-haiku-4-5",
                    "object": "model",
                    "owned_by": "anthropic",
                    "supported_parameters": ["max_tokens", "temperature"],
                    "supported_tools": ["function"],
                    "unsupported_parameter_behavior": "reject",
                    "parameter_contract_url": (
                        "/v1/model-parameters?model=anthropic%2Fclaude-haiku-4-5"
                    ),
                },
                {
                    "id": "openrouter/openai/gpt-5.5",
                    "object": "model",
                    "owned_by": "openrouter",
                    "supported_parameters": ["reasoning_effort"],
                    "supported_tools": [],
                    "unsupported_parameter_behavior": "reject",
                    "parameter_contract_url": (
                        "/v1/model-parameters?model=openrouter%2Fopenai%2Fgpt-5.5"
                    ),
                },
            ],
        },
    )


def _benchmarks(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {
                    "id": "draco",
                    "object": "benchmark",
                    "title": "DRACO",
                    "description": "The 100-task deep-research benchmark.",
                    "revision": "rev0000000000000",
                    "case_count": 100,
                    "href": "/v1/benchmarks/draco",
                }
            ],
        },
    )


def test_explicit_client_lists_typed_models_and_benchmarks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        routes = {
            "/v1/models": _models,
            "/v1/benchmarks": _benchmarks,
        }
        route = routes.get(request.url.path)
        return route(request) if route else httpx.Response(404)

    with _sync_client(handler) as client:
        models = client.models.list()
        benchmarks = client.benchmarks.list()

    assert models == (
        sf.ModelInfo(
            id="anthropic/claude-haiku-4-5",
            provider="anthropic",
            supported_parameters=("max_tokens", "temperature"),
            supported_tools=("function",),
        ),
        sf.ModelInfo(
            id="openrouter/openai/gpt-5.5",
            provider="openrouter",
            supported_parameters=("reasoning_effort",),
            supported_tools=(),
        ),
    )
    assert [benchmark.id for benchmark in benchmarks] == ["draco"]
    assert benchmarks[0].title == "DRACO"
    assert benchmarks[0].case_count == 100


def test_benchmark_lookup_normalizes_flat_ids_and_rejects_hierarchies() -> None:
    with _sync_client(_benchmarks) as client:
        assert client.benchmarks.get(" draco ").id == "draco"
        with pytest.raises(ValueError, match="one flat lowercase identifier"):
            client.benchmarks.get("nested/benchmark")


@pytest.mark.asyncio
async def test_async_client_has_the_same_catalogue_interface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return _models(request)
        return _benchmarks(request)

    async with _async_client(handler) as client:
        assert (await client.models.list())[0].id == "anthropic/claude-haiku-4-5"
        assert (await client.benchmarks.list())[0].id == "draco"


def test_module_catalogues_delegate_to_the_lazy_default_client(monkeypatch: Any) -> None:
    class Models:
        def list(self) -> tuple[str, ...]:
            return ("model",)

    class Benchmarks:
        def list(self) -> tuple[str, ...]:
            return ("benchmark",)

        def get(self, benchmark_id: str) -> str:
            return f"benchmark:{benchmark_id}"

    class FakeClient:
        models = Models()
        benchmarks = Benchmarks()

    monkeypatch.setattr(_default_client, "_client", FakeClient())

    assert sf.models.list() == ("model",)
    assert sf.benchmarks.list() == ("benchmark",)
    assert sf.benchmarks.get("draco") == "benchmark:draco"

    monkeypatch.setattr(_default_client, "_client", None)


@pytest.mark.parametrize(
    ("path", "body", "message"),
    [
        ("/v1/models", {"object": "list", "data": [{"id": ""}]}, "Model id"),
        ("/v1/models", {"object": "wrong", "data": []}, "model catalogue"),
        ("/v1/models", {"object": "list", "data": "wrong"}, "data array"),
        ("/v1/models", {"object": "list", "data": [None]}, "entry must be an object"),
        ("/v1/benchmarks", [], "must be an object"),
        ("/v1/benchmarks", {"object": "wrong", "data": []}, "object must be 'list'"),
        (
            "/v1/benchmarks",
            {"object": "list", "data": "wrong"},
            "data array",
        ),
        (
            "/v1/benchmarks",
            {"object": "list", "data": [None]},
            "entry must be an object",
        ),
        (
            "/v1/benchmarks",
            {
                "object": "list",
                "data": [{"id": "draco", "object": "wrong"}],
            },
            "entry object",
        ),
        (
            "/v1/benchmarks",
            {
                "object": "list",
                "data": [
                    {
                        "id": "draco",
                        "object": "benchmark",
                        "title": "D",
                        "description": "d",
                        "revision": "r",
                        "case_count": 1,
                        "href": "/v1/benchmarks/draco",
                    },
                    {
                        "id": "draco",
                        "object": "benchmark",
                        "title": "D",
                        "description": "d",
                        "revision": "r",
                        "case_count": 1,
                        "href": "/v1/benchmarks/draco",
                    },
                ],
            },
            "duplicate id",
        ),
        (
            "/v1/benchmarks",
            {
                "object": "list",
                "data": [
                    {
                        "id": "draco",
                        "object": "benchmark",
                        "title": "D",
                        "description": "d",
                        "revision": "r",
                        "case_count": 0,
                        "href": "/v1/benchmarks/draco",
                    }
                ],
            },
            "case_count",
        ),
        (
            "/v1/benchmarks",
            {
                "object": "list",
                "data": [
                    {
                        "id": "nested/benchmark",
                        "object": "benchmark",
                        "title": "D",
                        "description": "d",
                        "revision": "r",
                        "case_count": 1,
                        "href": "/v1/benchmarks/nested/benchmark",
                    }
                ],
            },
            "one flat lowercase identifier",
        ),
    ],
)
def test_catalogues_reject_malformed_engine_payloads(
    path: str,
    body: object,
    message: str,
) -> None:
    client = _sync_client(
        lambda request: (
            httpx.Response(200, json=body) if request.url.path == path else httpx.Response(404)
        )
    )

    with client, pytest.raises(sf.PlanningError, match=message):
        (client.models if path.endswith("models") else client.benchmarks).list()


def test_catalogue_authentication_failure_is_typed() -> None:
    client = _sync_client(lambda _: httpx.Response(401, json={"detail": "missing"}))

    with client, pytest.raises(sf.AuthenticationError) as exc_info:
        client.models.list()

    assert exc_info.value.status == 401
    assert exc_info.value.code == "authentication_required"


def test_sync_catalogue_connection_failure_is_typed() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = _sync_client(unreachable)

    with client, pytest.raises(sf.EngineUnavailableError) as exc_info:
        client.models.list()

    assert exc_info.value.code == "engine_unreachable"
    assert exc_info.value.permanent is False
    assert exc_info.value.engine_url == "https://engine.example"


@pytest.mark.asyncio
async def test_async_catalogue_connection_failure_is_typed() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with _async_client(unreachable) as client:
        with pytest.raises(sf.EngineUnavailableError) as exc_info:
            await client.benchmarks.list()

    assert exc_info.value.code == "engine_unreachable"
    assert exc_info.value.permanent is False
    assert exc_info.value.engine_url == "https://engine.example"


@pytest.mark.parametrize(
    ("response", "code", "permanent"),
    [
        (httpx.Response(500), "engine_contract_error", False),
        (httpx.Response(200, text="{"), "invalid_catalogue", True),
    ],
)
def test_catalogue_http_and_json_failures_are_typed(
    response: httpx.Response,
    code: str,
    permanent: bool,
) -> None:
    client = _sync_client(lambda _: response)

    with client, pytest.raises(sf.PlanningError) as exc_info:
        client.models.list()

    assert exc_info.value.code == code
    assert exc_info.value.permanent is permanent


# --- an Unlisted Benchmark: off the listing, still read by id (OME-1714) ------------------

_UNLISTED_RESOURCE: dict[str, Any] = {
    # The resource spreads the same catalogue keys as a listing entry, plus the run-time
    # extras (`schema`, `selected_case_count`, `candidate_binding`, `url4`) and no `object`.
    "schema": "screamingface.benchmark.v1",
    "id": "inspect-wmdp_bio",
    "title": "WMDP-Bio",
    "description": "1,273 four-option questions probing hazardous biosecurity knowledge.",
    "revision": "557c21ed4fcf926e",
    "case_count": 1273,
    "origin": "inspect_evals",
    "saturation": "open",
    "selected_case_count": 1273,
    "candidate_binding": "candidate",
    "url4": "benchmark(...)",
}


def _listing_without_wmdp(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/benchmarks":
        return _benchmarks(request)
    if request.url.path == "/v1/benchmarks/inspect-wmdp_bio":
        return httpx.Response(200, json=_UNLISTED_RESOURCE)
    return httpx.Response(404, json={"title": "Unknown benchmark"})


def test_get_reads_an_unlisted_benchmark_by_id_when_the_listing_omits_it() -> None:
    # INVARIANT (OME-1714): "unlisted, not removed" — the listing hides the Benchmark, so
    # `get` must not stop at the listing. It falls back to the Engine's resource by id, which
    # still serves it, and returns the same typed Benchmark a listed id would.
    with _sync_client(_listing_without_wmdp) as client:
        assert [b.id for b in client.benchmarks.list()] == ["draco"]
        unlisted = client.benchmarks.get("inspect-wmdp_bio")

    assert unlisted.id == "inspect-wmdp_bio"
    assert unlisted.title == "WMDP-Bio"
    assert unlisted.revision == "557c21ed4fcf926e"
    assert unlisted.case_count == 1273
    assert unlisted.origin == "inspect_evals"


def test_get_of_an_id_the_engine_does_not_serve_still_says_not_installed() -> None:
    # INVARIANT: the fallback changes nothing for a wrong id — the Engine's 404 on the resource
    # becomes the same `unknown_benchmark` error callers matched before this fallback existed.
    with _sync_client(_listing_without_wmdp) as client:
        with pytest.raises(sf.PlanningError, match="not installed") as caught:
            client.benchmarks.get("inspect-wmdp_typo")

    assert caught.value.code == "unknown_benchmark"


def test_get_refuses_a_resource_whose_id_is_not_the_one_asked_for() -> None:
    # WHY: the fallback trusts the id in the body, so an Engine answering the wrong resource
    # must be refused as an invalid catalogue, not returned under the requested name.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks":
            return _benchmarks(request)
        return httpx.Response(200, json={**_UNLISTED_RESOURCE, "id": "inspect-wmdp_chem"})

    with _sync_client(handler) as client:
        with pytest.raises(sf.PlanningError, match="inspect-wmdp_chem") as caught:
            client.benchmarks.get("inspect-wmdp_bio")

    assert caught.value.code == "invalid_catalogue"


@pytest.mark.asyncio
async def test_async_get_reads_an_unlisted_benchmark_by_id_too() -> None:
    async with _async_client(_listing_without_wmdp) as client:
        unlisted = await client.benchmarks.get("inspect-wmdp_bio")

    assert unlisted.id == "inspect-wmdp_bio"
    assert unlisted.case_count == 1273

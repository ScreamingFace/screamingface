"""``POST /v1/benchmarks/{id}/selection`` returns the recipe for a fixed list of Case ids.

FEATURE (OME-1739): the SDK sends ``{"cases": [3, 17, 42]}`` in a request body (never a query
string, so a long list stays readable and out of access logs) and gets back the Benchmark
resource whose recipe serves and grades only those Cases. The resource echoes
``selected_case_ids`` so the SDK can refuse an Engine that ignored the selection.

INVARIANT: the recipe is written from the checked integers, never from the client's text, so a
body like ``["3)!/x"]`` can never reach the recipe. ``GET ?limit=N`` is untouched.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkRegistry,
    candidate,
)
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from screamingface_engine.benchmarks.selection import MAX_SELECTED_CASE_IDS
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

_CASE_COUNT = 1200  # above the id cap, so the cap is what refuses, not the Benchmark's size


def _app() -> FastAPI:
    benchmark = Benchmark(
        id="example-smoke",
        title="Example Smoke",
        description="One non-comparable structural probe.",
        revision="example-smoke-v1",
        case_count=_CASE_COUNT,
        declaration=BenchmarkDeclaration(
            failure_policy="coverage_declare", interaction="single_shot", difficulty="easy"
        ),
        build=lambda selected: build_evaluation_protocol(
            cases_route="/cases",
            case_evaluation=candidate("$item.input", web_search=False),
            selected_case_count=selected,
            available_case_count=_CASE_COUNT,
            aggregate_route="/aggregate",
        ),
    )
    return create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((benchmark,)),
    )


async def _post(app: FastAPI, body: Any, benchmark_id: str = "example-smoke") -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.post(f"/v1/benchmarks/{benchmark_id}/selection", json=body)


async def test_a_selection_returns_the_recipe_for_exactly_those_cases() -> None:
    response = await _post(_app(), {"cases": [42, 3, 17]})

    assert response.status_code == 200
    resource: dict[str, Any] = response.json()
    assert resource["id"] == "example-smoke"
    assert resource["case_count"] == _CASE_COUNT
    assert resource["selected_case_count"] == 3
    assert resource["selected_case_ids"] == [3, 17, 42]
    assert "/cases()!'[3,17,42]'" in resource["url4"]
    assert "!'aggregate:[3,17,42]'" in resource["url4"]


async def test_a_one_to_n_selection_is_the_limit_recipe() -> None:
    app = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        limited: dict[str, Any] = (await client.get("/v1/benchmarks/example-smoke?limit=3")).json()

    selected: dict[str, Any] = (await _post(app, {"cases": [1, 2, 3]})).json()

    assert selected["url4"] == limited["url4"]
    assert selected["selected_case_ids"] == [1, 2, 3]
    assert "selected_case_ids" not in limited


@pytest.mark.parametrize(
    "body",
    [
        {"cases": [3, 17, 1201]},  # above the Benchmark's Case count
        {"cases": [3, 3]},
        {"cases": [0]},
        {"cases": [-1]},
        {"cases": [True]},
        {"cases": [3.0]},
        {"cases": ["3)!/x"]},
        {"cases": ["3"]},
        {"cases": []},
        {"cases": 3},
        {"cases": [10**30]},
        {"cases": list(range(1, MAX_SELECTED_CASE_IDS + 2))},
        {},
        {"cases": [3], "limit": 3},
        [3, 17],
    ],
)
async def test_a_malformed_selection_is_a_422_problem(body: Any) -> None:
    response = await _post(_app(), body)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Invalid benchmark selection"


async def test_an_unknown_benchmark_is_a_404() -> None:
    response = await _post(_app(), {"cases": [3]}, benchmark_id="missing")

    assert response.status_code == 404


async def test_the_cap_admits_exactly_the_cap() -> None:
    response = await _post(_app(), {"cases": list(range(1, MAX_SELECTED_CASE_IDS + 1))})

    assert response.status_code == 200
    assert response.json()["selected_case_count"] == MAX_SELECTED_CASE_IDS

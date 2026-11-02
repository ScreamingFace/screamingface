"""An Unlisted Benchmark is off the catalogue index but still served by id (OME-1714).

FEATURE: take a Benchmark off the public catalogue without deleting it.
STORY: as product, I can keep a hazardous-knowledge Benchmark out of every public listing while
a researcher who knows its id can still run it.

INVARIANT: the mark changes exactly one thing — membership of ``GET /v1/benchmarks``. The
resource by id, every listed entry and the wire shape stay byte-identical, so no recorded
Score looks incomparable and no reader needs a new branch.
"""

from __future__ import annotations

from functools import partial

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkRegistry,
    candidate,
)
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream


def _benchmark(benchmark_id: str, *, unlisted: bool | None = None) -> Benchmark:
    """Build one minimal registrable Benchmark, passing `unlisted` only when the caller sets it."""
    build = partial(
        Benchmark,
        id=benchmark_id,
        title="Example Smoke",
        description="One non-comparable structural probe.",
        revision="example-smoke-v1",
        case_count=3,
        build=lambda selected: candidate(
            f"Explain why the sky looks blue. Selected cases: {selected}.",
            web_search=False,
        ),
        declaration=BenchmarkDeclaration(
            failure_policy="coverage_declare",
            interaction="single_shot",
            difficulty="easy",
        ),
    )
    return build() if unlisted is None else build(unlisted=unlisted)


def _client(*benchmarks: Benchmark) -> httpx.AsyncClient:
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry(benchmarks),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test")


def test_a_benchmark_is_listed_unless_it_says_otherwise() -> None:
    # INVARIANT: the default is listed — every Benchmark that existed before OME-1714 stays on
    # the catalogue without touching its row.
    assert _benchmark("example-smoke").unlisted is False
    assert _benchmark("example-smoke", unlisted=True).unlisted is True


def test_the_mark_never_reaches_the_wire() -> None:
    # INVARIANT (spec R4): the mark is a listing decision, not catalogue data — neither the
    # entry nor the resource carries it, so listed entries stay byte-identical to today.
    unlisted = _benchmark("example-smoke", unlisted=True)

    assert "unlisted" not in unlisted.catalog_entry()
    assert "unlisted" not in unlisted.resource()


@pytest.mark.asyncio
async def test_the_catalogue_listing_omits_an_unlisted_benchmark() -> None:
    # INVARIANT (spec R1): `GET /v1/benchmarks` is the one root every listing reads (the SDK's
    # `sf.benchmarks.list()`, the Scoreboard seed), so omitting it here hides it everywhere.
    listed = _benchmark("listed-smoke")
    async with _client(listed, _benchmark("unlisted-smoke", unlisted=True)) as client:
        entries = (await client.get("/v1/benchmarks")).json()["data"]
    async with _client(listed) as client:
        alone = (await client.get("/v1/benchmarks")).json()["data"]

    assert [entry["id"] for entry in entries] == ["listed-smoke"]
    # The listed neighbour is served exactly as it would be with no Unlisted sibling installed.
    assert entries == alone


@pytest.mark.asyncio
async def test_an_unlisted_benchmark_is_still_served_by_id() -> None:
    # INVARIANT (spec R2): unlisted is not removed — a run by id keeps working for anyone who
    # knows the id, and the resource is the same shape as a listed one's.
    async with _client(_benchmark("unlisted-smoke", unlisted=True)) as client:
        response = await client.get("/v1/benchmarks/unlisted-smoke")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "unlisted-smoke"
    assert body["schema"] == "screamingface.benchmark.v1"
    assert "unlisted" not in body

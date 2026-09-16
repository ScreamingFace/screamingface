"""Every catalogue entry declares where its benchmark came from (OME-1112).

FEATURE: benchmark provenance in the public catalogue.
STORY: as a researcher listing benchmarks, I can tell an imported board from a
home-grown one without guessing from its name.
"""

from __future__ import annotations

from functools import partial
from typing import cast

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks import (
    Benchmark,
    BenchmarkDeclaration,
    BenchmarkRegistry,
    candidate,
)
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.definition import BenchmarkOrigin
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream


def _benchmark(
    *, board_id: str = "example-smoke", origin: BenchmarkOrigin | None = None
) -> Benchmark:
    """Build one minimal registrable board, passing `origin` only when the caller declares it."""
    build = partial(
        Benchmark,
        id=board_id,
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
        ),
    )
    return build() if origin is None else build(origin=origin)


def test_a_board_registered_without_origin_is_home_grown() -> None:
    # INVARIANT: absent declaration means "screamingface" — every board that existed
    # before OME-1112 was authored in this repo, so the default states a true fact.
    board = _benchmark()

    assert board.origin == "screamingface"
    assert board.catalog_entry()["origin"] == "screamingface"
    assert board.resource()["origin"] == "screamingface"


def test_an_undeclared_origin_value_is_refused_by_name() -> None:
    # WHY the cast: the refusal is a RUNTIME contract — a caller outside the
    # typechecker (config, a plugin) must be stopped at construction, not at publish.
    with pytest.raises(ValueError, match="origin"):
        _benchmark(origin=cast("BenchmarkOrigin", "huggingface"))


def test_every_builtin_board_publishes_screamingface_origin() -> None:
    # INVARIANT: acceptance says /v1/benchmarks returns origin for EVERY board —
    # unconditionally emitted, never an optional key.
    for board in BUILTIN_BENCHMARKS:
        assert board.catalog_entry()["origin"] == "screamingface"


@pytest.mark.asyncio
async def test_an_imported_board_reads_back_through_the_api() -> None:
    imported = _benchmark(board_id="imported-smoke", origin="inspect_evals")
    app = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry([imported]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://engine.test",
    ) as client:
        entries = (await client.get("/v1/benchmarks")).json()["data"]

    assert [entry["origin"] for entry in entries] == ["inspect_evals"]

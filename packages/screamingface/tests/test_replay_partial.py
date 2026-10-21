"""Replay only the first n cases of a published run: `evaluate(pinned_cache=…, limit=n)` (row 5).

FEATURE: OME-1613 (spec §4, Q4, Q9, Q10) — a partial replay rebuilds the run's url4 for the first n
cases and replays them at $0. It is never judged and never recorded.
INVARIANT (Q9): the rebuild is trusted only if the Engine still builds the published run exactly:
the SDK rebuilds the whole run first and requires the same parsed recipe, else it refuses before
any run. Every comparison is on parsed url4 trees.

The Engine's benchmark catalog is faked so the url4 it serves depends on the `limit` asked for.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_client_run import CANDIDATE_URL4, _engine, _ForbiddenTransport
from test_replay import _Board, _lookup
from test_reproduce import COPY, _AsyncReplayer, _Replayer
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.linking import _prepare_benchmark

CASE_COUNT = 3


def _benchmark_url4(count: int, *, revision: str = "fixture-revision") -> str:
    """A benchmark whose url4 names its case count, as the Engine's protocol does."""

    return render(
        expr(
            src(
                RelExpr(
                    path=f"/benchmarks/draco/{revision}/cases",
                    context="question",
                    intent=text("$candidate"),
                ),
                name="answer",
                weight=0.0,
            ),
            src(
                RelExpr(path="/provider/judge", context="$answer", intent=text("Grade.")),
                name="grade",
                weight=0.0,
            ),
            intent=text(f"aggregate:{count}"),
        )
    )


def _linked(benchmark_url4: str) -> str:
    return _prepare_benchmark(benchmark_url4).bind(CANDIDATE_URL4).url4


PUBLISHED_URL4 = _linked(_benchmark_url4(CASE_COUNT))


class _Catalog:
    """The Engine's `/v1/benchmarks/draco`, rendering the case count it is asked for."""

    def __init__(self, *, revision: str = "fixture-revision", drift: bool = False) -> None:
        self.revision = revision
        self.drift = drift
        self.limits: list[int | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path != "/v1/benchmarks/draco":
            return _engine(request)
        raw = request.url.params.get("limit")
        limit = None if raw is None else int(raw)
        self.limits.append(limit)
        count = CASE_COUNT if limit is None else limit
        url4 = _benchmark_url4(count, revision=self.revision)
        if self.drift:
            url4 = _benchmark_url4(count + 100, revision=self.revision)
        return httpx.Response(
            200,
            json={
                "schema": "screamingface.benchmark.v1",
                "id": "draco",
                "title": "DRACO",
                "description": "Fixture DRACO Benchmark.",
                "revision": self.revision,
                "case_count": count,
                "url4": url4,
            },
        )


def _client(engine: object, catalog: _Catalog, board: _Board) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog),
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(board),
        run_transport=engine,  # type: ignore[arg-type]
    )


def _published(**overrides: object) -> dict[str, object]:
    return _lookup(url4_expression=PUBLISHED_URL4, total_questions=CASE_COUNT, **overrides)


def test_a_partial_replay_runs_the_first_n_cases_and_is_never_judged() -> None:
    engine = _Replayer(cases=((1, None), (2, None)))
    catalog = _Catalog()
    board = _Board(lookup=_published())

    with _client(engine, catalog, board) as client:
        report = client.evaluate(pinned_cache=COPY, limit=2, progress=False)

    assert report.candidates[0].reproduction is None
    assert board.posted == []
    assert engine.candidate is not None
    assert engine.candidate.url4 == _linked(_benchmark_url4(2))
    assert (engine.candidate.replay_frozen_copy, engine.candidate.answer_seed) == (COPY, 7)
    # The guard rebuilt the whole run first, at the published case count, then the subset.
    assert catalog.limits == [CASE_COUNT, 2]


@pytest.mark.parametrize(
    "catalog",
    [_Catalog(revision="newer-revision"), _Catalog(drift=True)],
    ids=["revision-changed", "protocol-changed"],
)
def test_an_engine_that_cannot_rebuild_the_run_refuses_before_any_run(catalog: _Catalog) -> None:
    board = _Board(lookup=_published())

    with _client(_ForbiddenTransport(), catalog, board) as client:
        with pytest.raises(sf.PlanningError) as caught:
            client.evaluate(pinned_cache=COPY, limit=2)

    assert caught.value.code == "partial_replay_unavailable"
    assert board.posted == []


@pytest.mark.parametrize("limit", [0, -1, CASE_COUNT, CASE_COUNT + 1])
def test_a_limit_that_is_not_a_proper_subset_fails_before_any_run(limit: int) -> None:
    catalog = _Catalog()

    with _client(_ForbiddenTransport(), catalog, _Board(lookup=_published())) as client:
        with pytest.raises(ValueError):
            client.evaluate(pinned_cache=COPY, limit=limit)

    assert catalog.limits == []


@pytest.mark.parametrize("limit", [True, 1.5, "2"])
def test_a_limit_that_is_not_an_integer_is_a_type_error(limit: Any) -> None:
    with _client(_ForbiddenTransport(), _Catalog(), _Board(lookup=_published())) as client:
        with pytest.raises(TypeError):
            client.evaluate(pinned_cache=COPY, limit=limit)


def test_a_partial_replay_needs_a_published_score() -> None:
    # S4 (no published score): the SDK would have to read the benchmark id out of the url4's route
    # text to rebuild it. It refuses instead (owner review pending, see the ledger).
    with _client(_ForbiddenTransport(), _Catalog(), _Board()) as client:
        with pytest.raises(ValueError):
            client.evaluate(pinned_cache=COPY, url4=PUBLISHED_URL4, limit=2)


def test_a_partial_replay_of_a_seedless_run_stamps_no_seed() -> None:
    engine = _Replayer(cases=((1, None),))
    lookup = _published()
    lookup.pop("answer_seed")

    with _client(engine, _Catalog(), _Board(lookup=lookup)) as client:
        client.evaluate(pinned_cache=COPY, limit=1, progress=False)

    assert engine.candidate is not None
    assert engine.candidate.answer_seed is None


@pytest.mark.asyncio
async def test_the_async_partial_replay_matches_the_sync_one() -> None:
    engine = _AsyncReplayer(cases=((1, None), (2, None)))
    catalog = _Catalog()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(catalog),
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(_Board(lookup=_published())),
        run_transport=engine,  # type: ignore[arg-type]
    )

    async with client:
        report = await client.evaluate(pinned_cache=COPY, limit=2, progress=False)

    assert report.candidates[0].reproduction is None
    assert engine.candidate is not None
    assert engine.candidate.url4 == _linked(_benchmark_url4(2))
    assert catalog.limits == [CASE_COUNT, 2]

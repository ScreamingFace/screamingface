"""`case_count` reaches the board from the Engine, and never from deployment config (OME-1056).

The Engine has always published `case_count` in its catalogue and the board discarded it via
`extra="ignore"`. That is why a one-case run could rank as though it were complete. These tests
pin both halves: the value now arrives, and configuration cannot forge it.

AIDEV-NOTE: `test_catalog_fields_the_board_does_not_display_are_ignored` in
test_seed_engine_catalog.py names `case_count` in its comment as an example of a field the board
ignores. That parenthetical predates this change and is now stale; its ASSERTION is unaffected
(unknown fields still do not break a deploy) and was deliberately left untouched.
"""

from __future__ import annotations

import httpx
import pytest

from scoreboard.scores.models import Benchmark
from scoreboard.seed import fetch_engine_benchmarks, load_benchmarks_json, seed_from_sources
from tests.unit.test_seed_engine_catalog import ENGINE_URL, _refusing, _serving

pytestmark = pytest.mark.asyncio


def _catalog(entry: dict[str, object]) -> dict[str, object]:
    return {"object": "list", "data": [{"id": "ifeval", "title": "IFEval", **entry}]}


async def test_the_catalogue_case_count_reaches_the_seed_row() -> None:
    payload = _catalog({"revision": "rev-ifeval", "case_count": 541})

    with _serving(payload) as client:
        row = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0).rows[0]

    assert row.case_count == 541


async def test_a_catalogue_without_a_case_count_seeds_none() -> None:
    # WHY tolerated rather than required: a catalogue that omits it costs the board its ranking
    # filter, not the benchmark its row — the same trade `description` already makes. A board
    # with no count ranks everything, exactly as it did before this change.
    payload = _catalog({"revision": "rev-ifeval"})

    with _serving(payload) as client:
        row = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0).rows[0]

    assert row.case_count is None


async def test_configuration_may_never_declare_a_case_count(tortoise_db: None) -> None:
    # INVARIANT: `case_count` is the Engine's claim about its own benchmark, exactly like
    # `revision`. Deployment configuration asserting one would re-open this ticket's hole from
    # the other side: a hand-written `case_count: 1` makes every one-case run rank as complete.
    # So the row is refused and named, not written.
    configured = load_benchmarks_json(
        '[{"id":"ifeval","display_name":"Stale IFEval","case_count":1}]'
    )

    with _refusing(httpx.ConnectError("down")) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=configured, client=client, retry_delay=0
        )

    assert report.refused == ["ifeval"]
    assert await Benchmark.filter(id="ifeval").count() == 0


@pytest.mark.parametrize(
    "published",
    [0, -1, True, "541", {"total": 541}, [541], 1.5],
    ids=["zero", "negative", "bool", "string", "object", "list", "float"],
)
async def test_an_unusable_catalogue_count_costs_the_filter_not_the_row(
    published: object,
) -> None:
    """A published count the board cannot use must degrade to None, never reject the entry.

    WHY this is the whole point of `extra="ignore"` on `_CatalogEntry`: the catalogue is written
    by another service. `ge=1` made a published `case_count: 0` — a benchmark whose dataset
    failed to load — cost the benchmark its ROW: a new board is never created, an existing
    board's text stops refreshing, and the deploy exits 0. The field's own comment already
    promised the milder outcome, and `SeedBenchmark` keeps `ge=1` because a HAND-WRITTEN typo
    should fail the deploy loudly. Require it where it is written; tolerate it where it is read.

    `True` is in the table because `bool` subclasses `int`, so an unguarded check would accept it
    as a case count of 1 — which re-opens the hole from the other side by making every one-case
    run "complete".
    """
    payload = _catalog({"revision": "rev-ifeval", "case_count": published})

    with _serving(payload) as client:
        read = fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0)

    assert read.rejected == [], f"{published!r} cost the benchmark its row"
    assert len(read.rows) == 1
    assert read.rows[0].case_count is None
    assert read.rows[0].display_name == "IFEval", "the row's text must still refresh"


async def test_the_catalogue_case_count_reaches_the_database(tortoise_db: None) -> None:
    """Pin the complete HTTP catalogue -> seed adapter -> ORM persistence path."""
    payload = _catalog({"revision": "rev-ifeval", "case_count": 541})

    with _serving(payload) as client:
        report = await seed_from_sources(
            engine_url=ENGINE_URL, configured=[], client=client, retry_delay=0
        )

    assert [row.id for row in report.seeded] == ["ifeval"]
    assert (await Benchmark.get(id="ifeval")).case_count == 541


async def test_a_catalogue_without_a_case_count_clears_a_stale_count(
    tortoise_db: None,
) -> None:
    """An authoritative missing count clears scope left by an older Engine revision."""
    await Benchmark.create(id="ifeval", display_name="IFEval", revision="rev-old", case_count=541)

    with _serving(_catalog({"revision": "rev-new"})) as client:
        await seed_from_sources(engine_url=ENGINE_URL, configured=[], client=client, retry_delay=0)

    benchmark = await Benchmark.get(id="ifeval")
    assert benchmark.revision == "rev-new"
    assert benchmark.case_count is None

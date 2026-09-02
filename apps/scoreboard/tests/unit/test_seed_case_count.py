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

"""The board copies each Benchmark's provenance block and saturation verdict from the Engine
(OME-1455, boxes ⑤ ⑥).

FEATURE: Benchmark Provenance on the Leaderboard page, the catalogue and the API.
STORY: as a reader of a Leaderboard page, the strip I will see (PR 4) is served by this API
from the same facts the Engine declared, copied at seed time, never retyped here.

INVARIANT: the block is a copy, not an authority. One nullable JSON column holds it whole
(spec §4.1); `saturation` has its own column because it is the one value a catalogue page
will sort on. The seed clears a stale block when the Engine stops publishing one.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.schemas import ProvenanceSchema
from scoreboard.scores.store import ScoreStore
from scoreboard.seed import (
    SeedBenchmark,
    SeedReport,
    _classify_configured,
    fetch_engine_benchmarks,
    load_benchmarks_json,
    seed_benchmarks,
)

pytestmark = pytest.mark.asyncio

ENGINE_URL = "https://engine.test"

_PROVENANCE: dict[str, Any] = {
    "paper_url": "https://arxiv.org/abs/2009.03300",
    "authors": "Hendrycks et al., 2020",
    "citation": "@article{hendrycks2020mmlu}",
    "inspect_contributors": ["jjallaire", "domdomegg"],
    "harness_url": (
        "https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmlu"
    ),
    "license": "MIT",
    "human_baseline": {"score": 0.898, "source_url": "https://arxiv.org/abs/2009.03300"},
    "frontier_score": {
        "score": 0.92,
        "model": "example frontier model",
        "source_url": "https://arxiv.org/abs/2009.03300",
        "as_of": "2026-09",
    },
    "notebook": "12_inspect_evals_benchmarks",
}


def _entry(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "object": "benchmark",
        "id": "inspect-mmlu",
        "title": "MMLU",
        "description": "57 subjects.",
        "revision": "rev-mmlu",
        "case_count": 14042,
        "origin": "inspect_evals",
        "saturation": "unknown",
        "href": "/v1/benchmarks/inspect-mmlu",
    }
    base.update(extra)
    return base


def _serving(payload: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _rows(*entries: dict[str, Any]) -> list[SeedBenchmark]:
    with _serving({"object": "list", "data": list(entries)}) as client:
        return list(fetch_engine_benchmarks(ENGINE_URL, client=client, retry_delay=0).rows)


# --- the catalogue → seed row ---------------------------------------------------------------


async def test_the_provenance_block_and_the_verdict_become_part_of_the_seed_row() -> None:
    row = _rows(_entry(saturation="saturated", **_PROVENANCE))[0]

    assert row.saturation == "saturated"
    assert row.provenance is not None
    assert row.provenance["paper_url"] == "https://arxiv.org/abs/2009.03300"
    assert row.provenance["inspect_contributors"] == ["jjallaire", "domdomegg"]
    assert row.provenance["human_baseline"] == {
        "score": 0.898,
        "source_url": "https://arxiv.org/abs/2009.03300",
    }
    assert row.provenance["frontier_score"]["as_of"] == "2026-09"


async def test_an_entry_with_no_provenance_keys_seeds_no_block() -> None:
    # WHY None and not {}: the Engine omits a key it has nothing for (never null); an empty
    # block would read as "we checked and there is none", which is a claim nobody made.
    row = _rows(_entry())[0]

    assert row.provenance is None
    assert row.saturation == "unknown"


async def test_a_partial_block_keeps_only_the_keys_the_engine_sent() -> None:
    row = _rows(_entry(paper_url="https://arxiv.org/abs/2009.03300", license="MIT"))[0]

    assert row.provenance == {
        "paper_url": "https://arxiv.org/abs/2009.03300",
        "license": "MIT",
    }


async def test_a_provenance_key_invented_next_quarter_is_ignored_not_fatal() -> None:
    # The Don't-regress rule: an older board must still boot against a newer Engine. Unknown
    # keys inside the block are dropped like unknown keys on the entry; the Engine's own twin
    # test pins that every key it serves TODAY is declared here.
    row = _rows(_entry(license="MIT", a_key_invented_next_quarter="x"))[0]

    assert row.provenance == {"license": "MIT"}


async def test_a_malformed_verdict_is_absent_never_a_rejected_row() -> None:
    # "Require it where it is written; tolerate it where it is read" (the case_count rule).
    row = _rows(_entry(saturation={"not": "a word"}))[0]

    assert row.saturation is None


async def test_a_malformed_score_object_costs_the_field_not_the_row() -> None:
    row = _rows(_entry(license="MIT", frontier_score="0.92"))[0]

    assert row.provenance == {"license": "MIT"}


@pytest.mark.parametrize("word", ["Saturated", "plateaued", "SATURATED", "saturated "])
async def test_a_verdict_outside_the_vocabulary_is_absent_never_stored_verbatim(
    word: str,
) -> None:
    # WHY: the page groups on this column, so a stray spelling stored as-is would be a group
    # of one no filter names. Null says "this board holds no verdict" (PR 1236 review).
    row = _rows(_entry(saturation=word))[0]

    assert row.saturation is None


async def test_the_local_seed_twins_row_shape_is_accepted_by_the_seed_parser() -> None:
    # The other half of the SDK's
    # `test_the_local_seed_twin_carries_the_sheet_and_the_verdict_in_the_seed_row_shape`:
    # a local stack hands the SDK's seed JSON straight to this parser, which forbids unknown
    # keys, so the block must arrive as ONE `provenance` object, never as the flat keys the
    # HTTP catalogue serves. Before this pin, the first declared value crashed every local
    # boot (review finding on PR 1236).
    twin_row: dict[str, Any] = {
        "id": "inspect-mmlu",
        "display_name": "MMLU",
        "description": "57 subjects.",
        "revision": "rev-mmlu",
        "provenance": _PROVENANCE,
        "saturation": "saturated",
    }

    row = load_benchmarks_json(json.dumps([twin_row]))[0]

    assert row.provenance == _PROVENANCE
    assert row.saturation == "saturated"
    with pytest.raises(ValueError) as refused:
        load_benchmarks_json(json.dumps([{**twin_row, "license": "MIT"}]))
    # The loader wraps pydantic's error in a plain ValueError, so the structured reason sits
    # on the cause; asserting on its code, not its English, survives a pydantic bump.
    cause = refused.value.__cause__
    assert isinstance(cause, ValidationError)
    assert cause.errors()[0]["type"] == "extra_forbidden"


# --- the seed → the table → the API ----------------------------------------------------------


@pytest_asyncio.fixture
async def async_client(tortoise_db: None) -> Any:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_the_seeded_block_is_served_on_the_catalogue_and_the_leaderboard(
    async_client: httpx.AsyncClient,
) -> None:
    await seed_benchmarks(_rows(_entry(saturation="saturated", **_PROVENANCE)))

    listing = (await async_client.get("/v1/benchmarks")).json()["benchmarks"][0]
    board = (await async_client.get("/v1/leaderboard/inspect-mmlu")).json()["benchmark"]

    for served in (listing, board):
        assert served["saturation"] == "saturated"
        assert served["provenance"]["authors"] == "Hendrycks et al., 2020"
        assert served["provenance"]["inspect_contributors"] == ["jjallaire", "domdomegg"]
        assert served["provenance"]["frontier_score"]["score"] == 0.92


async def test_a_board_with_no_block_serves_null_for_it(async_client: httpx.AsyncClient) -> None:
    await seed_benchmarks(_rows(_entry()))

    served = (await async_client.get("/v1/benchmarks")).json()["benchmarks"][0]

    assert served["provenance"] is None
    assert served["saturation"] == "unknown"


async def test_a_reseed_without_the_block_clears_the_stale_copy(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: the Engine is the only authority. If it stops publishing a field, the copy
    # must not outlive it (the case_count sentinel rule, OME-1056).
    await seed_benchmarks(_rows(_entry(saturation="saturated", **_PROVENANCE)))
    await seed_benchmarks(_rows(_entry()))

    served = (await async_client.get("/v1/benchmarks")).json()["benchmarks"][0]

    assert served["provenance"] is None
    assert served["saturation"] == "unknown"


async def test_a_stored_key_this_build_does_not_declare_never_breaks_the_listing(
    async_client: httpx.AsyncClient,
) -> None:
    # A Helm rollback keeps the newer build's stored block (the seed is a post-upgrade hook,
    # so a rollback never reseeds). One such row must cost its unknown key, not the whole
    # catalogue listing (PR 1236 review: `extra="forbid"` at read was a 500 on every board).
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="inspect-mmlu",
        display_name="MMLU",
        provenance={"license": "MIT", "a_key_from_a_newer_build": "x"},
        saturation="open",
    )

    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    served = response.json()["benchmarks"][0]
    assert served["provenance"] == {
        **{name: None for name in ProvenanceSchema.model_fields},
        "license": "MIT",
    }


async def test_a_stray_key_inside_a_stored_score_costs_that_key_not_the_listing(
    async_client: httpx.AsyncClient,
) -> None:
    # The same rollback, one level down: the newer build's seed wrote a richer score object.
    # The outer block already ignored unknown keys, but the nested score schema still forbade
    # them, and pydantic applies each model's own rule — so one stray nested key was again a
    # 500 on the whole listing (second review round on PR 1236).
    await ScoreStore().register_benchmark(
        benchmark_id="inspect-mmlu",
        display_name="MMLU",
        provenance={
            "license": "MIT",
            "human_baseline": {"score": 0.9, "source_url": "https://h.test", "stray": 1},
        },
    )

    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    served = response.json()["benchmarks"][0]["provenance"]
    assert served["human_baseline"] == {
        "score": 0.9,
        "source_url": "https://h.test",
        "model": None,
        "as_of": None,
    }


async def test_a_stored_key_of_the_wrong_type_costs_that_key_not_the_listing(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: the read side keeps the seed side's promise — one bad key costs its own
    # field, never the row and never the listing. Before this pin the read validated the
    # whole block at once and raised on the first mismatch (second review round on PR 1236).
    await ScoreStore().register_benchmark(
        benchmark_id="inspect-mmlu",
        display_name="MMLU",
        provenance={
            "license": "MIT",
            "inspect_contributors": "not-a-list",
            "frontier_score": "0.9",
        },
    )

    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    served = response.json()["benchmarks"][0]["provenance"]
    assert served["license"] == "MIT"
    assert served["inspect_contributors"] is None
    assert served["frontier_score"] is None


async def test_a_stored_block_with_no_readable_key_is_served_as_null(
    async_client: httpx.AsyncClient,
) -> None:
    # None, not an all-null object: the same "checked, none" rule the seed applies.
    await ScoreStore().register_benchmark(
        benchmark_id="inspect-mmlu",
        display_name="MMLU",
        provenance={"inspect_contributors": "not-a-list"},
    )

    served = (await async_client.get("/v1/benchmarks")).json()["benchmarks"][0]

    assert served["provenance"] is None


@pytest.mark.parametrize("word", ["Saturated", "plateaued", ""])
async def test_a_direct_register_call_with_a_word_outside_the_vocabulary_is_refused(
    tortoise_db: None, word: str
) -> None:
    # WHY refuse rather than store null, unlike the catalogue reader: a direct caller is code,
    # not another service's data, and code passing "Saturated" is a bug to surface, not a
    # value to tolerate. The HTTP seed never reaches here with one — its reader nulls it first.
    with pytest.raises(ValueError, match="saturation"):
        await ScoreStore().register_benchmark(
            benchmark_id="inspect-mmlu", display_name="MMLU", saturation=word
        )


async def test_a_direct_register_call_leaves_the_block_alone_when_it_says_nothing(
    tortoise_db: None,
) -> None:
    # The sentinel, like case_count: a caller that omits the argument keeps the stored copy;
    # only an explicit None (the Engine seed) clears it.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="inspect-mmlu",
        display_name="MMLU",
        provenance={"license": "MIT"},
        saturation="open",
    )
    kept = await store.register_benchmark(benchmark_id="inspect-mmlu", display_name="MMLU v2")

    assert kept.provenance is not None and kept.provenance.license == "MIT"
    assert kept.saturation == "open"


# --- configuration may not claim Engine-owned facts ---------------------------------------------


async def test_a_hand_written_row_claiming_provenance_is_refused_like_case_count() -> None:
    # WHY: a configured entry declaring a frontier score would let chart values impersonate a
    # published fact; the block reaches the table only through the Engine catalogue.
    report = SeedReport()

    allowed = _classify_configured(
        [SeedBenchmark(id="hand", display_name="Hand", provenance={"license": "MIT"})],
        published=set(),
        engine_owned=set(),
        existing_ids=set(),
        report=report,
    )

    assert allowed == []
    assert report.refused == ["hand"]

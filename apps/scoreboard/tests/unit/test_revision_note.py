"""A revision's note travels from the Engine catalogue to the revisions list (OME-2001).

FEATURE: the revision note, one short plain-text line (about 120 characters) that the Engine
publishes beside a Benchmark's revision, saying what changed and whether scores still compare.
STORY: as a researcher who sees that a leaderboard's revision changed, I read on the same page
what changed, without asking the team.

The rules these tests defend:
- absent stays absent: an Engine that serves no notes still seeds every Benchmark;
- an unusable note costs the note, never the Benchmark's row;
- the Engine is the author: a later non-empty note replaces the stored one, and a missing note
  never erases one;
- `first_seen_at` never moves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, BenchmarkRevision
from scoreboard.scores.revisions import REVISION_NOTE_STORAGE_BOUND, record_revision
from scoreboard.scores.store import ScoreStore
from scoreboard.seed import (
    CatalogRead,
    SeedReport,
    fetch_engine_benchmarks,
    load_benchmarks_json,
    seed_from_sources,
)

pytestmark = pytest.mark.asyncio

ENGINE_URL = "https://engine.test"
_OLD, _NEW = "d8fb037307f35415", "35c7d07e9058f52d"
_NOTE: str = (
    "Length-adjusted score, judge at low effort, failed Cases count as 0. "
    "Not comparable with earlier results."
)


def _catalog(revision: str, **extra: object) -> dict[str, Any]:
    """A one-Benchmark Engine catalogue; `extra` adds keys to the entry (the note, usually)."""

    return {
        "object": "list",
        "data": [
            {
                "object": "benchmark",
                "id": "healthbench-professional",
                "title": "HealthBench Professional",
                "description": "Clinician-written health conversations, rubric-graded.",
                "revision": revision,
                "case_count": 525,
                **extra,
            }
        ],
    }


def _serving(payload: object) -> httpx.Client:
    """An HTTP client whose every answer is `payload`, standing in for the Engine."""

    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )


async def _seed(payload: object) -> SeedReport:
    """One seed pass against an Engine serving `payload`, as a scoreboard deploy runs it."""

    with _serving(payload) as client:
        return await seed_from_sources(
            engine_url=ENGINE_URL, configured=[], client=client, retry_delay=0
        )


async def _stored(revision: str) -> BenchmarkRevision:
    """The stored record of one HealthBench Professional revision."""

    return await BenchmarkRevision.get(benchmark_id="healthbench-professional", revision=revision)


@pytest_asyncio.fixture
async def async_client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# --- reading the Engine catalogue ---------------------------------------------------------------


async def test_the_catalogue_reader_carries_the_note_beside_the_revision() -> None:
    """INVARIANT: the name is `revision_note`, the Engine's own
    (`test_a_declared_revision_note_is_served_with_the_catalogue_entry` pins the producer)."""

    with _serving(_catalog(_NEW, revision_note=_NOTE)) as client:
        read: CatalogRead = fetch_engine_benchmarks(ENGINE_URL, client=client)

    assert [(row.revision, row.revision_note) for row in read.rows] == [(_NEW, _NOTE)]


async def test_an_engine_that_serves_no_notes_still_seeds_every_benchmark() -> None:
    """Absent stays absent: the scoreboard can deploy before the Engine learns about notes."""

    with _serving(_catalog(_OLD)) as client:
        read: CatalogRead = fetch_engine_benchmarks(ENGINE_URL, client=client)

    assert [(row.id, row.revision_note) for row in read.rows] == [
        ("healthbench-professional", None)
    ]
    assert read.rejected == []


@pytest.mark.parametrize(
    "served",
    [
        pytest.param("x" * (REVISION_NOTE_STORAGE_BOUND + 1), id="over-the-storage-bound"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param(None, id="null"),
        pytest.param({"text": "Judge changed."}, id="not-text"),
        pytest.param("Judge changed.\nNot comparable.", id="two-lines"),
    ],
)
async def test_an_unusable_note_costs_the_note_and_never_the_benchmarks_row(
    served: object,
) -> None:
    """WHY dropped, not cut: a note ends with whether scores compare, so a cut note can lose
    exactly that sentence and read as the opposite claim. No note is honest; half a note is not.
    And never the row (the `case_count` rule): a Benchmark must not leave the board because
    another service wrote 501 characters, past the board's safety bound on stored text."""

    with _serving(_catalog(_NEW, revision_note=served)) as client:
        read: CatalogRead = fetch_engine_benchmarks(ENGINE_URL, client=client)

    assert [(row.id, row.revision_note) for row in read.rows] == [
        ("healthbench-professional", None)
    ]
    assert read.rejected == []


@pytest.mark.parametrize("length", [121, 300, 500])
async def test_a_note_longer_than_the_authors_target_travels_whole_to_the_revisions_list(
    async_client: httpx.AsyncClient, length: int
) -> None:
    """WHY: about 120 characters is guidance for the author, never a rule (owner decision,
    2026-11-23). A 121- or 300-character note is read, stored and returned unchanged; the only
    length the board enforces is its 500-character safety bound, and that one is inclusive."""

    note: str = "x" * length

    with _serving(_catalog(_NEW, revision_note=note)) as client:
        read: CatalogRead = fetch_engine_benchmarks(ENGINE_URL, client=client)
    await _seed(_catalog(_NEW, revision_note=note))
    response: httpx.Response = await async_client.get(
        "/v1/leaderboard/healthbench-professional/revisions"
    )

    assert REVISION_NOTE_STORAGE_BOUND == 500
    assert read.rows[0].revision_note == note
    assert (await _stored(_NEW)).note == note
    assert [r["note"] for r in response.json()["revisions"]] == [note]


async def test_a_note_past_the_storage_bound_is_not_stored(tortoise_db: None) -> None:
    """The board never stores unbounded text from another service: a 501-character note leaves
    the revision recorded, with no note."""

    await _seed(_catalog(_NEW, revision_note="x" * (REVISION_NOTE_STORAGE_BOUND + 1)))

    assert (await _stored(_NEW)).note is None


async def test_deployment_configuration_cannot_write_a_note(tortoise_db: None) -> None:
    """The note is Engine-owned, like the revision it describes: a hand-written chart value
    claiming one is refused, so configuration can never put words under a revision."""

    configured = load_benchmarks_json(
        '[{"id":"hle","display_name":"HLE","revision_note":"Trust me, comparable."}]'
    )

    report: SeedReport = await seed_from_sources(engine_url=None, configured=configured)

    assert report.refused == ["hle"]
    assert not await Benchmark.exists(id="hle")


# --- storing it -----------------------------------------------------------------------------


async def test_the_seed_stores_the_note_on_the_revision_it_describes(tortoise_db: None) -> None:
    """Each revision keeps its own note: the earlier revision, seeded before notes, has none."""

    await _seed(_catalog(_OLD))
    await _seed(_catalog(_NEW, revision_note=_NOTE))

    assert (await _stored(_NEW)).note == _NOTE
    assert (await _stored(_OLD)).note is None


async def test_a_later_deploy_with_new_text_replaces_the_stored_note(tortoise_db: None) -> None:
    """The Engine row is the author, so a typo fixed there reaches the page on the next deploy.
    The first-seen date does not move: the wording changed, not the day the board learned the id."""

    await _seed(_catalog(_NEW, revision_note="Judge at low efort. Not comparable."))
    first_seen: datetime = (await _stored(_NEW)).first_seen_at

    await _seed(_catalog(_NEW, revision_note="Judge at low effort. Not comparable."))

    after: BenchmarkRevision = await _stored(_NEW)
    assert after.note == "Judge at low effort. Not comparable."
    assert after.first_seen_at == first_seen


async def test_a_deploy_that_serves_no_note_keeps_the_stored_one(tortoise_db: None) -> None:
    """Never erased: an Engine rolled back to a build without notes, or a dropped unusable note,
    must not blank a reason readers already rely on."""

    await _seed(_catalog(_NEW, revision_note=_NOTE))

    await _seed(_catalog(_NEW))
    await _seed(_catalog(_NEW, revision_note="x" * (REVISION_NOTE_STORAGE_BOUND + 1)))

    assert (await _stored(_NEW)).note == _NOTE


async def test_a_note_arriving_after_the_revision_was_first_seen_is_filled_in(
    tortoise_db: None,
) -> None:
    """Two deployments must land before a note shows. When the scoreboard seeds the new id
    before the Engine serves notes, the next seed fills the note in and keeps the date."""

    await _seed(_catalog(_NEW))
    first_seen: datetime = (await _stored(_NEW)).first_seen_at

    await _seed(_catalog(_NEW, revision_note=_NOTE))

    after: BenchmarkRevision = await _stored(_NEW)
    assert (after.note, after.first_seen_at) == (_NOTE, first_seen)


@pytest.mark.parametrize(
    "note", ["x" * (REVISION_NOTE_STORAGE_BOUND + 1), "", "  ", "Judge changed.\nNot comparable."]
)
async def test_recording_a_revision_refuses_a_note_it_could_not_show(
    tortoise_db: None, note: str
) -> None:
    """WHY refuse here while the catalogue reader drops: that reader faces another service's
    data; this is a code boundary, and a caller passing a blank, multi-line or unbounded note is
    a bug to surface (the `saturation` rule in `register_benchmark`). The bound is the same
    500-character safety bound, never the author's target of about 120."""

    await ScoreStore().register_benchmark("mmlu_pro", "MMLU-Pro", revision=_OLD)

    with pytest.raises(ValueError, match="note"):
        await record_revision("mmlu_pro", _NEW, 100, note)

    assert not await BenchmarkRevision.exists(benchmark_id="mmlu_pro", revision=_NEW)


# --- serving it -----------------------------------------------------------------------------


async def test_the_revisions_list_returns_each_revisions_own_note(
    async_client: httpx.AsyncClient,
) -> None:
    """The page shows the SELECTED revision's note, so the list names the note per revision,
    and says null where there is none rather than leaving the key out."""

    await _seed(_catalog(_OLD))
    await _seed(_catalog(_NEW, revision_note=_NOTE))

    response: httpx.Response = await async_client.get(
        "/v1/leaderboard/healthbench-professional/revisions"
    )

    assert response.status_code == 200
    assert [(r["revision"], r["current"], r["note"]) for r in response.json()["revisions"]] == [
        (_NEW, True, _NOTE),
        (_OLD, False, None),
    ]

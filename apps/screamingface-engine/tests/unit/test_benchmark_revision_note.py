"""A Benchmark may say, beside its published revision, what changed (OME-2001).

FEATURE: the revision note, one plain-text line of at most 120 characters written where the
revision id is written, and served with the Benchmark's catalogue entry.
STORY: as a researcher who sees that a leaderboard's revision changed, I read on the same page
what changed and whether my old scores still compare, without asking the team.

Runs without the `inspect` extra: the note is declared on `Benchmark` itself, the one type a
hand-built Benchmark (MedXpertQA) and an imported catalogue row both become.
"""

from __future__ import annotations

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
from screamingface_engine.benchmarks.definition import REVISION_NOTE_LIMIT
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio

_NOTE: str = (
    "Length-adjusted score, judge at low effort, failed Cases count as 0. "
    "Not comparable with earlier results."
)


def _benchmark(revision_note: str | None = None) -> Benchmark:
    """A stand-in Benchmark built the way a hand-built one is: straight through `Benchmark`."""

    return Benchmark(
        id="example-smoke",
        title="Example Smoke",
        description="One non-comparable structural probe.",
        revision="example-smoke-v2",
        revision_note=revision_note,
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


async def _listed_entry(benchmark: Benchmark) -> dict[str, object]:
    """The Benchmark's entry as the public `GET /v1/benchmarks` route serves it."""

    app: FastAPI = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((benchmark,)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        response: httpx.Response = await client.get("/v1/benchmarks")
    assert response.status_code == 200
    (entry,) = response.json()["data"]
    return entry


async def test_a_declared_revision_note_is_served_with_the_catalogue_entry() -> None:
    """INVARIANT: the Scoreboard seed reads the note from this document by the name
    `revision_note` (`_CatalogEntry` in apps/scoreboard/src/scoreboard/seed.py). The two apps
    cannot import each other, so the producer pins the name: rename it here and the page
    silently stops showing why a revision changed."""

    entry: dict[str, object] = await _listed_entry(_benchmark(_NOTE))

    assert entry["revision_note"] == _NOTE
    assert entry["revision"] == "example-smoke-v2"


async def test_a_benchmark_without_a_note_serves_no_note_key() -> None:
    """Present-only, like `focus`: every revision published before notes existed keeps a
    byte-identical catalogue entry, so no reader sees an empty note it has to handle."""

    entry: dict[str, object] = await _listed_entry(_benchmark())

    assert "revision_note" not in entry


async def test_a_note_at_the_limit_is_accepted() -> None:
    """The limit is inclusive: exactly 120 characters is a valid note."""

    note: str = "x" * REVISION_NOTE_LIMIT

    assert REVISION_NOTE_LIMIT == 120
    assert _benchmark(note).revision_note == note


@pytest.mark.parametrize(
    "note",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("x" * (REVISION_NOTE_LIMIT + 1), id="over-the-limit"),
        pytest.param("Judge changed.\nNot comparable.", id="two-lines"),
        pytest.param(" Judge changed.", id="leading-space"),
    ],
)
async def test_a_note_the_leaderboard_could_not_show_as_one_line_is_refused_at_authoring_time(
    note: str,
) -> None:
    """WHY the Engine refuses it: the note is written here and only read on the Scoreboard, which
    drops an unusable note rather than lose the Benchmark's row. Without this refusal a note that
    is too long would pass every Engine test and simply never appear on the page."""

    with pytest.raises(ValueError, match="revision_note"):
        _benchmark(note)

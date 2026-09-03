"""The Engine owns every word the leaderboard shows about a Benchmark (OME-904).

FEATURE: benchmark descriptions on the leaderboard, with one authoring site.
STORY: as a leaderboard reader, I see what a benchmark tests without leaving the board.
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
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS, BUILTIN_DEPLOYMENT
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream

pytestmark = pytest.mark.asyncio


def _benchmark(
    *,
    focus: str | None = None,
    dataset_url: str | None = None,
    title: str = "Example Smoke",
    revision: str = "example-smoke-v1",
) -> Benchmark:
    return Benchmark(
        id="example-smoke",
        title=title,
        description="One non-comparable structural probe.",
        revision=revision,
        case_count=3,
        build=lambda selected: candidate(
            f"Explain why the sky looks blue. Selected cases: {selected}.",
            web_search=False,
        ),
        focus=focus,
        dataset_url=dataset_url,
        declaration=BenchmarkDeclaration(
            failure_policy="coverage-declare",
            interaction="single_shot",
        ),
    )


async def _catalog(benchmark: Benchmark) -> dict[str, object]:
    app: FastAPI = create_app(
        Settings(jwt_secret="s"),
        stream=InMemoryEventStream(),
        benchmarks=BenchmarkRegistry((benchmark,)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://engine.test",
    ) as client:
        entries = (await client.get("/v1/benchmarks")).json()["data"]
    entry: dict[str, object] = entries[0]
    return entry


async def test_a_declared_focus_and_dataset_link_reach_the_catalog() -> None:
    entry = await _catalog(
        _benchmark(
            focus="Structural probing",
            dataset_url="https://huggingface.co/datasets/example/smoke",
        )
    )

    assert entry["focus"] == "Structural probing"
    assert entry["dataset_url"] == "https://huggingface.co/datasets/example/smoke"


async def test_a_declared_focus_and_dataset_link_reach_the_detail_resource() -> None:
    benchmark = _benchmark(
        focus="Structural probing",
        dataset_url="https://huggingface.co/datasets/example/smoke",
    )

    resource = benchmark.resource(1)

    assert resource["focus"] == "Structural probing"
    assert resource["dataset_url"] == "https://huggingface.co/datasets/example/smoke"


async def test_a_benchmark_declaring_neither_publishes_neither_key() -> None:
    # INVARIANT: absent display metadata is an absent key, never a null. A seeded row's
    # focus/dataset columns are then left untouched rather than blanked by a null.
    entry = await _catalog(_benchmark())

    assert "focus" not in entry
    assert "dataset_url" not in entry


@pytest.mark.parametrize("blank", ["", "   "])
async def test_a_blank_focus_line_is_refused(blank: str) -> None:
    with pytest.raises(ValueError, match="focus"):
        _benchmark(focus=blank)


@pytest.mark.parametrize(
    "reference",
    ["/datasets/example", "huggingface.co/datasets/example", "ftp://example.invalid/x", ""],
)
async def test_a_dataset_link_that_is_not_an_absolute_web_url_is_refused(reference: str) -> None:
    with pytest.raises(ValueError, match="dataset_url"):
        _benchmark(dataset_url=reference)


@pytest.mark.parametrize(
    "benchmark",
    tuple(BUILTIN_BENCHMARKS),
    ids=lambda benchmark: benchmark.id,
)
async def test_every_installed_benchmark_publishes_a_focus_line(benchmark: Benchmark) -> None:
    # STORY: the portal's "Focus" column is filled from the Engine, not hand-copied into a chart.
    # WHY not a table of the exact lines (OME-1095): the wording is authored in the board's own
    # definition module and reviewed in that diff; a second copy here would only have to be
    # edited by hand for every new board. What the shared suite owns is that the column is
    # never empty for a registered board.
    assert benchmark.focus


async def test_no_two_boards_are_published_under_the_same_focus_line() -> None:
    """INVARIANT: the Focus column is where a reader tells two boards over one dataset apart.

    The two HealthBench boards share a dataset and the two DRACO boards share cases, rubrics
    and dataset alike — the focus line is the only place the leaderboard shows the difference.
    Two boards sharing one line leaves a reader with two indistinguishable rows.
    """

    lines = [benchmark.focus for benchmark in BUILTIN_BENCHMARKS]

    assert len(set(lines)) == len(lines), f"duplicate focus lines across boards: {lines}"


async def test_boards_baked_from_one_asset_bundle_publish_one_dataset_link() -> None:
    """INVARIANT: one physical dataset, one published link — derived, not hand-listed.

    A board's dataset link is a fact about the assets it reads, and boards that share an
    asset bundle read the same baked files. Two links under one bundle means at least one
    board sends a reader to a dataset it was not built from.

    WHY nothing here asserts which boards have a link at all: that is a per-board editorial
    fact (IFEval publishes none because its dataset is vendored inside the Engine, so no
    public URL is authoritative), owned by the board's definition module.
    """

    published: dict[str, set[str | None]] = {}
    for registration in BUILTIN_DEPLOYMENT.registrations:
        published.setdefault(registration.asset_bundle.id, set()).add(
            registration.benchmark.dataset_url
        )

    conflicting = {bundle: links for bundle, links in published.items() if len(links) > 1}
    assert not conflicting, f"one asset bundle, more than one dataset link: {conflicting}"


async def test_the_catalog_publishes_the_computed_revision_untouched_by_display_metadata() -> None:
    # INVARIANT: a submission carries the Engine's revision and the board ranks per revision, so
    # a revision that moves makes every already-recorded submission look incomparable. `revision`
    # is computed from dataset and protocol constants; editorial text must never reach it, and
    # the wire value must be that computed value rather than anything derived from metadata.
    entry = await _catalog(
        _benchmark(focus="Structural probing", dataset_url="https://example.test/dataset")
    )
    plain = await _catalog(_benchmark())

    assert entry["revision"] == plain["revision"] == "example-smoke-v1"


async def test_the_catalog_publishes_every_installed_benchmarks_own_revision() -> None:
    # AIDEV-NOTE: deliberately NOT a table of literal hashes. Pinning them here would recreate
    # the very failure OME-904 removes — a hand-copied second copy that silently goes stale.
    # The board no longer holds its own copy either: it seeds `revision` straight from this
    # catalogue response.
    for benchmark in BUILTIN_BENCHMARKS:
        entry = await _catalog(benchmark)
        assert entry["revision"] == benchmark.revision
        assert entry["revision"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("focus", "x" * 121),
        ("title", "x" * 256),
        ("revision", "x" * 65),
    ],
)
async def test_text_too_long_for_the_board_to_store_is_refused_at_authoring_time(
    field: str, value: str
) -> None:
    # WHY the Engine enforces the board's limits: "one authoring site" means an Engine author
    # never runs the board's validation. Without a cap here, a 130-character focus line passes
    # every Engine test and is only discovered at the next deploy, where the board can do
    # nothing better than skip that benchmark and keep its old text. Fail where it is written.
    with pytest.raises(ValueError, match=field):
        if field == "focus":
            _benchmark(focus=value)
        elif field == "title":
            _benchmark(title=value)
        else:
            _benchmark(revision=value)


async def test_the_catalog_keeps_the_field_names_the_leaderboard_seeds_from() -> None:
    """The catalogue is a PUBLISHED contract; the leaderboard reads these exact names.

    INVARIANT: `apps/scoreboard/src/scoreboard/seed.py` fetches this document at deploy and
    maps `title` onto its own `display_name` column. Rename or drop one of the required names
    here and the board stops registering that benchmark — it lands in the seed job's `rejected`
    list, so the benchmark quietly vanishes from the leaderboard while the Engine's own tests
    stay green.

    WHY assert it on this side: the two apps have separate virtualenvs and neither can import
    the other, so no single test can run both halves of the handshake. The producer is the side
    that can break the contract, so the producer is the side that pins it.

    AIDEV-NOTE: changing anything here means changing `_CatalogEntry` in the Scoreboard's
    `seed.py` in the same pull request. `focus` and `dataset_url` are optional on both sides,
    so an older Engine that omits them still seeds correctly.
    """

    required = {"id", "title", "description", "revision"}
    optional_display = {"focus", "dataset_url"}

    for benchmark in BUILTIN_BENCHMARKS:
        entry = await _catalog(benchmark)
        assert required <= set(entry), f"{benchmark.id} lost a field the leaderboard seeds from"
        for name in required:
            assert isinstance(entry[name], str) and entry[name]
        for name in optional_display & set(entry):
            assert isinstance(entry[name], str) and entry[name]


async def test_the_catalogue_publishes_a_usable_case_count() -> None:
    """`case_count` is load-bearing across the app boundary, so its NAME is pinned here.

    FEATURE: OME-1056. The Scoreboard's ranking drops a run that covered fewer cases than the
    benchmark defines, and it learns that number from this catalogue by name. Rename the field
    here — `cases`, `total_cases` — or drop it from `_metadata()`, and both suites stay green:
    the two apps have separate virtualenvs, and the Scoreboard's `_CatalogEntry` uses
    `extra="ignore"` and tolerates a missing count by design. The next seed then writes nothing,
    every board's `case_count` goes stale or absent, and one-case runs rank as complete again.
    Silently, with a deploy that exits 0.

    WHY a separate test rather than adding `case_count` to `required` above: that set's loop
    asserts every member is a non-empty `str`, and this is an `int`. Asserted here instead, so
    no prior assertion changes (rule 5).

    INVARIANT: `>= 1`, matching `SeedBenchmark`'s constraint on the board side. A published `0`
    would be tolerated by the board — costing it the filter, not the benchmark's row — but it is
    not a state any built-in should ever be in, so it fails here, on the producing side, where
    it is a real defect rather than someone else's bad input.
    """
    for benchmark in BUILTIN_BENCHMARKS:
        entry = await _catalog(benchmark)

        assert "case_count" in entry, (
            f"{benchmark.id} does not publish case_count; the leaderboard's coverage filter "
            "reads this field by name and silently ranks partial runs without it"
        )
        count = entry["case_count"]
        assert isinstance(count, int) and not isinstance(count, bool), (
            f"{benchmark.id} publishes case_count as {type(count).__name__}; the board parses "
            "an int and normalises anything else to None, which costs it the filter"
        )
        assert count >= 1, f"{benchmark.id} publishes case_count={count}"

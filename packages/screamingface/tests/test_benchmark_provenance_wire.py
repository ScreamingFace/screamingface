"""OME-1455 — catalogue rows carry the Benchmark Provenance block and the saturation verdict.

Mental model: the Engine prints the exam's cover sheet (paper, authors, who brought it here,
links, licence, how humans and the best published model scored) beside the title, and one
word, saturated / open / unknown, that says whether a win here can still show a capability
difference. The SDK carries all of it verbatim onto the public ``Benchmark``; an older Engine
that never printed the sheet still decodes, with no block and the verdict ``unknown``.

INVARIANT: no test here opens a socket; the catalogue is a mocked transport.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

import screamingface as sf
from screamingface._runtime.bootstrap import scoreboard_seed_json
from screamingface.discovery import Benchmark, BenchmarkProvenance, PublishedScore
from screamingface.errors import PlanningError

_PAPER = "https://arxiv.org/abs/2009.03300"
_HARNESS = "https://github.com/UKGovernmentBEIS/inspect_evals/tree/v0.20.0/src/inspect_evals/mmlu"
_BLOCK: dict[str, object] = {
    "paper_url": _PAPER,
    "authors": "Hendrycks et al., 2020",
    "citation": "@article{hendrycks2020mmlu}",
    "inspect_contributors": ["jjallaire", "domdomegg"],
    "homepage_url": "https://github.com/hendrycks/test",
    "harness_url": _HARNESS,
    "license": "MIT",
    "license_note": "No restriction beyond MIT.",
    "content_warning": "None.",
    "human_baseline": {"score": 0.898, "source_url": _PAPER},
    "frontier_score": {"score": 0.92, "model": "m", "source_url": _PAPER, "as_of": "2026-09"},
    "notebook": "12_inspect_evals_benchmarks",
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example", http_transport=httpx.MockTransport(handler)
    )


def _entry(board_id: str, **extra: object) -> dict[str, object]:
    return {
        "id": board_id,
        "object": "benchmark",
        "title": f"{board_id} title",
        "description": f"{board_id} description.",
        "revision": "rev0000000000000",
        "case_count": 30,
        "href": f"/v1/benchmarks/{board_id}",
        **extra,
    }


def _catalogue(*entries: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks":
            return httpx.Response(200, json={"object": "list", "data": list(entries)})
        return httpx.Response(404)

    return handler


def test_the_whole_block_and_the_verdict_flow_from_the_wire() -> None:
    """INVARIANT: every served provenance key reaches the public Benchmark verbatim — the
    card and the listing (PR 4) render the Engine's words, never a guess."""

    with _client(_catalogue(_entry("mmlu", saturation="saturated", **_BLOCK))) as client:
        benchmark = client.benchmarks.list()[0]

    assert benchmark.saturation == "saturated"
    # Exact, all twelve: a decoder that silently drops one key must fail here (a mutant
    # dropping citation and license_note passed the earlier per-field asserts).
    assert benchmark.provenance == BenchmarkProvenance(
        paper_url=_PAPER,
        authors="Hendrycks et al., 2020",
        citation="@article{hendrycks2020mmlu}",
        inspect_contributors=("jjallaire", "domdomegg"),
        homepage_url="https://github.com/hendrycks/test",
        harness_url=_HARNESS,
        license="MIT",
        license_note="No restriction beyond MIT.",
        content_warning="None.",
        human_baseline=PublishedScore(score=0.898, source_url=_PAPER),
        frontier_score=PublishedScore(score=0.92, source_url=_PAPER, model="m", as_of="2026-09"),
        notebook="12_inspect_evals_benchmarks",
    )


def test_an_engine_that_predates_the_sheet_decodes_with_no_block_and_unknown() -> None:
    # WHY "unknown" and not None: the verdict is a closed word the listing will group on;
    # "no frontier score recorded" is what an older Engine's silence means.
    with _client(_catalogue(_entry("gsm8k"))) as client:
        benchmark = client.benchmarks.list()[0]

    assert benchmark.provenance is None
    assert benchmark.saturation == "unknown"


def test_a_partial_block_keeps_the_keys_the_engine_sent_and_no_others() -> None:
    with _client(_catalogue(_entry("gsm8k", license="MIT", saturation="open"))) as client:
        benchmark = client.benchmarks.list()[0]

    assert benchmark.provenance == BenchmarkProvenance(license="MIT")
    assert benchmark.saturation == "open"


@pytest.mark.parametrize(
    "corrupt",
    [
        {"paper_url": ""},
        {"inspect_contributors": "jjallaire"},
        {"inspect_contributors": ["jjallaire", 7]},
        {"human_baseline": {"score": "high", "source_url": _PAPER}},
        {"frontier_score": {"score": 1.5, "source_url": _PAPER}},
        {"frontier_score": {"score": 0.5}},
        {"saturation": ""},
    ],
    ids=[
        "blank-link",
        "handles-not-a-list",
        "handle-not-text",
        "score-text",
        "score-range",
        "no-source",
        "blank-verdict",
    ],
)
def test_a_present_but_malformed_value_is_a_catalogue_defect(corrupt: dict[str, object]) -> None:
    # The two-axis doctrine: absent means "never declared"; present and wrong is Engine data
    # corruption, surfaced by name rather than coerced to None (OME-1257).
    with (
        _client(_catalogue(_entry("gsm8k", **corrupt))) as client,
        pytest.raises(PlanningError, match="invalid_catalogue|Benchmark"),
    ):
        client.benchmarks.list()


def test_the_verdict_is_an_open_set_on_the_wire() -> None:
    # INVARIANT (origin tolerance doctrine): an older SDK keeps decoding a newer Engine's
    # catalogue when a new verdict word ships; the known words only ORDER the listing.
    with _client(_catalogue(_entry("gsm8k", saturation="plateaued"))) as client:
        assert client.benchmarks.list()[0].saturation == "plateaued"


def test_the_public_benchmark_refuses_a_malformed_block_at_construction() -> None:
    with pytest.raises(ValueError, match="score"):
        PublishedScore(score=2.0, source_url=_PAPER)
    with pytest.raises(TypeError, match="inspect_contributors"):
        BenchmarkProvenance(inspect_contributors="jjallaire")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="saturation"):
        Benchmark(id="x", title="X", description="d", revision="r", case_count=1, saturation="  ")


def test_the_local_seed_twin_carries_the_sheet_and_the_verdict_in_the_seed_row_shape() -> None:
    # INVARIANT: the local board must show what the deployed board shows (OME-904), and the
    # local seed must BOOT. This JSON goes to the Scoreboard's seed-row parser, which forbids
    # unknown keys and holds the block as ONE `provenance` object — not to its catalogue
    # reader, which cuts the block off flat keys. The Scoreboard's
    # `test_the_local_seed_twins_row_shape_is_accepted_by_the_seed_parser` is the other half:
    # it feeds exactly this shape to the real parser. Change one, change both.
    class Definition:
        id = "inspect-mmlu"
        title = "MMLU"
        description = "57 subjects."
        revision = "revision-from-engine"

        def catalog_entry(self) -> dict[str, object]:
            return {"object": "benchmark", "id": self.id, "saturation": "saturated", **_BLOCK}

    row = json.loads(scoreboard_seed_json([Definition()]))[0]  # type: ignore[list-item]

    assert row == {
        "id": "inspect-mmlu",
        "display_name": "MMLU",
        "description": "57 subjects.",
        "revision": "revision-from-engine",
        "provenance": _BLOCK,
        "saturation": "saturated",
    }


def test_a_catalogue_entry_with_only_the_verdict_seeds_no_block() -> None:
    # WHY no `provenance` key rather than {}: the board stores None for "the Engine published
    # none"; an empty object would read as "checked, none".
    class Definition:
        id = "ifeval"
        title = "IFEval"
        description = "d"
        revision = "r"

        def catalog_entry(self) -> dict[str, object]:
            return {"object": "benchmark", "id": self.id, "saturation": "unknown"}

    row = json.loads(scoreboard_seed_json([Definition()]))[0]  # type: ignore[list-item]

    assert "provenance" not in row
    assert row["saturation"] == "unknown"


def test_a_definition_without_a_catalogue_entry_seeds_as_before() -> None:
    class Definition:
        id = "ifeval"
        title = "IFEval"
        description = "d"
        revision = "r"

    row = json.loads(scoreboard_seed_json([Definition()]))[0]  # type: ignore[list-item]

    assert "saturation" not in row and "paper_url" not in row

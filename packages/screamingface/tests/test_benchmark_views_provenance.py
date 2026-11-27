"""OME-1494 — the notebook views show each Benchmark's provenance and saturation.

Mental model: a researcher choosing a Benchmark sees, without leaving the notebook, how it is
graded, who wrote it, how humans and the best published model scored, and whether frontier
models still have room. A Benchmark that declares none of it looks exactly as it did before.

INVARIANTS: a missing field is omitted, never shown as a dash; every link comes from the
Benchmark's own block (no per-origin hardcode); an unknown verdict word renders verbatim.
"""

from __future__ import annotations

from html import unescape

import httpx
import pytest

import screamingface as sf
from screamingface._ui.cards import benchmark_card_html, benchmarks_rows_html
from screamingface._ui.leaderboard_view import leaderboard_html
from screamingface.discovery import Benchmark, BenchmarkProvenance, PublishedScore
from screamingface.leaderboard import Leaderboard, LeaderboardInfo

_PAPER = "https://arxiv.org/abs/2110.14168"
_HARNESS = "https://github.com/openai/grade-school-math"
_HOME = "https://openai.com/index/solving-math-word-problems/"
_FRONTIER = PublishedScore(score=0.968, source_url=_PAPER, model="Llama 3.1 405B", as_of="2024-07")
_HUMANS = PublishedScore(score=0.9, source_url=_HOME)
_FULL = BenchmarkProvenance(
    paper_url=_PAPER,
    authors="Cobbe et al., 2021",
    harness_url=_HARNESS,
    homepage_url=_HOME,
    license="MIT",
    license_note="No restriction beyond MIT.",
    content_warning="Contains arithmetic.",
    human_baseline=_HUMANS,
    frontier_score=_FRONTIER,
    notebook="12_inspect_evals_benchmarks",
)


def _benchmark(**extra: object) -> Benchmark:
    fields: dict[str, object] = {
        "id": "inspect-gsm8k",
        "title": "GSM8K",
        "description": "Grade-school math.",
        "revision": "rev0000000000000",
        "case_count": 1319,
        "origin": "inspect_evals",
        **extra,
    }
    return Benchmark(**fields)  # type: ignore[arg-type]


def _body(html: str) -> str:
    """The markup after the shared stylesheet, whose comments hold dashes of their own."""

    return unescape(html).split("</style>")[-1]


def _full() -> Benchmark:
    return _benchmark(provenance=_FULL, saturation="saturated")


def test_a_bare_benchmark_shows_none_of_the_block() -> None:
    row = _body(benchmarks_rows_html([_benchmark()]))
    card = _body(benchmark_card_html(_benchmark()))

    for html in (row, card):
        assert "saturation" not in html.lower()
        assert "authors" not in html
        assert "frontier" not in html.lower()
        assert "—" not in html
        assert " - " not in html


def test_the_listing_row_shows_cases_and_the_verdict() -> None:
    row = unescape(benchmarks_rows_html([_full()]))

    assert "1319 cases" in row
    assert "saturation: saturated" in row


def test_an_unknown_verdict_word_renders_verbatim_and_unstyled() -> None:
    row = benchmarks_rows_html([_benchmark(saturation="plateaued")])

    assert "<span class='sf-chip'>saturation: plateaued</span>" in row


def test_an_unknown_verdict_means_no_mark() -> None:
    assert "saturation" not in benchmarks_rows_html([_benchmark(saturation="unknown")])


def test_the_card_shows_the_block() -> None:
    card = unescape(benchmark_card_html(_full()))

    assert "Cobbe et al., 2021" in card
    assert f"href='{_PAPER}'" in card
    assert f"href='{_HARNESS}'" in card
    assert f"href='{_HOME}'" in card
    assert "MIT" in card and "No restriction beyond MIT." in card
    assert "90.0%" in card
    assert "96.8%" in card and "Llama 3.1 405B" in card and "2024-07" in card
    assert "Contains arithmetic." in card
    assert "12_inspect_evals_benchmarks" in card
    assert "saturated" in card


def test_an_absent_field_leaves_no_placeholder() -> None:
    sparse = _benchmark(
        provenance=BenchmarkProvenance(authors="Cobbe et al., 2021"), saturation="open"
    )
    card = _body(benchmark_card_html(sparse))

    assert "Cobbe et al., 2021" in card
    for label in ("paper", "harness", "licence", "humans", "frontier", "warning", "notebook"):
        assert f">{label}<" not in card
    assert "—" not in card


def test_links_come_from_the_benchmarks_own_block_not_the_origin() -> None:
    for origin in ("inspect_evals", "screamingface"):
        html = benchmark_card_html(_benchmark(origin=origin)) + benchmarks_rows_html(
            [_benchmark(origin=origin)]
        )

        assert "ukgovernmentbeis.github.io" not in html
        assert "leaderboard.screamingface.ai" not in html


def test_a_link_that_is_not_http_is_not_rendered_as_a_link() -> None:
    card = benchmark_card_html(
        _benchmark(provenance=BenchmarkProvenance(paper_url="javascript:alert(1)"))
    )

    assert "href='javascript" not in card


def test_the_block_is_escaped() -> None:
    card = benchmark_card_html(
        _benchmark(provenance=BenchmarkProvenance(authors="<script>x</script>"))
    )

    assert "<script>" not in card


def _info(**extra: object) -> LeaderboardInfo:
    fields: dict[str, object] = {
        "id": "inspect-gsm8k",
        "display_name": "GSM8K",
        "description": None,
        "dataset_url": None,
        "created_at": __import__("datetime").datetime(
            2026, 8, 1, tzinfo=__import__("datetime").UTC
        ),
        **extra,
    }
    return LeaderboardInfo(**fields)  # type: ignore[arg-type]


def _board(info: LeaderboardInfo) -> Leaderboard:
    return Leaderboard(benchmark=info, entries=(), baselines=())


def test_the_leaderboard_view_shows_the_same_strip() -> None:
    html = _body(leaderboard_html(_board(_info(provenance=_FULL, saturation="saturated"))))

    assert "Cobbe et al., 2021" in html
    assert f"href='{_PAPER}'" in html
    assert "96.8%" in html and "saturated" in html
    assert html.index("Cobbe") < html.index("sf-lb__table")


def test_a_leaderboard_without_the_block_renders_as_today() -> None:
    html = _body(leaderboard_html(_board(_info())))

    assert "Cobbe" not in html and "saturation" not in html.lower()
    assert "sf-lb__strip" not in html


def _scoreboard_client(benchmark: dict[str, object]) -> sf.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"benchmarks": [benchmark]})

    return sf.Client(
        engine_url="https://engine.example",
        scoreboard_url="https://scoreboard.example",
        scoreboard_transport=httpx.MockTransport(handler),
    )


_WIRE: dict[str, object] = {
    "id": "inspect-gsm8k",
    "display_name": "GSM8K",
    "description": None,
    "dataset_url": None,
    "created_at": "2026-08-01T10:00:00Z",
}


def test_the_scoreboard_block_decodes_onto_the_leaderboard_info() -> None:
    wire = {
        **_WIRE,
        "saturation": "saturated",
        "provenance": {
            "paper_url": _PAPER,
            "authors": "Cobbe et al., 2021",
            "inspect_contributors": ["jjallaire"],
            "human_baseline": {"score": 0.9, "source_url": _HOME},
            "frontier_score": {
                "score": 0.968,
                "source_url": _PAPER,
                "model": "Llama 3.1 405B",
                "as_of": "2024-07",
            },
        },
    }
    with _scoreboard_client(wire) as client:
        info = client.leaderboards.list()[0]

    assert info.saturation == "saturated"
    assert info.provenance == BenchmarkProvenance(
        paper_url=_PAPER,
        authors="Cobbe et al., 2021",
        inspect_contributors=("jjallaire",),
        human_baseline=_HUMANS,
        frontier_score=_FRONTIER,
    )


@pytest.mark.parametrize(
    "extra", [{}, {"provenance": None, "saturation": None}], ids=["keys absent", "null"]
)
def test_an_older_scoreboard_decodes_without_the_block(extra: dict[str, object]) -> None:
    with _scoreboard_client({**_WIRE, **extra}) as client:
        info = client.leaderboards.list()[0]

    assert info.provenance is None
    assert info.saturation is None


@pytest.mark.parametrize(
    "block",
    ["text", {"paper_url": 3}, {"frontier_score": {"score": "x", "source_url": _PAPER}}],
)
def test_a_malformed_block_is_refused_by_name(block: object) -> None:
    with _scoreboard_client({**_WIRE, "provenance": block}) as client:
        with pytest.raises(sf.LeaderboardError, match="Invalid Scoreboard Leaderboard response"):
            client.leaderboards.list()

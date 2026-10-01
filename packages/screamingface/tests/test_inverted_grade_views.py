"""OME-1400 PR 3 — a researcher SEES the inverted_grade mark in the notebook, not just in JSON.

FEATURE: safety Benchmarks where refusing is the right answer. Three places a researcher looks:

    before a run:  sf.benchmarks listing row  ──► "inverted grade" chip
                   a Benchmark's card         ──► a "grading" line in plain words
    after a run:   the notebook report view   ──► the same sentence under the header

INVARIANT: only a flipped Benchmark gets any of it — every other Benchmark's markup is unchanged,
so the mark stays a signal instead of noise.
"""

from __future__ import annotations

from collections.abc import Callable
from html import unescape

import httpx
import pytest
from test_draco_vertical_slice import _engine as _draco_engine
from test_draco_vertical_slice import _FakeTransport
from test_inverted_grade_report import _evaluate, _marked_engine, _result_payload

import screamingface as sf
from screamingface._ui.cards import benchmark_card_html, benchmarks_rows_html
from screamingface._ui.report_view import report_html
from screamingface.discovery import Benchmark
from screamingface.errors import PlanningError

#: The one plain sentence every view uses — a researcher meets the same words everywhere.
_MEANING = "each Case scores 1 − the eval's grade"


def _benchmark(*, inverted_grade: bool) -> Benchmark:
    return Benchmark(
        id="inspect-xstest_unsafe",
        title="XSTest (unsafe prompts)",
        description="200 unsafe prompts.",
        revision="rev0000000000000",
        case_count=200,
        inverted_grade=inverted_grade,
    )


def _catalogue(**extra: object) -> Callable[[httpx.Request], httpx.Response]:
    entry: dict[str, object] = {
        "id": "inspect-xstest_unsafe",
        "object": "benchmark",
        "title": "XSTest (unsafe prompts)",
        "description": "200 unsafe prompts.",
        "revision": "rev0000000000000",
        "case_count": 200,
        "href": "/v1/benchmarks/inspect-xstest_unsafe",
        **extra,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks":
            return httpx.Response(200, json={"object": "list", "data": [entry]})
        return httpx.Response(404)

    return handler


def _listed(**extra: object) -> Benchmark:
    client = sf.Client(
        engine_url="https://engine.example", http_transport=httpx.MockTransport(_catalogue(**extra))
    )
    with client:
        return client.benchmarks.list()[0]


# ── the catalogue carries the mark ───────────────────────────────────────────────


def test_the_listing_carries_the_engines_mark() -> None:
    assert _listed(inverted_grade=True).inverted_grade is True


def test_an_engine_without_the_mark_lists_an_ordinary_benchmark() -> None:
    """The Engine publishes the key only when true; an older one never does."""

    assert _listed().inverted_grade is False


def test_a_non_boolean_mark_in_the_catalogue_is_refused() -> None:
    with pytest.raises(PlanningError, match="inverted_grade"):
        _listed(inverted_grade="yes")


# ── the listing row and the card show it ─────────────────────────────────────────


def test_a_flipped_benchmarks_row_and_card_say_so_in_plain_words() -> None:
    row: str = unescape(benchmarks_rows_html([_benchmark(inverted_grade=True)]))
    card: str = unescape(benchmark_card_html(_benchmark(inverted_grade=True)))

    assert ">inverted grade<" in row
    assert _MEANING in row  # the chip's hover title
    assert _MEANING in card


def test_an_ordinary_benchmarks_row_and_card_are_unchanged() -> None:
    row: str = unescape(benchmarks_rows_html([_benchmark(inverted_grade=False)]))
    card: str = unescape(benchmark_card_html(_benchmark(inverted_grade=False)))

    assert "inverted grade" not in row
    assert _MEANING not in card


# ── the notebook report view shows it ────────────────────────────────────────────


def test_a_flipped_benchmarks_report_view_says_so_under_the_header() -> None:
    report = _evaluate(_marked_engine, _FakeTransport(_result_payload(inverted_grade=True)))

    assert _MEANING in unescape(report_html(report))


def test_an_ordinary_report_view_says_nothing_about_it() -> None:
    report = _evaluate(_draco_engine, _FakeTransport(_result_payload()))

    assert _MEANING not in unescape(report_html(report))

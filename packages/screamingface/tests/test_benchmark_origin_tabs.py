"""OME-1114 — the benchmark catalogue renders one tab per origin, linked to its source.

Mental model: the Engine stamps every benchmark with where it came from (OME-1112);
the SDK is the shelf display. One tab per origin — "ScreamingFace" and
"inspect_evals" — each linking to its source collection, so a researcher scanning
the catalogue always knows which boards we authored and which we imported.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest

import screamingface as sf
from screamingface.discovery import Benchmark
from screamingface.errors import PlanningError

LEADERBOARD_URL = "https://leaderboard.dev.screamingface.ai/"
INSPECT_EVALS_URL = "https://ukgovernmentbeis.github.io/inspect_evals/"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
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


def _mixed_handler() -> Callable[[httpx.Request], httpx.Response]:
    return _catalogue(
        _entry("draco", origin="screamingface"),
        _entry("gaia", origin="inspect_evals"),
    )


def _walk(widget: Any) -> tuple[Any, ...]:
    children = getattr(widget, "children", ())
    return (widget, *(item for child in children for item in _walk(child)))


# ── decode ────────────────────────────────────────────────────────────────────


def test_origin_flows_from_the_wire_and_defaults_for_older_engines() -> None:
    """INVARIANT: origin is the Engine's word carried verbatim; an Engine predating
    OME-1112 (no origin key) still decodes as our own shelf, never an error."""

    with _client(_catalogue(_entry("draco"), _entry("gaia", origin="inspect_evals"))) as client:
        benchmarks = client.benchmarks.list()

    assert benchmarks[0].origin == "screamingface"
    assert benchmarks[1].origin == "inspect_evals"


def test_unknown_origin_still_decodes() -> None:
    """INVARIANT: the SDK never validates origin against the Engine's closed set —
    an older SDK must not brick against a newer Engine that ships a new origin."""

    with _client(_catalogue(_entry("draco", origin="helm"))) as client:
        benchmarks = client.benchmarks.list()

    assert benchmarks[0].origin == "helm"


@pytest.mark.parametrize("bad_origin", ["", "   ", 7])
def test_blank_or_nonstring_origin_is_a_catalogue_defect(bad_origin: object) -> None:
    with _client(_catalogue(_entry("draco", origin=bad_origin))) as client:
        with pytest.raises(PlanningError) as caught:
            client.benchmarks.list()

    assert caught.value.code == "invalid_catalogue"


def test_benchmark_value_refuses_blank_origin() -> None:
    with pytest.raises(ValueError, match="origin"):
        Benchmark(
            id="draco",
            title="DRACO",
            description="A tiny probe tier.",
            revision="rev0000000000000",
            case_count=30,
            origin="   ",
        )


# ── static HTML fallback ──────────────────────────────────────────────────────


def test_mixed_catalogue_static_html_shows_one_group_per_origin_with_source_links() -> None:
    with _client(_mixed_handler()) as client:
        benchmarks = client.benchmarks.list()

    html = cast(Any, benchmarks)._repr_html_()
    assert "ScreamingFace" in html
    assert "inspect_evals" in html
    assert LEADERBOARD_URL in html
    assert INSPECT_EVALS_URL in html
    # WHY: our shelf always leads — deterministic order regardless of wire order.
    assert html.index("ScreamingFace") < html.index("inspect_evals")


def test_unmapped_origin_renders_its_own_group_without_a_link() -> None:
    with _client(_catalogue(_entry("draco"), _entry("mystery", origin="helm"))) as client:
        benchmarks = client.benchmarks.list()

    html = cast(Any, benchmarks)._repr_html_()
    assert "helm" in html
    # WHY: only mapped origins get a source anchor — one here (screamingface's).
    assert html.count("<a ") == 1


def test_screamingface_only_catalogue_keeps_repr_and_gains_the_leaderboard_link() -> None:
    """The prior cycle's `Benchmarks(N)` repr is a pinned contract; the single-tab
    rendering still shows where our shelf lives."""

    with _client(_catalogue(_entry("draco"))) as client:
        benchmarks = client.benchmarks.list()

    assert repr(benchmarks) == "Benchmarks(1)"
    html = cast(Any, benchmarks)._repr_html_()
    assert LEADERBOARD_URL in html


# ── interactive widget ────────────────────────────────────────────────────────


def test_widget_renders_one_tab_per_origin_with_titles_and_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets = pytest.importorskip("ipywidgets")
    display_module = pytest.importorskip("IPython.display")

    with _client(_mixed_handler()) as client:
        benchmarks = client.benchmarks.list()

    shown: list[Any] = []
    monkeypatch.setattr(display_module, "display", lambda value: shown.append(value))
    cast(Any, benchmarks)._ipython_display_()

    tab = next(item for item in _walk(shown[0]) if isinstance(item, widgets.Tab))
    titles = tuple(tab.get_title(index) for index in range(len(tab.children)))
    assert titles == ("ScreamingFace", "inspect_evals")

    bodies = [
        item.value
        for item in _walk(tab)
        if isinstance(item, widgets.HTML) and isinstance(item.value, str)
    ]
    assert any(LEADERBOARD_URL in body for body in bodies)
    assert any(INSPECT_EVALS_URL in body for body in bodies)
    assert any("draco title" in body for body in bodies)
    assert any("gaia title" in body for body in bodies)


def test_widget_search_filters_rows_inside_every_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    widgets = pytest.importorskip("ipywidgets")
    display_module = pytest.importorskip("IPython.display")

    with _client(_mixed_handler()) as client:
        benchmarks = client.benchmarks.list()

    shown: list[Any] = []
    monkeypatch.setattr(display_module, "display", lambda value: shown.append(value))
    cast(Any, benchmarks)._ipython_display_()

    search = next(item for item in _walk(shown[0]) if isinstance(item, widgets.Text))
    search.value = "does-not-exist"
    bodies = "\n".join(
        item.value
        for item in _walk(shown[0])
        if isinstance(item, widgets.HTML) and isinstance(item.value, str)
    )
    assert "No benchmarks match." in bodies
    assert "draco title" not in bodies
    assert "gaia title" not in bodies

    # STORY: as a researcher I clear the filter and both shelves come back.
    search.value = ""
    bodies = "\n".join(
        item.value
        for item in _walk(shown[0])
        if isinstance(item, widgets.HTML) and isinstance(item.value, str)
    )
    assert "draco title" in bodies
    assert "gaia title" in bodies


# ── benchmark card ────────────────────────────────────────────────────────────


def test_benchmark_card_shows_origin_and_its_source_link() -> None:
    with _client(_mixed_handler()) as client:
        imported = client.benchmarks.get("gaia")

    html = cast(Any, imported)._repr_html_()
    assert "origin" in html
    assert "inspect_evals" in html
    assert INSPECT_EVALS_URL in html

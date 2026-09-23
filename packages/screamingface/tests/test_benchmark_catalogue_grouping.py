"""OME-1257 — the catalogue reads as a two-axis map with clickable facet chips.

Mental model: the flat shelf becomes a library floor plan. Walking easy→hard, the
reader passes the Easy shelf (quick-signal boards frontier models saturate), the
Medium shelf (real headroom, no expert stakes), and the Hard shelf (expert-written
work the best models visibly fail). Within a shelf, boards stand in interaction
lanes — single-shot first, then multi-turn. In a notebook, two chip rows sit above
the listing — Difficulty: All/Easy/Medium/Hard and Interaction: All/Single-shot/
Multi-turn/Agentic — and clicking a chip regroups the listing to that facet, with
the search box composing on top. Every board keeps its provenance chip
(ScreamingFace / inspect_evals, linked to its source collection), so the OME-1114
grouping survives as per-row provenance.

A catalogue from an Engine that predates the axis (every difficulty None) renders as
the familiar flat list — the map appears the moment the Engine starts serving tiers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest

import screamingface as sf
from screamingface._ui.cards import ALL_CHIP_VALUE

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


def _two_tier_handler() -> Callable[[httpx.Request], httpx.Response]:
    # WHY hard FIRST on the wire: the tests below assert display order is the
    # declared easy→hard order, never the wire order.
    return _catalogue(
        _entry("hle", difficulty="hard", interaction="multi_turn", origin="inspect_evals"),
        _entry("gsm8k", difficulty="easy", interaction="single_shot", origin="inspect_evals"),
        _entry("draco", difficulty="hard", interaction="single_shot", origin="screamingface"),
    )


def _walk(widget: Any) -> tuple[Any, ...]:
    children = getattr(widget, "children", ())
    return (widget, *(item for child in children for item in _walk(child)))


def _static_html(handler: Callable[[httpx.Request], httpx.Response]) -> str:
    with _client(handler) as client:
        return cast(Any, client.benchmarks.list())._repr_html_()


def _displayed_root(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> Any:
    display_module = pytest.importorskip("IPython.display")
    with _client(handler) as client:
        benchmarks = client.benchmarks.list()
    shown: list[Any] = []
    monkeypatch.setattr(display_module, "display", lambda value: shown.append(value))
    cast(Any, benchmarks)._ipython_display_()
    return shown[0]


def _chip_group(root: Any, description: str) -> Any:
    import ipywidgets as widgets

    return next(
        item
        for item in _walk(root)
        if isinstance(item, widgets.ToggleButtons) and item.description == description
    )


def _html_bodies(root: Any) -> str:
    import ipywidgets as widgets

    return "\n".join(
        item.value
        for item in _walk(root)
        if isinstance(item, widgets.HTML) and isinstance(item.value, str)
    )


# ── static HTML: the map ─────────────────────────────────────────────────────


def test_tiers_render_in_declared_easy_to_hard_order_not_wire_order() -> None:
    # INVARIANT: the reading direction of the map IS the declared tier order —
    # easy before hard, whatever order the Engine served the rows in.
    html = _static_html(_two_tier_handler())
    assert "Easy" in html
    assert "Hard" in html
    assert html.index("Easy") < html.index("Hard")
    # The board rows landed under their tiers.
    assert html.index("gsm8k title") < html.index("draco title")


def test_interaction_lanes_render_inside_a_tier() -> None:
    # STORY: as a researcher, inside the Hard shelf I can tell the one-prompt
    # boards from the interactive work at a glance.
    html = _static_html(_two_tier_handler())
    assert "Single-shot" in html
    assert "Multi-turn" in html
    hard_at = html.index("Hard")
    assert html.index("Single-shot", hard_at) < html.index("Multi-turn", hard_at)
    assert html.index("draco title") < html.index("hle title")


def test_every_row_carries_its_provenance_chip_linked_to_the_source() -> None:
    # DON'T-REGRESS (OME-1114): moving provenance from top-level tabs to per-row
    # chips must keep both the ours/imported distinction and the source links.
    html = _static_html(_two_tier_handler())
    assert "ScreamingFace" in html
    assert "inspect_evals" in html
    assert LEADERBOARD_URL in html
    assert INSPECT_EVALS_URL in html


def test_unmapped_origin_chip_renders_without_a_link() -> None:
    html = _static_html(_catalogue(_entry("mystery", difficulty="hard", origin="helm")))
    assert "helm" in html
    assert "<a " not in html


def test_unknown_tier_renders_its_own_section_after_the_declared_tiers() -> None:
    # INVARIANT: the SDK never refuses a newer Engine's new tier — it renders as its
    # own shelf AFTER the declared ones, named by the Engine's word verbatim.
    html = _static_html(
        _catalogue(
            _entry("novel", difficulty="olympian"),
            _entry("gsm8k", difficulty="easy"),
        )
    )
    assert html.index("Easy") < html.index("olympian")


def test_undeclared_tier_rows_gather_in_a_trailing_unspecified_shelf() -> None:
    # WHY: a mixed catalogue (new boards declared, one old row without a tier) must
    # not hide the undeclared row — it gathers under "Unspecified", last.
    html = _static_html(
        _catalogue(
            _entry("gsm8k", difficulty="easy"),
            _entry("legacy"),
        )
    )
    assert html.index("Easy") < html.index("Unspecified")
    assert "legacy title" in html


def test_catalogue_without_any_tier_keeps_the_flat_list() -> None:
    # INVARIANT: an Engine predating OME-1257 (no difficulty anywhere) renders the
    # familiar flat rows — no lone "Unspecified" shelf pretending to be structure.
    html = _static_html(_catalogue(_entry("draco"), _entry("gaia", origin="inspect_evals")))
    assert "Unspecified" not in html
    assert "draco title" in html and "gaia title" in html


# ── interactive widget: facet chips over the map ─────────────────────────────


def test_widget_renders_both_chip_rows_with_all_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # STORY: as a researcher I see the two facets up front — Difficulty chips in
    # easy→hard order and Interaction chips including the not-yet-populated
    # Agentic lane — with All active, so the full map shows by default.
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    difficulty = _chip_group(root, "Difficulty:")
    interaction = _chip_group(root, "Interaction:")
    assert [label for label, _ in difficulty.options] == ["All", "Easy", "Medium", "Hard"]
    assert [label for label, _ in interaction.options] == [
        "All",
        "Single-shot",
        "Multi-turn",
        "Agentic",
    ]
    assert difficulty.value == ALL_CHIP_VALUE and interaction.value == ALL_CHIP_VALUE
    bodies = _html_bodies(root)
    assert "gsm8k title" in bodies and "draco title" in bodies and "hle title" in bodies


def test_clicking_a_difficulty_chip_regroups_to_that_shelf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: chips FILTER what the map shows without changing its shape —
    # clicking Easy reads as "the Easy shelf", tagline and lanes intact.
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    _chip_group(root, "Difficulty:").value = "easy"
    bodies = _html_bodies(root)
    assert "gsm8k title" in bodies
    assert "draco title" not in bodies and "hle title" not in bodies
    assert "Easy" in bodies and "Single-shot" in bodies


def test_clicking_an_interaction_chip_composes_with_difficulty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    _chip_group(root, "Interaction:").value = "multi_turn"
    bodies = _html_bodies(root)
    assert "hle title" in bodies
    assert "draco title" not in bodies and "gsm8k title" not in bodies
    # Composing the two facets: multi-turn ∩ easy = nothing.
    _chip_group(root, "Difficulty:").value = "easy"
    bodies = _html_bodies(root)
    assert "hle title" not in bodies
    assert "No benchmarks match." in bodies


def test_the_agentic_chip_shows_an_honest_empty_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # STORY: as a researcher clicking Agentic today, I learn the lane exists and is
    # empty — not that my filter "broke" (visible empty state, OME-1257).
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    _chip_group(root, "Interaction:").value = "agentic"
    bodies = _html_bodies(root)
    assert "No agentic benchmarks yet" in bodies


def test_search_composes_with_the_chips_and_clearing_restores_the_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widgets = pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    search = next(item for item in _walk(root) if isinstance(item, widgets.Text))

    _chip_group(root, "Difficulty:").value = "hard"
    search.value = "draco"
    bodies = _html_bodies(root)
    assert "draco title" in bodies
    assert "hle title" not in bodies

    # STORY: as a researcher I clear the filter and the whole map comes back.
    search.value = ""
    _chip_group(root, "Difficulty:").value = ALL_CHIP_VALUE
    bodies = _html_bodies(root)
    assert "draco title" in bodies and "hle title" in bodies and "gsm8k title" in bodies


def test_the_all_chip_is_a_real_value_never_the_no_selection_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY: ipywidgets treats value None as "no selection" — an All chip valued None
    # filters correctly on click but the frontend clears every highlight, so All
    # only turns active on a SECOND click (owner-reported). All must be a real
    # selectable value on every axis row.
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    for description in ("Difficulty:", "Interaction:", "Origin:"):
        group = _chip_group(root, description)
        values = [value for _, value in group.options]
        assert None not in values
        assert group.value == values[0]  # All selected — and highlightable — by default


def test_the_listing_body_scrolls_instead_of_growing_the_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # STORY: as a researcher with 25 boards, the listing scrolls inside the widget
    # after roughly a screenful instead of stretching the notebook cell to the full
    # catalogue height (owner request, OME-1257).
    widgets = pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    rows = [
        item
        for item in _walk(root)
        if isinstance(item, widgets.HTML) and "sf-catalog__scroll" in item._dom_classes
    ]
    assert len(rows) == 1  # exactly the rows body scrolls — never the chips or search


def test_widget_without_any_tier_keeps_flat_rows_under_the_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: an old-Engine catalogue stays a flat list (no tier sections), but
    # the chips still render — selecting Easy over it simply shows the empty state.
    pytest.importorskip("ipywidgets")
    root = _displayed_root(
        monkeypatch, _catalogue(_entry("draco"), _entry("gaia", origin="inspect_evals"))
    )
    bodies = _html_bodies(root)
    assert "draco title" in bodies and "gaia title" in bodies
    assert "Unspecified" not in bodies
    _chip_group(root, "Difficulty:").value = "easy"
    assert "No benchmarks match." in _html_bodies(root)


def test_widget_renders_an_origin_chip_row_from_the_origins_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY options derive from the catalogue, not a fixed vocabulary: origin is an
    # OPEN set by doctrine (OME-1114) — a newer Engine's new origin gets its own
    # chip instead of being invisible. Our shelf leads when present.
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    origin = _chip_group(root, "Origin:")
    assert [label for label, _ in origin.options] == ["All", "ScreamingFace", "inspect_evals"]
    assert origin.value == ALL_CHIP_VALUE


def test_clicking_an_origin_chip_filters_but_keeps_the_map_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # STORY: as a researcher clicking inspect_evals, I see only imported boards —
    # still shelved easy→hard with their lanes, not a different view.
    pytest.importorskip("ipywidgets")
    root = _displayed_root(monkeypatch, _two_tier_handler())
    _chip_group(root, "Origin:").value = "inspect_evals"
    bodies = _html_bodies(root)
    assert "gsm8k title" in bodies and "hle title" in bodies
    assert "draco title" not in bodies
    assert "Easy" in bodies and "Hard" in bodies  # the map shape survives the filter
    # Composing with difficulty: imported ∩ hard = hle only.
    _chip_group(root, "Difficulty:").value = "hard"
    bodies = _html_bodies(root)
    assert "hle title" in bodies
    assert "gsm8k title" not in bodies


def test_an_unmapped_origin_gets_its_own_chip_named_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("ipywidgets")
    root = _displayed_root(
        monkeypatch,
        _catalogue(
            _entry("mystery", difficulty="hard", origin="helm"),
            _entry("draco", difficulty="hard", origin="screamingface"),
        ),
    )
    origin = _chip_group(root, "Origin:")
    assert [label for label, _ in origin.options] == ["All", "ScreamingFace", "helm"]
    origin.value = "helm"
    bodies = _html_bodies(root)
    assert "mystery title" in bodies
    assert "draco title" not in bodies

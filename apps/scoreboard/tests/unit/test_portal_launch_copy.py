"""OME-1595: marketing's P0 copy and UI fixes on the leaderboard launch pages.

FEATURE: the public leaderboard launch surfaces (landing, board, submission history, about, data).
STORY: as a first-time visitor from the launch post, I read plain words ("submission", "home"),
see the research-grant call on every page, and land on the right docs page from every CTA.

WHY parsed, not searched: every assertion reads an element's text or attribute from a parsed
tree (stdlib `html.parser`). A substring search over the raw file would pass on a comment, on a
neighbouring element, or on markup that renders differently (owner rule: no regex, no substring
checks over whole files).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parents[2] / "portal"
_PAGES = ("index.html", "benchmark.html", "spec.html", "about.html", "data.html")
_VOID = {"meta", "link", "img", "br", "hr", "input", "source", "wbr", "area", "base", "col"}

_GRANT_TEXT = "Open call for research grants to explore ensembles & routers →"
_GRANT_HREF = "https://openmined.org/research/grants/"
_FIRST_FUSION = "https://docs.screamingface.ai/sf-client/first-fusion"
_URL4_DOCS = "https://docs.screamingface.ai/learn/url4"
_NOTE_COPY = (
    "The leaderboard's top row is the current state of the art. Every submission carries its "
    "url4 expression, a complete recipe for the run. Copy it with the Copy button in the Run "
    "Locally column to rerun, verify or build on any score here."
)


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    order: int
    parent: _Node | None = None
    children: list[_Node | str] = field(default_factory=lambda: [])

    @property
    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()

    def text(self) -> str:
        """Rendered-ish text: descendants' character data, whitespace collapsed."""
        parts: list[str] = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return " ".join("".join(parts).split())

    def walk(self) -> list[_Node]:
        found: list[_Node] = [self]
        for child in self.children:
            if isinstance(child, _Node):
                found.extend(child.walk())
        return found

    def find(self, tag: str | None = None, cls: str | None = None, **attrs: str) -> list[_Node]:
        return [
            node
            for node in self.walk()
            if (tag is None or node.tag == tag)
            and (cls is None or cls in node.classes)
            and all(node.attrs.get(name) == value for name, value in attrs.items())
        ]

    def one(self, tag: str | None = None, cls: str | None = None, **attrs: str) -> _Node:
        matches = self.find(tag, cls, **attrs)
        assert len(matches) == 1, f"expected one <{tag} class={cls} {attrs}>, got {len(matches)}"
        return matches[0]


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.root = _Node("#document", {}, 0)
        self._open = self.root
        self._count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._count += 1
        node = _Node(tag, {k: v or "" for k, v in attrs}, self._count, self._open)
        self._open.children.append(node)
        if tag not in _VOID:
            self._open = node

    def handle_endtag(self, tag: str) -> None:
        node: _Node | None = self._open
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._open = node.parent

    def handle_data(self, data: str) -> None:
        self._open.children.append(data)


def _page(name: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed((_PORTAL / name).read_text(encoding="utf-8"))
    builder.close()
    return builder.root


def _assert_new_tab(link: _Node) -> None:
    assert link.attrs.get("target") == "_blank"
    assert "noopener" in link.attrs.get("rel", "").split()


# ---- every page: grant banner and rail ------------------------------------------------------


@pytest.mark.parametrize("page", _PAGES)
def test_every_page_opens_with_the_grant_banner_above_the_rail(page: str) -> None:
    doc = _page(page)
    body = doc.one("body")
    banner = doc.one(cls="grant-banner")
    rail = doc.one("div", "rail")

    # INVARIANT: the banner is the body's first element and sits above the rail.
    first_element = next(child for child in body.children if isinstance(child, _Node))
    assert first_element is banner
    assert banner.order < rail.order

    links = banner.find("a")
    assert len(links) == 1, "the banner is one link"
    assert links[0].text() == _GRANT_TEXT
    assert links[0].attrs.get("href") == _GRANT_HREF
    _assert_new_tab(links[0])
    # Fixed, not dismissible: nothing in it can be clicked except the link.
    assert banner.find("button") == []


@pytest.mark.parametrize("page", _PAGES)
def test_every_rail_says_home_and_points_to_the_landing_page(page: str) -> None:
    nav = _page(page).one("nav", "rail-nav")
    links = [(a.text(), a.attrs.get("href")) for a in nav.find("a")]

    assert links[0] == ("home", "index.html")
    assert [text for text, _ in links] == ["home", "about", "github", "docs"]


# ---- landing and about ---------------------------------------------------------------------


def test_landing_get_started_goes_to_first_fusion() -> None:
    cta = _page("index.html").one(cls="hero-cta").one("a", "btn--primary")

    assert cta.text() == "Get started with ScreamingFace →"
    assert cta.attrs.get("href") == _FIRST_FUSION


def test_about_lead_copy() -> None:
    lead = _page("about.html").one("p", "hero-lead")

    assert lead.text() == (
        "What's the best accuracy anyone can reach at a price point they can afford, and "
        "which combination of models gets them there?"
    )


@pytest.mark.parametrize("section", ["how-a-result", "contribute"])
def test_about_url4_is_a_plain_docs_link(section: str) -> None:
    block = _page("about.html").one("section", **{"data-section": section})
    url4 = [a for a in block.find("a") if a.text() == "url4"]

    assert len(url4) == 1
    assert url4[0].attrs.get("href") == _URL4_DOCS
    _assert_new_tab(url4[0])
    # The boxed <code> style is gone (marketing review).
    assert block.find("code") == []


def test_about_contribute_links() -> None:
    links = (
        _page("about.html").one("section", **{"data-section": "contribute"}).one("p", "about-links")
    )
    by_text = {a.text(): a.attrs.get("href") for a in links.find("a")}

    assert by_text["Start fusing →"] == _FIRST_FUSION
    assert by_text["Browse leaderboards →"] == "index.html"
    assert by_text["Get paid to try →"] == _GRANT_HREF


_ARXIV = "https://arxiv.org/abs/"


def test_about_papers_carousel_cites_arxiv() -> None:
    strip = _page("about.html").one("div", "papers")
    # Keyboard-scrollable and named for assistive tech, like the portal's other scroll strips.
    assert strip.attrs.get("tabindex") == "0"
    assert strip.attrs.get("aria-label")

    cards = strip.find("div", "paper-card")
    assert len(cards) == 11, f"expected 11 paper cards, got {len(cards)}"
    for card in cards:
        # Each card is just the paper's first-page image, linking to the paper on arXiv.
        link = card.one("a", "paper-card__link")
        href = link.attrs.get("href", "")
        assert href.startswith(_ARXIV), f"paper image must link to arXiv, got {href!r}"
        _assert_new_tab(link)
        # The image carries the paper's identity in its alt text (no visible title/abstract).
        thumb = link.one("img", "paper-card__thumb")
        assert thumb.attrs.get("alt")


def test_about_openmined_links_to_openmined() -> None:
    block = _page("about.html").one("section", **{"data-section": "who-builds-this"})
    links = [a for a in block.find("a") if a.text() == "OpenMined"]

    assert len(links) == 1
    assert links[0].attrs.get("href") == "https://openmined.org"
    _assert_new_tab(links[0])


# ---- board page ----------------------------------------------------------------------------


def test_board_about_note_carries_the_approved_copy_and_url4_link() -> None:
    note = _page("benchmark.html").one("div", "note")
    kicker = note.one("span", "kicker")
    body = " ".join(
        (child if isinstance(child, str) else child.text())
        for child in note.children
        if child is not kicker
    )

    assert kicker.text() == "about"
    assert " ".join(body.split()) == _NOTE_COPY
    url4 = note.one("a")
    assert url4.text() == "url4"
    assert url4.attrs.get("href") == _URL4_DOCS
    _assert_new_tab(url4)


def test_board_summary_counts_submissions() -> None:
    value = _page("benchmark.html").one(id="summary-specs")
    assert value.parent is not None
    label = value.parent.one("span", "k")

    assert label.text() == "Submissions shown"


def test_board_chart_key_names_all_submissions() -> None:
    doc = _page("benchmark.html")
    swatch = doc.one("span", "pareto-chart-key__dominated")
    assert swatch.parent is not None

    assert swatch.parent.text() == "all submissions"


def test_board_legend_sits_between_the_chart_and_the_table() -> None:
    doc = _page("benchmark.html")
    chart = doc.one(id="pareto-chart-section")
    legend = doc.one(id="leaderboard-legend")
    table = doc.one(id="leaderboard-wrap")

    assert chart.order < legend.order < table.order


# ---- submission history page ---------------------------------------------------------------


def test_history_page_says_submission_in_its_visible_copy() -> None:
    doc = _page("spec.html")
    description = [m for m in doc.find("meta") if m.attrs.get("name") == "description"]

    assert doc.one("title").text() == "screamingface — submission history"
    assert len(description) == 1
    assert description[0].attrs.get("content") == (
        "Run history for a screamingface benchmark submission, with scores and a local rerun link."
    )
    assert doc.one("nav", "crumbs").one("a", "here").text() == "submission"
    assert doc.one("header", "masthead").one("div", "eyebrow").text() == "Submission history"
    assert doc.one("div", "stats").attrs.get("aria-label") == "Submission summary"


# ---- review round 1: per-row items are runs; no em dash in visible prose -------------------


def test_history_page_calls_each_row_a_run() -> None:
    doc = _page("spec.html")
    count = doc.one(id="submission-count")
    assert count.parent is not None

    assert count.parent.one("span", "k").text() == "Runs"
    assert doc.one("table").attrs.get("aria-label") == "Run history"


def test_history_note_points_to_the_client_not_the_desktop_app() -> None:
    note = _page("spec.html").one("div", "note")
    kicker = note.one("span", "kicker")
    body = " ".join(
        (child if isinstance(child, str) else child.text())
        for child in note.children
        if child is not kicker
    )

    assert " ".join(body.split()) == (
        "History is newest-first. The Copy button copies the newest run's url4 expression. "
        "Run it with the screamingface client to check the latest result before trusting it."
    )


def test_about_how_a_result_recipe_sentences() -> None:
    block = _page("about.html").one("section", **{"data-section": "how-a-result"})
    paragraphs = [p.text() for p in block.find("p")]

    assert paragraphs[0] == (
        "Every fusion entry comes with its code, in a single url4 line that contains all the "
        "details of the run. Each call in the recipe is pinned to an exact model version, prompt, "
        "and seed."
    )
    assert paragraphs[1] == (
        "A result appears only after it can be independently rerun on the hosted engine and "
        "registered on the shared cache. Replaying a published row costs nothing, and starting "
        "from someone else's recipe means you pay only for what you change."
    )


def test_about_contribute_sentence_has_no_dash() -> None:
    block = _page("about.html").one("section", **{"data-section": "contribute"})
    paragraphs = [p.text() for p in block.find("p")]

    assert paragraphs[0] == (
        "Anyone can compose a fusion using the Client, compile it to a url4 recipe, score it "
        "against a benchmark of your choice, and publish it on its corresponding leaderboard. "
        "Code and recipes are open under Apache-2.0."
    )


def test_board_legend_frontier_item_uses_a_colon() -> None:
    item = _page("benchmark.html").one(id="legend-pareto")

    assert item.text() == (
        "on the Pareto frontier: no submission has an equal-or-higher score at an "
        "equal-or-lower cost, with one strict improvement"
    )

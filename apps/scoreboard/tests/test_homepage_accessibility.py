"""Structural contracts for navigation and early theme selection."""

from html.parser import HTMLParser
from pathlib import Path

import pytest

PORTAL = Path(__file__).resolve().parents[1] / "portal"


class Elements(HTMLParser):
    def __init__(self, filename: str) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.feed((PORTAL / filename).read_text())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))


def test_homepage_landmarks_and_skip_link() -> None:
    elements = Elements("index.html").elements
    mains = [attrs for tag, attrs in elements if tag == "main"]
    assert len(mains) == 1
    assert mains[0]["id"] == "main-content"
    assert mains[0]["tabindex"] == "-1"
    assert len([tag for tag, _ in elements if tag == "footer"]) == 1
    links = [attrs for tag, attrs in elements if tag == "a"]
    assert links[0]["href"] == "#main-content"


def test_catalog_announcement_controls() -> None:
    elements = Elements("index.html").elements
    by_id = {attrs["id"]: (tag, attrs) for tag, attrs in elements if "id" in attrs}
    tag, more = by_id["benchmark-more"]
    assert tag == "button"
    assert more["aria-controls"] == "benchmark-cards"
    assert more["aria-controls"] in by_id
    _, count = by_id["benchmark-count"]
    assert count["role"] == "status"
    assert count["aria-live"] == "polite"
    assert count["aria-atomic"] == "true"


@pytest.mark.parametrize("page", ["index", "benchmark", "spec", "about", "data"])
def test_theme_initializes_before_styles_and_content(page: str) -> None:
    elements = Elements(f"{page}.html").elements
    scripts = [(i, attrs) for i, (tag, attrs) in enumerate(elements) if tag == "script"]
    init = [(i, attrs) for i, attrs in scripts if attrs.get("src") == "theme-init.js"]
    assert len(init) == 1
    index, attrs = init[0]
    assert "defer" not in attrs
    assert "async" not in attrs
    assert index < next(i for i, (tag, _) in enumerate(elements) if tag == "body")
    assert index < next(
        i
        for i, (tag, attrs) in enumerate(elements)
        if tag == "link" and attrs.get("rel") == "stylesheet"
    )

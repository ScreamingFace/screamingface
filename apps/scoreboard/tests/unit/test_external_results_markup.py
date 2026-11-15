"""Owner-approved shared table; inspect HTML structure without a DOM dependency."""

from html.parser import HTMLParser
from pathlib import Path


class PageElements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))


def test_external_results_use_the_existing_table_and_load_before_the_page() -> None:
    page = PageElements()
    page.feed((Path(__file__).resolve().parents[2] / "portal/benchmark.html").read_text())
    tables = [attrs for tag, attrs in page.elements if tag == "table"]
    assert tables == [{"aria-label": "Leaderboard"}]
    ids = [attrs.get("id") for _, attrs in page.elements]
    assert "external-results" not in ids
    assert "external-results-body" not in ids
    scripts = [attrs.get("src") for tag, attrs in page.elements if tag == "script"]
    assert scripts.count("external-results.js") == 1
    assert scripts.index("main.js") < scripts.index("external-results.js")
    assert scripts.index("external-results.js") < scripts.index("benchmark.js")
    table_regions = [attrs for _, attrs in page.elements if attrs.get("id") == "leaderboard-wrap"]
    assert len(table_regions) == 1
    assert table_regions[0]["tabindex"] == "0"
    assert table_regions[0]["role"] == "region"
    assert table_regions[0]["aria-label"] == "Leaderboard, scrollable"

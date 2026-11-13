"""What the static portal pages tell a search engine about themselves.

FEATURE: search metadata. The home page is the landing for broad searches, so its head has to
say what the site is; pages that show nothing without query parameters stay out of the index.

WHY structure and not wording: the home title is brand copy that changes on someone else's
schedule. These tests pin that the head names a leaderboard for fusions and that the tags agree
with each other, not the sentence.
"""

from __future__ import annotations

from collections.abc import Generator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scoreboard.config import Settings
from scoreboard.main import create_app

PUBLIC_ORIGIN = "https://leaderboard.screamingface.ai"


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.canonicals: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name") or ""
            self.meta[key] = attributes.get("content", "")
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonicals.append(attributes.get("href", ""))
        self._in_title = tag == "title"

    def handle_endtag(self, tag: str) -> None:
        self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient]:
    settings = Settings(database_url=f"sqlite://{tmp_path / 'pages.sqlite3'}", cors_origins=[])
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _head(client: TestClient, path: str) -> _Head:
    response = client.get(path)
    assert response.status_code == 200, path
    parser = _Head()
    parser.feed(response.text)
    return parser


def test_home_head_names_a_leaderboard_for_fusions(client: TestClient) -> None:
    head = _head(client, "/")

    for text in (head.title, head.meta["description"]):
        assert "leaderboard" in text.lower(), text
        assert "fusion" in text.lower(), text
    assert "ScreamingFace" in head.title
    # A results page cuts a title at roughly 60 to 70 characters and a description near 160.
    assert len(head.title) <= 70
    assert 70 <= len(head.meta["description"]) <= 200


@pytest.mark.parametrize("path", ["/", "/about.html"])
def test_link_preview_text_matches_the_title_and_description(client: TestClient, path: str) -> None:
    head = _head(client, path)

    assert head.meta["og:title"] == head.title == head.meta["twitter:title"]
    assert head.meta["og:description"] == head.meta["description"]
    assert head.meta["twitter:description"] == head.meta["description"]


@pytest.mark.parametrize(
    ("path", "address"),
    [
        ("/", f"{PUBLIC_ORIGIN}/"),
        ("/index.html", f"{PUBLIC_ORIGIN}/"),
        ("/about.html", f"{PUBLIC_ORIGIN}/about.html"),
    ],
)
def test_fixed_pages_declare_one_canonical_equal_to_og_url(
    client: TestClient, path: str, address: str
) -> None:
    # INVARIANT: / and /index.html are one page with one address.
    head = _head(client, path)

    assert head.canonicals == [address]
    assert head.meta["og:url"] == address


@pytest.mark.parametrize("path", ["/spec.html", "/data.html"])
def test_parameter_pages_stay_out_of_the_index(client: TestClient, path: str) -> None:
    # WHY: each shows content only with its query parameters, which the static file cannot
    # name, so the document a crawler receives is empty. `follow` keeps its links crawlable.
    head = _head(client, path)

    assert head.meta["robots"] == "noindex,follow"
    assert head.canonicals == []


@pytest.mark.parametrize("path", ["/", "/about.html", "/benchmark.html"])
def test_indexable_pages_carry_no_robots_restriction(client: TestClient, path: str) -> None:
    assert "robots" not in _head(client, path).meta

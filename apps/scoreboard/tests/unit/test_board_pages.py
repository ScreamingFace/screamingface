"""Each public leaderboard has its own address and its own head, served without JavaScript.

FEATURE: board pages — `/benchmarks/<id>/` is the one indexable address of a leaderboard.
`benchmark.html?id=<id>` is the same bytes for every board, so a crawler or a link-preview
fetcher that does not run scripts cannot tell boards apart; these tests pin what the server
itself says about a board.
"""

from __future__ import annotations

import re
from collections.abc import Generator
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score

PUBLIC_ORIGIN = "https://leaderboard.screamingface.ai"
PORTAL = Path(__file__).resolve().parents[2] / "portal"
HOSTILE = '<script>alert("x")</script>'


class _Head(HTMLParser):
    """The parts of a page a crawler reads: title, meta tags, canonical, the h1 and the lead."""

    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.text: dict[str, str] = {"title": "", "benchmark-name": "", "benchmark-desc": ""}
        self.urls: list[str] = []
        self._open: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        self.urls += [attributes[key] for key in ("href", "src") if key in attributes]
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name") or ""
            self.meta[key] = attributes.get("content", "")
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonical = attributes.get("href")
        if tag == "title":
            self._open = "title"
        if attributes.get("id") in self.text:
            self._open = attributes["id"]

    def handle_endtag(self, tag: str) -> None:
        self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self.text[self._open] += data


def _head(markup: str) -> _Head:
    parser = _Head()
    parser.feed(markup)
    return parser


async def _seed() -> None:
    boards = [
        ("draco-3pass", "DRACO 3-Pass", "Research reports, three judge passes", "public"),
        ("empty-board", "Empty Board", "Nothing submitted yet", "public"),
        ("challenge", "Secret Challenge", "Hidden focus", "private"),
        ("hostile", HOSTILE, HOSTILE, "public"),
        ("no-focus", "No Focus", None, "public"),
        ("long-name", "A" * 70, "Long name", "public"),
    ]
    for board_id, name, focus, visibility in boards:
        await Benchmark.create(
            id=board_id,
            display_name=name,
            focus=focus,
            description=f"About {name}.",
            visibility=visibility,
        )
    for board_id in ("draco-3pass", "challenge", "hostile", "no-focus", "long-name"):
        await Score.create(
            benchmark_id=board_id,
            spec_id="entry",
            score=0.5,
            total_questions=10,
            ran_with_providers=[],
            url4_expression="url4://test",
            verified_by_screamingface=True,
        )


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient]:
    settings = Settings(database_url=f"sqlite://{tmp_path / 'boards.sqlite3'}", cors_origins=[])
    with TestClient(create_app(settings), follow_redirects=False) as test_client:
        assert test_client.portal is not None
        test_client.portal.call(Tortoise.generate_schemas)
        test_client.portal.call(_seed)
        yield test_client


def test_scored_board_names_itself_in_the_head_and_body(client: TestClient) -> None:
    response = client.get("/benchmarks/draco-3pass/")
    page = _head(response.text)
    url = f"{PUBLIC_ORIGIN}/benchmarks/draco-3pass/"

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert page.text["title"] == "DRACO 3-Pass leaderboard: models & fusions | ScreamingFace"
    assert page.meta["description"].startswith(
        "DRACO 3-Pass leaderboard: Research reports, three judge passes. "
    )
    assert "fusions" in page.meta["description"]
    assert page.canonical == url
    assert page.meta["og:url"] == url
    assert page.meta["og:title"] == page.text["title"] == page.meta["twitter:title"]
    assert page.meta["og:description"] == page.meta["description"]
    assert page.meta["twitter:description"] == page.meta["description"]
    assert page.text["benchmark-name"] == "DRACO 3-Pass"
    assert page.text["benchmark-desc"] == "About DRACO 3-Pass."
    assert "robots" not in page.meta


def test_boards_do_not_share_a_title_or_description(client: TestClient) -> None:
    # INVARIANT: the defect this unit removes is that every board was one document.
    first = _head(client.get("/benchmarks/draco-3pass/").text)
    second = _head(client.get("/benchmarks/no-focus/").text)

    assert first.text["title"] != second.text["title"]
    assert first.meta["description"] != second.meta["description"]
    assert first.canonical != second.canonical


def test_board_without_a_focus_still_reads_as_a_sentence(client: TestClient) -> None:
    page = _head(client.get("/benchmarks/no-focus/").text)

    assert page.meta["description"].startswith("No Focus leaderboard. An open leaderboard")
    assert "None" not in page.meta["description"]
    assert page.text["benchmark-desc"].strip() == "About No Focus."


def test_long_board_name_drops_the_tagline_to_keep_the_title_short(client: TestClient) -> None:
    page = _head(client.get("/benchmarks/long-name/").text)

    assert page.text["title"] == f"{'A' * 70} leaderboard | ScreamingFace"


def test_unscored_board_is_served_but_kept_out_of_the_index(client: TestClient) -> None:
    response = client.get("/benchmarks/empty-board/")
    page = _head(response.text)

    assert response.status_code == 200
    assert page.meta["robots"] == "noindex,follow"
    assert page.text["benchmark-name"] == "Empty Board"


def test_private_board_page_loads_with_no_board_field_and_no_index(client: TestClient) -> None:
    # INVARIANT: a private board is publicly listed and its page loads for participants, but the
    # server writes nothing about it into HTML. Its scored state must not be observable either:
    # this board has a score and reads exactly like one that has none.
    response = client.get("/benchmarks/challenge/")
    page = _head(response.text)

    assert response.status_code == 200
    assert page.meta["robots"] == "noindex,follow"
    assert page.text["title"] == "screamingface · leaderboard"
    assert "Secret Challenge" not in response.text
    assert "Hidden focus" not in response.text
    assert "og:url" not in page.meta
    assert page.canonical is None


def test_unknown_board_is_a_real_404(client: TestClient) -> None:
    assert client.get("/benchmarks/does-not-exist/").status_code == 404
    assert client.get("/benchmarks/does-not-exist").status_code in (301, 404)


def test_board_fields_are_escaped(client: TestClient) -> None:
    # WHY: display_name, focus and description are community-submitted. The portal writes them
    # with textContent only; server-rendered HTML has to hold the same line.
    response = client.get("/benchmarks/hostile/")

    assert response.status_code == 200
    assert HOSTILE not in response.text
    assert "&lt;script&gt;" in response.text
    assert _head(response.text).text["benchmark-name"] == HOSTILE


@pytest.mark.parametrize("board", ["draco-3pass", "empty-board", "challenge"])
def test_board_page_has_no_relative_url(client: TestClient, board: str) -> None:
    # WHY: under /benchmarks/<id>/ a relative "main.js" resolves to /benchmarks/<id>/main.js.
    # Asserted for every href and src so a script tag added to the shell later cannot break
    # board pages unnoticed.
    urls = _head(client.get(f"/benchmarks/{board}/").text).urls

    assert urls
    for url in urls:
        assert url.startswith(("/", "#", "https://", "http://", "data:")), url


def test_board_page_assets_resolve(client: TestClient) -> None:
    urls = _head(client.get("/benchmarks/draco-3pass/").text).urls
    local = [url for url in urls if url.startswith("/") and url != "/"]

    assert "/main.js" in local and "/benchmark.js" in local and "/portal.css" in local
    for url in local:
        assert client.get(url).status_code == 200, url


def test_board_page_is_not_cached(client: TestClient) -> None:
    # INVARIANT: a score or visibility change shows on the next request, as on the catalog.
    for board in ("draco-3pass", "challenge"):
        assert client.get(f"/benchmarks/{board}/").headers["cache-control"] == "no-store"


def test_board_address_without_the_slash_redirects_permanently(client: TestClient) -> None:
    response = client.get("/benchmarks/draco-3pass")

    assert response.status_code == 301
    assert response.headers["location"] == "/benchmarks/draco-3pass/"


def test_old_board_address_redirects_once_and_keeps_other_parameters(client: TestClient) -> None:
    response = client.get("/benchmark.html?id=draco-3pass&utm_source=news&utm_campaign=q4")

    assert response.status_code == 301
    assert response.headers["location"] == (
        "/benchmarks/draco-3pass/?utm_source=news&utm_campaign=q4"
    )
    assert client.get(response.headers["location"]).status_code == 200


def test_old_board_address_encodes_the_id_into_one_path_segment(client: TestClient) -> None:
    # INVARIANT: the id is data. It never becomes a second path segment, a scheme or a host.
    response = client.get("/benchmark.html", params={"id": "//evil.example/a b?x#y"})

    assert response.status_code == 301
    assert response.headers["location"] == "/benchmarks/%2F%2Fevil.example%2Fa%20b%3Fx%23y/"


def test_bare_board_file_is_still_the_static_file(client: TestClient) -> None:
    for path in ("/benchmark.html", "/benchmark.html?id=", "/benchmark.html?utm_source=news"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content == (PORTAL / "benchmark.html").read_bytes(), path


def test_each_board_has_its_own_og_url(client: TestClient) -> None:
    # WHY: the static parameter pages deliberately carry no og:url, so that one fixed value
    # cannot collapse every board onto a single preview. The clean address gives each board its
    # own identity, which is what that rule protects.
    urls = {
        _head(client.get(f"/benchmarks/{board}/").text).meta["og:url"]
        for board in ("draco-3pass", "no-focus", "empty-board")
    }

    assert len(urls) == 3


def test_sitemap_lists_home_about_and_scored_public_boards(client: TestClient) -> None:
    response = client.get("/sitemap.xml")
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    nodes = ElementTree.fromstring(response.text).iter(f"{namespace}loc")
    locations = [node.text or "" for node in nodes]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert f"{PUBLIC_ORIGIN}/" in locations
    assert f"{PUBLIC_ORIGIN}/about.html" in locations
    assert f"{PUBLIC_ORIGIN}/benchmarks/draco-3pass/" in locations
    assert f"{PUBLIC_ORIGIN}/benchmarks/hostile/" in locations
    assert not [url for url in locations if "empty-board" in url or "challenge" in url]
    assert len(locations) == len(set(locations)) == 6


def test_robots_allows_crawling_and_names_the_sitemap(client: TestClient) -> None:
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert re.search(r"^User-agent: \*$", response.text, re.MULTILINE)
    assert re.search(r"^Allow: /$", response.text, re.MULTILINE)
    assert f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml" in response.text.splitlines()
    assert "Disallow" not in response.text


def test_api_routes_under_v1_are_untouched(client: TestClient) -> None:
    assert client.get("/v1/benchmarks/summary").status_code == 200
    assert client.get("/v1/leaderboard/draco-3pass").status_code == 200


def test_store_failure_is_a_503_not_a_page_or_a_404(tmp_path: Path) -> None:
    # WHY: a crawler that meets a 200 shell or a 404 during an outage drops the board; a 503
    # tells it to come back. No schema is created here, so every query fails.
    settings = Settings(database_url=f"sqlite://{tmp_path / 'down.sqlite3'}", cors_origins=[])
    with TestClient(create_app(settings), follow_redirects=False) as down:
        assert down.get("/benchmarks/draco-3pass/").status_code == 503
        assert down.get("/sitemap.xml").status_code == 503
        assert down.get("/benchmark.html?id=draco-3pass").status_code == 301
        assert down.get("/benchmark.html").status_code == 200
        assert down.get("/robots.txt").status_code == 200

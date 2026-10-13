"""The FRAMES snapshot builder: one frozen copy of every gold Wikipedia article (OME-1481).

FEATURE: FRAMES, articles-given setting. The builder runs once, by hand, and its output is
published as a pinned dataset; these tests are the only check on what goes into it, so each
names the reason a rule exists.
"""

import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "frames_snapshot.py"
_DATA = Path(__file__).resolve().parent / "data" / "frames_snapshot"
_EN = "en.wikipedia.org"


def _builder() -> ModuleType:
    """Load the builder script as a module; it lives in scripts/, outside the package."""
    spec = importlib.util.spec_from_file_location("frames_snapshot", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # WHY registered first: dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fs = _builder()


def _text(fixture: str) -> str:
    """The builder's text for one real article revision."""
    return fs.article_text((_DATA / fixture).read_text(encoding="utf-8"))


# --- HTML → text, on real revisions -------------------------------------------------------


def test_infobox_facts_survive_as_label_value_rows() -> None:
    # WHY: FRAMES chains facts like "the first lady after X"; on this page the predecessor and
    # successor live ONLY in the infobox, so a plain-text extract that drops it makes the
    # question unanswerable from the articles given.
    text: str = _text("harriet_lane_1234251973.html")
    assert "| Preceded by | Jane Pierce |" in text
    assert "| Succeeded by | Mary Todd Lincoln |" in text


def test_data_table_rows_survive_as_pipe_rows() -> None:
    # WHY: "tabular" is one of the paper's five reasoning types; the row keeps its cells in
    # column order, and the citation in the Ref column is dropped, leaving the cell empty.
    text: str = _text("list_of_mayors_of_utica_1220067810.html")
    assert "| Name | Party | Term | Ref |" in text
    assert "| Joseph Kirkland | Federalist | 1832 | |" in text


def test_body_prose_and_headings_are_kept() -> None:
    text: str = _text("harriet_lane_1234251973.html")
    assert "Harriet Rebecca Lane Johnston (May 9, 1830 – July 3, 1903) acted as first lady" in text
    assert "\n## Early life\n" in text
    assert "\n### Namesake ships\n" in text


def test_page_furniture_without_facts_is_dropped() -> None:
    # WHY: references, navigation boxes, hatnotes, images and stylesheets add tokens and no
    # facts; every token cut keeps more Cases inside a Candidate's context window.
    text: str = _text("harriet_lane_1234251973.html")
    for absent in (
        "For ships named",  # the hatnote
        "Retrieved",  # citation bodies
        "[1]",  # citation markers in the prose
        ".mw-parser-output",  # inline stylesheets
        "Template:James Buchanan",  # the navbox
        "Lane-Johnston Building, St. Albans School",  # an image caption
    ):
        assert absent not in text, absent


def test_reference_sections_are_dropped_up_to_the_next_heading_of_their_level() -> None:
    text: str = _text("harriet_lane_1234251973.html")
    for heading in ("## Footnotes", "## References", "## Further reading", "## External links"):
        assert heading not in text
    # The last kept section is the one before the reference sections start.
    assert text.rstrip().splitlines()[-1] != ""
    assert text.index("### Namesake ships") > text.index("## Legacy")


def test_text_is_byte_stable_for_the_same_html() -> None:
    # INVARIANT: the same revision always yields the same bytes, or a re-run of the builder
    # would publish a snapshot with a different sha256 and nobody could say why.
    html: str = (_DATA / "list_of_mayors_of_utica_1220067810.html").read_text(encoding="utf-8")
    assert fs.article_text(html) == fs.article_text(html)


# --- link cleanup, one case per spelling FRAMES actually contains ---------------------------


@pytest.mark.parametrize(
    ("link", "wiki", "title"),
    [
        ("https://en.wikipedia.org/wiki/Harriet_Lane", _EN, "Harriet Lane"),
        ("https://en.m.wikipedia.org/wiki/Kodansha", _EN, "Kodansha"),
        ("en.wikipedia.org/wiki/Grazia_Deledda", _EN, "Grazia Deledda"),
        (
            "https://en.wikipedia.org/wiki/Home_Alone_2:_Lost_in_New_York#Cast",
            _EN,
            "Home Alone 2: Lost in New York",
        ),
        ("https://en.wikipedia.org/wiki/Spyro_2:_Ripto%27s_Rage!", _EN, "Spyro 2: Ripto's Rage!"),
        ("https://en.wikipedia.org/w/index.php?title=Bronco&redirect=no", _EN, "Bronco"),
        (
            "https://simple.wikipedia.org/wiki/Video_assistant_referee",
            "simple.wikipedia.org",
            "Video assistant referee",
        ),
        ("https://w.wiki/ASFv", _EN, "Harry C. Bradley (actor)"),
        # Question 764 percent-encodes its apostrophe twice: %2527 -> %27 -> '.
        (
            "https://en.wikipedia.org/wiki/2021_French_Open_%E2%80%93_Men%2527s_singles",
            _EN,
            "2021 French Open – Men's singles",
        ),
        # Question 644 has a note pasted into the URL after the title.
        ("https://en.wikipedia.org/wiki/Pok%C3%A9mon (NOT REQUIRED, BUT HELPFUL)", _EN, "Pokémon"),
        (
            "https://en.wikipedia.org/w/index.php?search=Polytrichum+piliferum"
            "&title=Special:Search&profile=advanced&fulltext=1&ns0=1",
            _EN,
            "Polytrichum piliferum",
        ),
    ],
)
def test_every_link_spelling_resolves_to_one_page(link: str, wiki: str, title: str) -> None:
    assert fs.page_ref(link) == fs.PageRef(wiki=wiki, title=title)


@pytest.mark.parametrize(
    "link",
    [
        "https://de.wikipedia.org/wiki/Berlin",  # another language: not FRAMES' source
        "https://example.com/wiki/Harriet_Lane",
        "https://en.wikipedia.org/w/index.php?search=Something+else",  # a search we never read
    ],
)
def test_a_link_with_no_known_page_is_refused_by_name(link: str) -> None:
    with pytest.raises(fs.SnapshotError, match="link"):
        fs.page_ref(link)


def test_glued_links_split_and_padding_is_stripped() -> None:
    # WHY: one FRAMES row stores three URLs in one list item, joined by ", " with a trailing
    # comma; another pads a URL with spaces. Without the split, three articles go missing.
    raw: list[str] = [
        "https://en.wikipedia.org/wiki/Calton,_Glasgow  ",
        "https://en.wikipedia.org/wiki/American_Family_Field, "
        "https://en.wikipedia.org/wiki/LoanDepot_Park, "
        "https://en.wikipedia.org/wiki/Globe_Life_Field, ",
    ]
    assert fs.split_links(raw) == [
        "https://en.wikipedia.org/wiki/Calton,_Glasgow",
        "https://en.wikipedia.org/wiki/American_Family_Field",
        "https://en.wikipedia.org/wiki/LoanDepot_Park",
        "https://en.wikipedia.org/wiki/Globe_Life_Field",
    ]


# --- revision at the cut-off --------------------------------------------------------------


class _FakeWiki:
    """Stand-in for the MediaWiki API: answers the queries the builder makes.

    It simulates page histories (by title and by page id) and the move log; it does NOT
    simulate rate limits, lag or network errors, which the real client's retry loop handles.
    It answers no "where does this title redirect today" query: the builder must never ask.
    """

    def __init__(
        self,
        history: dict[str, dict[str, Any]],
        moves: dict[str, list[tuple[str, int]]] | None = None,
        html: dict[int, str] | None = None,
    ) -> None:
        self.history = history
        self.moves = moves or {}
        self.html = html or {}

    def get(self, wiki: str, params: dict[str, str]) -> dict[str, Any]:
        """Answer a parse call or a query."""
        if params["action"] == "parse":
            return {"parse": {"text": self.html[int(params["oldid"])]}}
        return {"query": self._query(params)}

    def _query(self, params: dict[str, str]) -> dict[str, Any]:
        """Answer a move-log query or a revisions query."""
        if params.get("list") == "logevents":
            after: list[tuple[str, int]] = sorted(
                move
                for move in self.moves.get(params["letitle"], [])
                if move[0] >= params["lestart"]
            )
            limit: int = int(params["lelimit"])
            return {"logevents": [{"timestamp": at, "logpage": page} for at, page in after[:limit]]}
        return {"pages": [self._page(params)]}

    def _page(self, params: dict[str, str]) -> dict[str, Any]:
        """One page by id or by title, or a missing page."""
        if "pageids" in params:
            by_id: dict[int, dict[str, Any]] = {p["pageid"]: p for p in self.history.values()}
            return by_id.get(int(params["pageids"]), {"missing": True})
        return self.history.get(params["titles"], {"title": params["titles"], "missing": True})


def _page(title: str, page_id: int, revid: int, timestamp: str, content: str) -> dict[str, Any]:
    """One page as the revisions query returns it: its latest revision at the cut-off."""
    revision: dict[str, Any] = {
        "revid": revid,
        "timestamp": timestamp,
        "slots": {"main": {"content": content}},
    }
    return {"title": title, "pageid": page_id, "revisions": [revision]}


def test_the_revision_asked_for_is_the_last_one_before_the_cut_off() -> None:
    wiki = _FakeWiki(
        {
            "Harriet Lane": _page(
                "Harriet Lane", 416378, 1234251973, "2024-07-13T11:11:17Z", "'''Harriet'''"
            )
        }
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Harriet Lane"))
    assert revision == fs.Revision(_EN, "Harriet Lane", 416378, 1234251973, "2024-07-13T11:11:17Z")


def test_a_redirect_at_the_cut_off_is_followed_to_its_article() -> None:
    # WHY: FRAMES links "Bronco", which was already a redirect in 2024; its text is one line.
    wiki = _FakeWiki(
        {
            "Bronco": _page(
                "Bronco",
                1,
                1075282700,
                "2022-03-04T22:04:24Z",
                "#REDIRECT [[Bucking horse]]  {{R from Merge}}",
            ),
            "Bucking horse": _page("Bucking horse", 2, 1240000000, "2024-08-01T00:00:00Z", "text"),
        }
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Bronco"))
    assert (revision.title, revision.revision_id) == ("Bucking horse", 1240000000)


def test_a_page_renamed_after_the_cut_off_is_found_by_its_page_id() -> None:
    # WHY: a rename moves the page and its whole history to the new title and leaves a fresh
    # redirect at the old one, so the old title has no revision before the cut-off. The move
    # log names the page id, which no rename changes. 41 FRAMES titles were renamed this way.
    wiki = _FakeWiki(
        {"Daikin Park": _page("Daikin Park", 3, 1230000000, "2024-06-01T00:00:00Z", "text")},
        moves={"Minute Maid Park": [("2024-11-18T00:00:00Z", 3)]},
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Minute Maid Park"))
    assert (revision.page_id, revision.revision_id) == (3, 1230000000)


def test_a_renamed_page_is_never_found_through_todays_redirect() -> None:
    # WHY: a redirect can be re-pointed after a rename. "The Beatles discography" was renamed
    # "The Beatles albums discography" in October 2024, and its leftover redirect now lands on
    # "The Beatles"; following it would serve question 665 the band's article without a word.
    # Both pages exist here, so landing on the wrong one would pass silently.
    wiki = _FakeWiki(
        {
            "The Beatles albums discography": _page(
                "The Beatles albums discography", 7, 1244000000, "2024-09-10T00:00:00Z", "albums"
            ),
            "The Beatles": _page("The Beatles", 8, 1245000000, "2024-09-12T00:00:00Z", "band"),
        },
        moves={"The Beatles discography": [("2024-10-05T14:58:12Z", 7)]},
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "The Beatles discography"))
    assert (revision.title, revision.page_id) == ("The Beatles albums discography", 7)


def test_only_the_first_rename_after_the_cut_off_counts() -> None:
    # WHY: a title can be renamed, reused and renamed again. A 2006 rename moved a different
    # page away; only the page renamed away after the cut-off held this title at the cut-off.
    wiki = _FakeWiki(
        {
            "List of current United States representatives": _page(
                "List of current United States representatives",
                5,
                1240000001,
                "2024-09-01T00:00:00Z",
                "current",
            ),
            "List of members of the 109th United States House of Representatives": _page(
                "List of members of the 109th United States House of Representatives",
                4,
                1200000000,
                "2024-01-01T00:00:00Z",
                "109th",
            ),
        },
        moves={
            "List of current members of the United States House of Representatives": [
                ("2006-01-01T00:00:00Z", 4),
                ("2025-02-05T00:00:00Z", 5),
            ]
        },
    )
    old_title: str = "List of current members of the United States House of Representatives"
    assert fs.resolve_revision(wiki, fs.PageRef(_EN, old_title)).page_id == 5


def test_a_title_taken_over_by_a_redirect_after_the_cut_off_serves_the_page_that_left() -> None:
    # WHY: after the cut-off "Edward II of England" was swapped with its short-name redirect:
    # the article moved to "Edward II" and the redirect page, with its own history, took the
    # old title. Asking by title returns that redirect's 2024 revision, which points at the
    # title itself. The first page moved away from the title held it at the cut-off.
    wiki = _FakeWiki(
        {
            "Edward II of England": _page(
                "Edward II of England",
                1004892,
                1207264863,
                "2024-02-14T10:53:05Z",
                "#REDIRECT [[Edward II of England]]",
            ),
            "Edward II": _page("Edward II", 9, 1240000002, "2024-09-01T00:00:00Z", "king"),
        },
        moves={"Edward II of England": [("2025-03-01T00:00:00Z", 9)]},
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Edward II of England"))
    assert (revision.page_id, revision.revision_id) == (9, 1240000002)


def test_two_articles_swapped_after_the_cut_off_never_serve_the_wrong_one() -> None:
    # INVARIANT: the article served is the one that held the title AT the cut-off. When two
    # articles swap titles, asking by title returns a real article with real 2024 history,
    # just the wrong one, and nothing downstream could notice.
    wiki = _FakeWiki(
        {
            "Mercury": _page("Mercury", 2, 1230000002, "2024-05-01T00:00:00Z", "the element"),
            "Mercury (planet)": _page(
                "Mercury (planet)", 1, 1230000001, "2024-05-01T00:00:00Z", "the planet"
            ),
        },
        moves={"Mercury": [("2025-01-01T00:00:00Z", 1)]},
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Mercury"))
    assert (revision.page_id, revision.revision_id) == (1, 1230000001)


def test_a_page_created_after_the_cut_off_never_counts_as_the_one_that_held_the_title() -> None:
    # WHY: in August 2026 a vandal swapped "Dolly Parton" with a junk page and an admin moved
    # the junk page away again; that cleanup is the first visible move after the cut-off (the
    # vandal's own moves are hidden from the log). The junk page has no revision before the
    # cut-off, so it cannot have held the title then; the article back at the title did.
    wiki = _FakeWiki(
        {"Dolly Parton": _page("Dolly Parton", 1, 1245000000, "2024-09-15T00:00:00Z", "singer")},
        moves={"Dolly Parton": [("2026-08-27T18:59:05Z", 84079417)]},
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Dolly Parton"))
    assert (revision.page_id, revision.revision_id) == (1, 1245000000)


def test_a_title_nobody_moved_costs_one_move_log_call() -> None:
    # WHY: almost every one of the ~2,500 gold titles was never moved; asking the log a second
    # time for "more moves" after an empty answer adds ~2,500 calls and ~20 minutes a build.
    fake = _FakeWiki({"Harriet Lane": _page("Harriet Lane", 1, 100, "2024-01-01T00:00:00Z", "a")})
    log_calls: list[dict[str, str]] = []
    answer = fake.get

    def counting_get(wiki: str, params: dict[str, str]) -> dict[str, Any]:
        if params.get("list") == "logevents":
            log_calls.append(params)
        return answer(wiki, params)

    fake.get = counting_get
    fs.resolve_revision(fake, fs.PageRef(_EN, "Harriet Lane"))
    assert len(log_calls) == 1


def test_a_page_with_no_revision_before_the_cut_off_is_refused_by_name() -> None:
    with pytest.raises(fs.SnapshotError, match="Created later"):
        fs.resolve_revision(_FakeWiki({}), fs.PageRef(_EN, "Created later"))


def test_a_revision_on_or_after_the_cut_off_is_refused() -> None:
    # INVARIANT: no snapshot article postdates the cut-off, even if the API misbehaves.
    wiki = _FakeWiki({"Late": _page("Late", 4, 1250000000, "2024-09-19T00:00:00Z", "text")})
    with pytest.raises(fs.SnapshotError, match="cut-off"):
        fs.resolve_revision(wiki, fs.PageRef(_EN, "Late"))


# --- the whole build and the files it writes ----------------------------------------------


def _two_question_wiki() -> Any:
    """Three pages, one of them reached by two different link spellings."""
    return _FakeWiki(
        {
            "Alpha": _page("Alpha", 10, 100, "2024-01-01T00:00:00Z", "a"),
            "Beta": _page("Beta", 20, 200, "2024-01-02T00:00:00Z", "b"),
            "Gamma": _page("Gamma", 30, 300, "2024-01-03T00:00:00Z", "c"),
        },
        html={100: "<p>Alpha text.</p>", 200: "<p>Beta text.</p>", 300: "<p>Gamma text.</p>"},
    )


def _two_questions() -> list[Any]:
    return [
        fs.Question(
            0, "Q0?", ["https://en.wikipedia.org/wiki/Beta", "https://en.wikipedia.org/wiki/Alpha"]
        ),
        fs.Question(
            1,
            "Q1?",
            [
                "https://en.m.wikipedia.org/wiki/Alpha#History",
                "https://en.wikipedia.org/wiki/Gamma",
            ],
        ),
    ]


def test_build_dedupes_articles_and_keeps_each_questions_link_order() -> None:
    snapshot = fs.build_snapshot(_two_questions(), _two_question_wiki())
    assert [a["title"] for a in snapshot.articles] == ["Alpha", "Beta", "Gamma"]
    alpha: dict[str, Any] = snapshot.articles[0]
    assert alpha["links"] == [
        "https://en.m.wikipedia.org/wiki/Alpha#History",
        "https://en.wikipedia.org/wiki/Alpha",
    ]
    assert alpha["text"] == "Alpha text."
    assert [q["articles"] for q in snapshot.questions] == [
        ["en.wikipedia.org/200", "en.wikipedia.org/100"],
        ["en.wikipedia.org/100", "en.wikipedia.org/300"],
    ]


def test_build_reports_every_refusal_together_and_returns_nothing() -> None:
    # WHY: a build takes an hour of polite API calls; stopping at the first bad link would
    # cost one hour per bad link. Every refusal is named in one error instead.
    questions = [
        fs.Question(
            0,
            "Q0?",
            ["https://en.wikipedia.org/wiki/Missing_one", "https://en.wikipedia.org/wiki/Alpha"],
        ),
        fs.Question(1, "Q1?", ["https://de.wikipedia.org/wiki/Berlin"]),
    ]
    with pytest.raises(fs.SnapshotError) as refused:
        fs.build_snapshot(questions, _two_question_wiki())
    assert "Missing one" in str(refused.value)
    assert "de.wikipedia.org" in str(refused.value)


def test_written_files_are_byte_identical_on_a_rebuild(tmp_path: Path) -> None:
    # INVARIANT: the published sha256 must be reproducible from the same inputs.
    first: dict[str, str] = fs.write_snapshot(
        fs.build_snapshot(_two_questions(), _two_question_wiki()), tmp_path / "a"
    )
    second: dict[str, str] = fs.write_snapshot(
        fs.build_snapshot(_two_questions(), _two_question_wiki()), tmp_path / "b"
    )
    assert first == second
    articles: bytes = (tmp_path / "a" / "articles.jsonl").read_bytes()
    assert first["articles.jsonl"] == hashlib.sha256(articles).hexdigest()
    rows: list[dict[str, Any]] = [json.loads(line) for line in articles.splitlines()]
    assert set(rows[0]) == {
        "key",
        "wiki",
        "title",
        "page_id",
        "revision_id",
        "revision_timestamp",
        "links",
        "text",
        "years_from_templates",
    }


def test_each_question_row_carries_its_prompt_hash_so_the_loader_can_check_alignment(
    tmp_path: Path,
) -> None:
    # WHY: the Task joins this file to the questions file by row index; the hash lets it
    # refuse a snapshot built from a different questions file instead of pairing wrong rows.
    fs.write_snapshot(fs.build_snapshot(_two_questions(), _two_question_wiki()), tmp_path)
    lines: list[str] = (tmp_path / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    first: dict[str, Any] = json.loads(lines[0])
    assert first["index"] == 0
    assert first["prompt_sha256"] == hashlib.sha256(b"Q0?").hexdigest()


def test_a_known_deleted_page_is_named_on_its_question_and_not_refused() -> None:
    # WHY (decision 9): two gold articles were deleted and only Wikipedia admins can read
    # them. Refusing would block every build forever; dropping them silently would hide it.
    # The question row names what is missing, so the Task can drop or keep the question.
    questions = [
        fs.Question(
            540,
            "Which Mexican player?",
            [
                "https://en.wikipedia.org/wiki/Alpha",
                "https://en.wikipedia.org/wiki/Jack_Vance_(tennis)",
            ],
        )
    ]
    snapshot = fs.build_snapshot(questions, _two_question_wiki())
    row: dict[str, Any] = snapshot.questions[0]
    assert row["articles"] == ["en.wikipedia.org/100"]
    assert row["missing_articles"] == [
        {"wiki": _EN, "title": "Jack Vance (tennis)", "deleted": "2024-11-15"}
    ]
    assert [a["title"] for a in snapshot.articles] == ["Alpha"]


def test_a_missing_page_not_on_the_deleted_list_is_still_refused() -> None:
    # INVARIANT: the deleted list is an exception for two named pages, not a way for a newly
    # deleted article to drop out of the snapshot unnoticed.
    questions = [fs.Question(0, "Q?", ["https://en.wikipedia.org/wiki/Deleted_next_year"])]
    with pytest.raises(fs.SnapshotError, match="Deleted next year"):
        fs.build_snapshot(questions, _two_question_wiki())


def test_years_after_the_cut_off_that_only_templates_wrote_are_flagged() -> None:
    # WHY: Wikipedia draws an old revision with TODAY's templates, so Harriet Lane's 2024
    # revision renders "equivalent to $14,300,000 in 2025". A year after the cut-off that the
    # revision's own source never writes can only have come from a template. 2026 here is in
    # the source (a planned event) and 2023 is before the cut-off, so neither is flagged.
    source: str = "$400,000 ({{Inflation|US|400000|1854}}) A 2026 reunion is planned. In 2023 she"
    html: str = (
        "<p>$400,000 (equivalent to $14,300,000 in 2025) A 2026 reunion is planned. In 2023 she</p>"
    )
    wiki = _FakeWiki(
        {"Harriet Lane": _page("Harriet Lane", 416378, 1234251973, "2024-07-13T11:11:17Z", source)},
        html={1234251973: html},
    )
    questions = [fs.Question(0, "Q?", ["https://en.wikipedia.org/wiki/Harriet_Lane"])]
    assert fs.build_snapshot(questions, wiki).articles[0]["years_from_templates"] == ["2025"]


class _GzipResponse:
    """Stand-in for one HTTP response that arrives gzip-compressed."""

    def __init__(self, body: bytes) -> None:
        self.headers: dict[str, str] = {"Content-Encoding": "gzip"}
        self._body: bytes = gzip.compress(body)

    def read(self) -> bytes:
        """The bytes as they came over the wire, still compressed."""
        return self._body

    def __enter__(self) -> "_GzipResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_the_api_is_asked_for_gzip_and_the_answer_is_unpacked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY: a full build downloads the drawn HTML of ~2,500 articles, about 1 GB uncompressed;
    # gzip cuts that several times over, which matters on a metered link and is what
    # Wikipedia's API etiquette asks for. The cache must still hold plain JSON.
    sent: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> _GzipResponse:
        sent.append(request)
        return _GzipResponse(b'{"ok": true}')

    monkeypatch.setattr(fs.urllib.request, "urlopen", fake_urlopen)
    assert fs._fetch("https://en.wikipedia.org/w/api.php?x=1") == b'{"ok": true}'
    assert sent[0].get_header("Accept-encoding") == "gzip"

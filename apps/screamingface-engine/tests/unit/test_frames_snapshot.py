"""The FRAMES snapshot builder: one frozen copy of every gold Wikipedia article (OME-1481).

FEATURE: FRAMES, articles-given setting. The builder runs once, by hand, and its output is
published as a pinned dataset; these tests are the only check on what goes into it, so each
names the reason a rule exists.
"""

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
    """Stand-in for the MediaWiki API: answers the two queries the builder makes.

    It simulates page histories and today's redirects; it does NOT simulate rate limits,
    lag or network errors, which the real client's retry loop handles.
    """

    def __init__(
        self,
        history: dict[str, dict[str, Any]],
        redirects: dict[str, str] | None = None,
        html: dict[int, str] | None = None,
    ) -> None:
        self.history = history
        self.redirects = redirects or {}
        self.html = html or {}

    def get(self, wiki: str, params: dict[str, str]) -> dict[str, Any]:
        """Answer a revisions query, a redirect query or a parse call."""
        if params["action"] == "parse":
            return {"parse": {"text": self.html[int(params["oldid"])]}}
        title: str = params["titles"]
        if "redirects" in params:
            target: str | None = self.redirects.get(title)
            return {"query": {"redirects": [{"from": title, "to": target}] if target else []}}
        missing: dict[str, Any] = {"title": title, "missing": True}
        return {"query": {"pages": [self.history.get(title, missing)]}}


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


def test_a_page_moved_after_the_cut_off_is_found_through_todays_redirect() -> None:
    # WHY: a move after the cut-off leaves only a new redirect at the old title, with no
    # history before the cut-off; the history moved with the page.
    wiki = _FakeWiki(
        {"New name": _page("New name", 3, 1230000000, "2024-06-01T00:00:00Z", "text")},
        redirects={"Old name": "New name"},
    )
    revision = fs.resolve_revision(wiki, fs.PageRef(_EN, "Old name"))
    assert (revision.title, revision.revision_id) == ("New name", 1230000000)


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

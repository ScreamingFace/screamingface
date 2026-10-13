"""Freeze every gold Wikipedia article FRAMES cites into one snapshot (OME-1481, decisions 6-8).

    uv run python scripts/frames_snapshot.py --out <dir> [--cache-dir <dir>]

FEATURE: FRAMES, articles-given setting. Think of it as photocopying an exam's reading list
once, from one dated edition, so every sitting of the exam hands out the same pages. FRAMES
publishes 824 questions with Wikipedia LINKS, not text; the Task pastes the gold articles into
each prompt, so the text has to come from somewhere fixed.

Stages, in the order they run:

1. Read the questions file at its pinned Hugging Face commit, checking its sha256.
2. Clean every link into one page (``page_ref``): FRAMES spells links many ways (mobile host,
   no scheme, a fragment, two URLs glued into one item, a search URL, a ``w.wiki`` short link,
   a title percent-encoded twice, a note pasted after the title).
3. Find each page's last revision BEFORE the 2024-09-19 cut-off (``resolve_revision``),
   following a redirect that was in place then. Which page held a title at the cut-off is read
   from the move log (pages get renamed and swapped); today's redirects are never followed.
4. Fetch each revision's rendered HTML and turn it into text (``article_text``): body, headings,
   tables and infoboxes kept as pipe rows; references, navigation boxes, hatnotes, images and
   the reference sections dropped.
5. Write ``articles.jsonl`` (one row per revision) and ``questions.jsonl`` (one row per
   question: its articles in link order, and its prompt's sha256), then print their sha256s.

Every refusal (a link with no page, a page with no revision before the cut-off) is collected
and reported together, and nothing is written: an article is never silently dropped. The one
exception is ``_DELETED``: two pages only Wikipedia admins can read, each named on its
question row as missing (decision 9).

Network: only ``huggingface.co`` (stage 1) and the Wikipedia API (stages 3-4), sequentially,
with a User-Agent naming the project. Responses are cached under ``--cache-dir`` so a re-run
after fixing a refusal does not refetch. Nothing here runs at import or at image build.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol

# WHY 2024-09-19: the paper's first arXiv version; it names no Wikipedia snapshot, and this is
# the latest date its authors could have read. Each article is pinned at its last revision
# strictly before it (OME-1481 decision 7).
CUTOFF: str = "2024-09-19T00:00:00Z"
_LAST_SECOND: str = "2024-09-18T23:59:59Z"

QUESTIONS_URL: str = (
    "https://huggingface.co/datasets/google/frames-benchmark/resolve/"
    "58d9fb6330f3ab1316d1eca12e5e8ef23dcc22ef/test.tsv"
)
QUESTIONS_SHA256: str = "4255093c93b595b5b04c7c8dde290b48ec87d72ca0fb0b760d9dd02740d669ff"

USER_AGENT: str = (
    "ScreamingFace-FRAMES-snapshot/1.0 (https://github.com/ScreamingFace/screamingface)"
)
_WIKIS: frozenset[str] = frozenset({"en.wikipedia.org", "simple.wikipedia.org"})
_MOBILE: dict[str, str] = {"en.m.wikipedia.org": "en.wikipedia.org"}

# WHY a table, not code: two FRAMES links name no page in their URL. Each was resolved once by
# hand (the short link by following its redirect, 2026-10-12) and is reviewable here.
_LINK_PAGES: dict[str, tuple[str, str]] = {
    "https://w.wiki/ASFv": ("en.wikipedia.org", "Harry C. Bradley (actor)"),
    "https://en.wikipedia.org/w/index.php?search=Polytrichum+piliferum&title=Special:Search"
    "&profile=advanced&fulltext=1&ns0=1": ("en.wikipedia.org", "Polytrichum piliferum"),
    # Question 644: a note to the question writers pasted into the URL after the title.
    "https://en.wikipedia.org/wiki/Pok%C3%A9mon (NOT REQUIRED, BUT HELPFUL)": (
        "en.wikipedia.org",
        "Pokémon",
    ),
}
# WHY a table (OME-1481 decision 9): these two gold articles were deleted, and a deleted
# revision is readable only by Wikipedia admins. Refusing would block every build; dropping
# them silently would hide it. Each is named on its question row instead, with the date it
# was deleted (from the deletion log, checked 2026-10-13).
_DELETED: dict[tuple[str, str], str] = {
    ("en.wikipedia.org", "Nemanja Marković"): "2024-07-01",
    ("en.wikipedia.org", "Jack Vance (tennis)"): "2024-11-15",
}
_YEAR: re.Pattern[str] = re.compile(r"\b20[2-9]\d\b")
_FIRST_YEAR_AFTER_CUTOFF: int = 2025
_GLUED: re.Pattern[str] = re.compile(r",\s*(?=(?:https?://|en\.))")
_REDIRECT: re.Pattern[str] = re.compile(r"^\s*#REDIRECT\s*\[\[([^\]|#]+)", re.IGNORECASE)
_MAX_REDIRECTS: int = 3
_MAX_ATTEMPTS: int = 5
_RETRY_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})


_DESCRIPTION: str = "Freeze every gold Wikipedia article FRAMES cites into one snapshot."


class SnapshotError(Exception):
    """The snapshot cannot be built faithfully; the message names every reason."""


@dataclass(frozen=True, order=True)
class PageRef:
    """One wiki page as a link names it, before any redirect is followed."""

    wiki: str
    title: str


@dataclass(frozen=True)
class Revision:
    """The pinned revision of one article: the edition every prompt quotes."""

    wiki: str
    title: str
    page_id: int
    revision_id: int
    timestamp: str
    # WHY kept: the revision's own wikitext tells which rendered years only a template wrote.
    source: str = field(default="", compare=False, repr=False)

    @property
    def key(self) -> str:
        """The id a question row uses to name this article; revision ids are per wiki."""
        return f"{self.wiki}/{self.revision_id}"


@dataclass(frozen=True)
class Question:
    """One FRAMES row as the builder needs it: its index, prompt and raw link list."""

    index: int
    prompt: str
    links: list[str]


@dataclass
class Snapshot:
    """The two files' rows, in the order they are written."""

    articles: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)


class Wiki(Protocol):
    """The MediaWiki action API, one GET at a time."""

    def get(self, wiki: str, params: dict[str, str]) -> dict[str, Any]:
        """Return the decoded JSON answer to one API call on ``wiki``."""
        ...


# --- stage 2: links → pages -----------------------------------------------------------------


def split_links(raw: Iterable[str]) -> list[str]:
    """Split list items that hold several glued URLs, and strip padding around each."""
    links: list[str] = []
    for item in raw:
        links.extend(part.strip() for part in _GLUED.split(item) if part.strip(" ,"))
    return [link.rstrip(", ").strip() for link in links]


def page_ref(link: str) -> PageRef:
    """The one page a FRAMES link names; refuses a link that names no known page."""
    if link in _LINK_PAGES:
        return PageRef(*_LINK_PAGES[link])
    parts: urllib.parse.SplitResult = urllib.parse.urlsplit(
        link if "://" in link else f"https://{link}"
    )
    wiki: str = _MOBILE.get(parts.netloc, parts.netloc)
    title: str | None = _title(parts)
    if wiki not in _WIKIS or not title:
        raise SnapshotError(f"link names no page on a FRAMES wiki: {link}")
    return PageRef(wiki, title)


def _title(parts: urllib.parse.SplitResult) -> str | None:
    """The page title in a ``/wiki/<title>`` or ``/w/index.php?title=<title>`` URL."""
    raw: str | None = None
    if parts.path.startswith("/wiki/"):
        raw = parts.path.removeprefix("/wiki/")
    elif parts.path == "/w/index.php":
        raw = urllib.parse.parse_qs(parts.query).get("title", [None])[0]
        raw = None if raw is None or raw.startswith("Special:") else raw
    if not raw:
        return None
    # WHY until stable: question 764 encodes its apostrophe twice, %2527 -> %27 -> '.
    title: str = urllib.parse.unquote(raw)
    while (decoded := urllib.parse.unquote(title)) != title:
        title = decoded
    title = title.replace("_", " ").strip()
    return title[:1].upper() + title[1:]


# --- stage 3: the revision live at the cut-off ----------------------------------------------


def resolve_revision(wiki: Wiki, ref: PageRef, hops: int = 0) -> Revision:
    """The last revision of ``ref`` before the cut-off, through any redirect or later rename.

    A history belongs to a page, not a title, so the first question is WHICH page held the
    title at the cut-off. If any page was moved away from the title after the cut-off, the
    first one moved away held it then; its revision is fetched by page id. Only when nothing
    moved is the title asked directly. Asking by title first would fail two ways: a page
    swap (the "Edward II of England" article moved to "Edward II", and its short-name
    redirect took the title, history and all) returns the wrong page's 2024 revision, and
    today's redirect at a renamed title can be re-pointed ("The Beatles discography" now
    lands on "The Beatles"), so it is never followed. A page that was a redirect at the
    cut-off is followed as it pointed THEN. Refuses after ``_MAX_REDIRECTS`` hops, so a
    redirect loop terminates.
    """
    if hops > _MAX_REDIRECTS:
        raise SnapshotError(f"{ref.wiki}: {ref.title}: more than {_MAX_REDIRECTS} redirects")
    moved_away: int | None = _first_page_moved_away(wiki, ref)
    page: dict[str, Any] = _revisions(
        wiki,
        ref.wiki,
        {"titles": ref.title} if moved_away is None else {"pageids": str(moved_away)},
    )
    revisions: list[dict[str, Any]] = page.get("revisions") or []
    if not revisions:
        raise SnapshotError(f"{ref.wiki}: {ref.title}: no revision before the cut-off {CUTOFF}")
    revision: dict[str, Any] = revisions[0]
    content: str = revision["slots"]["main"]["content"]
    target: re.Match[str] | None = _REDIRECT.match(content)
    if target:
        return resolve_revision(wiki, PageRef(ref.wiki, target.group(1).strip()), hops + 1)
    return _pinned(ref.wiki, page, revision, content)


def _revisions(wiki: Wiki, on: str, page: dict[str, str]) -> dict[str, Any]:
    """The page (named by title or by id) with its newest revision before the cut-off."""
    return wiki.get(
        on,
        {
            "action": "query",
            "prop": "revisions",
            **page,
            "rvprop": "ids|timestamp|content",
            "rvslots": "main",
            "rvlimit": "1",
            "rvdir": "older",
            "rvstart": _LAST_SECOND,
        },
    )["query"]["pages"][0]


def _first_page_moved_away(wiki: Wiki, ref: PageRef) -> int | None:
    """The id of the first page moved away from ``ref``'s title after the cut-off, if any."""
    # INVARIANT: only the FIRST move after the cut-off counts; an earlier move took a
    # different page away, and a later one moved a page that took the title over afterwards.
    events: list[dict[str, Any]] = (
        wiki.get(
            ref.wiki,
            {
                "action": "query",
                "list": "logevents",
                "letype": "move",
                "letitle": ref.title,
                "lestart": CUTOFF,
                "ledir": "newer",
                "lelimit": "1",
            },
        )["query"].get("logevents")
        or []
    )
    return int(events[0]["logpage"]) if events else None


def _pinned(wiki: str, page: dict[str, Any], revision: dict[str, Any], source: str) -> Revision:
    """Build the pinned Revision, refusing one that is not strictly before the cut-off."""
    # INVARIANT: no snapshot article postdates the cut-off, whatever the API returned.
    if revision["timestamp"] >= CUTOFF:
        raise SnapshotError(
            f"{wiki}: {page['title']}: revision {revision['revid']} at {revision['timestamp']}"
            f" is not before the cut-off {CUTOFF}"
        )
    return Revision(
        wiki, page["title"], page["pageid"], revision["revid"], revision["timestamp"], source
    )


# --- stage 4: rendered HTML → text ----------------------------------------------------------

_VOID: frozenset[str] = frozenset(
    "area base br col embed hr img input link meta source track wbr".split()
)
# WHY each is dropped (decision 8): no facts, only tokens. Images cannot ride a text prompt,
# and a caption without its image is dropped with it.
_DROP_TAGS: frozenset[str] = frozenset("style script noscript figure img annotation".split())
_DROP_CLASSES: frozenset[str] = frozenset(
    """navbox navbox-styles navbar hatnote shortdescription sidebar metadata ambox sistersitebox
    authority-control toc mw-editsection noprint reference reflist references mw-references-wrap
    mw-cite-backlink infobox-image infobox-hiddenrow thumb gallery mw-empty-elt""".split()
)
_DROP_SECTIONS: frozenset[str] = frozenset(
    {
        *("References", "Notes", "Footnotes", "Citations", "Sources", "Bibliography"),
        *("Works cited", "Notes and references", "Further reading", "External links", "See also"),
    }
)
_HEADINGS: dict[str, int] = {f"h{level}": level for level in range(2, 7)}
_BREAKS: dict[str, str] = {"p": "\n\n", "li": "\n- ", "br": "\n"} | {
    tag: "\n" for tag in ("div", "ul", "ol", "dl", "dd", "dt", "blockquote", "caption", "pre")
}
_SPACES: re.Pattern[str] = re.compile(r"[ \t\r\f\v\u00a0]+")


def article_text(html: str) -> str:
    """Turn one revision's rendered HTML into the plain text a prompt quotes.

    Example, on real revisions: an infobox row becomes ``| Preceded by | Jane Pierce |``, a
    table row ``| Joseph Kirkland | Federalist | 1832 | |`` (its citation cell emptied), an
    ``<h2>Early life</h2>`` becomes ``## Early life``; the References section and everything
    under it up to the next heading of its level is gone.
    """
    parser: _ArticleText = _ArticleText()
    parser.feed(html)
    parser.close()
    return _tidy("".join(parser.out))


def _tidy(text: str) -> str:
    """Collapse runs of spaces, strip each line, and keep at most one blank line in a row."""
    lines: list[str] = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


class _ArticleText(HTMLParser):
    """A one-pass HTML walker that writes the kept text into ``out``.

    Three switches decide where a piece of text goes: inside a dropped element (``_skip``
    counts its open tags) it is discarded; inside a dropped section (``_section`` holds that
    heading's level) it is discarded until a heading of the same or a higher level; inside a
    top-level table cell it is buffered and written out as one pipe row per ``<tr>``. Tables
    nested inside a cell (an infobox sub-box) flatten into that cell.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip: int = 0
        self._section: int | None = None
        self._heading: tuple[int, list[str]] | None = None
        self._tables: int = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open a tag: start dropping, start a heading, or start a row or cell."""
        if self._skip or _dropped(tag, attrs):
            self._skip += tag not in _VOID
        elif tag in _HEADINGS:
            self._heading = (_HEADINGS[tag], [])
        elif tag == "table":
            self._tables += 1
        elif self._tables == 1 and tag in ("tr", "td", "th"):
            self._open_cell(tag)
        else:
            self._write(_BREAKS.get(tag, ""))

    def handle_endtag(self, tag: str) -> None:
        """Close a tag: stop dropping, finish a heading, a cell, a row or a table."""
        if self._skip:
            self._skip -= tag not in _VOID
        elif tag in _HEADINGS and self._heading is not None:
            self._close_heading()
        elif tag == "table":
            self._tables -= 1
            self._write("\n")
        elif self._tables == 1 and tag in ("tr", "td", "th"):
            self._close_cell(tag)
        elif tag in _BREAKS and tag != "br":
            self._write("\n")

    def handle_data(self, data: str) -> None:
        """Route text to the heading, the open cell, or the page, unless it is dropped."""
        if self._skip:
            return
        if self._heading is not None:
            self._heading[1].append(data)
        else:
            self._write(data)

    def _write(self, text: str) -> None:
        """Append kept text to the open cell (as spaces for breaks) or to the page."""
        # WHY whitespace between rows is dropped: a table's rows must sit on consecutive lines,
        # or every row reads as its own paragraph.
        between_rows: bool = self._tables > 0 and self._cell is None and text.isspace()
        if self._section is not None or not text or between_rows:
            return
        if self._cell is not None:
            self._cell.append(" " if text.isspace() else text)
        else:
            self.out.append(text)

    def _open_cell(self, tag: str) -> None:
        """Start a row, or a cell inside the open row."""
        if tag == "tr":
            self._row = []
        elif self._row is not None:
            self._cell = []

    def _close_cell(self, tag: str) -> None:
        """Finish a cell into its row, or a row into one ``| a | b |`` line."""
        if tag != "tr" and self._row is not None and self._cell is not None:
            self._row.append(_SPACES.sub(" ", "".join(self._cell).replace("\n", " ")).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            row: list[str] = self._row
            self._row = None
            if any(row):
                self._write("\n| " + " | ".join(row) + " |")

    def _close_heading(self) -> None:
        """End a dropped section at a heading of its level or above; drop or keep this one."""
        assert self._heading is not None
        level, parts = self._heading
        self._heading = None
        title: str = _SPACES.sub(" ", "".join(parts)).strip()
        if self._section is not None and level <= self._section:
            self._section = None
        if self._section is None and title in _DROP_SECTIONS:
            self._section = level
        else:
            self._write(f"\n\n{'#' * level} {title}\n\n")


def _dropped(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    """Whether this element and everything inside it carries no facts worth a token."""
    attributes: dict[str, str] = {name: value or "" for name, value in attrs}
    classes: set[str] = set(attributes.get("class", "").split())
    hidden: bool = "display:none" in attributes.get("style", "").replace(" ", "")
    return tag in _DROP_TAGS or bool(classes & _DROP_CLASSES) or hidden


# --- stages 1, 3, 4 together: the build ------------------------------------------------------


def build_snapshot(questions: Sequence[Question], wiki: Wiki) -> Snapshot:
    """Resolve, fetch and convert every gold article; refuse with every reason, or return rows.

    Example: question 0 links Beta then Alpha, question 1 links Alpha (mobile, with a fragment)
    then Gamma. Three article rows come back, sorted by title, Alpha listing both spellings;
    the question rows name ``[Beta, Alpha]`` and ``[Alpha, Gamma]`` by revision key.
    """
    refs, refusals = _page_refs(questions)
    revisions: dict[PageRef, Revision] = {}
    for ref in sorted(set(refs.values()) - _deleted_refs()):
        try:
            revisions[ref] = resolve_revision(wiki, ref)
        except SnapshotError as refused:
            refusals.append(str(refused))
    if refusals:
        raise SnapshotError("refused, nothing written:\n" + "\n".join(refusals))
    by_key: dict[str, Revision] = {revision.key: revision for revision in revisions.values()}
    links: dict[str, set[str]] = {key: set() for key in by_key}
    for link, ref in refs.items():
        if ref in revisions:
            links[revisions[ref].key].add(link)
    snapshot: Snapshot = Snapshot()
    for key in sorted(by_key, key=lambda k: (by_key[k].wiki, by_key[k].title, k)):
        snapshot.articles.append(_article_row(wiki, by_key[key], sorted(links[key])))
    snapshot.questions = [_question_row(q, refs, revisions) for q in questions]
    return snapshot


def _deleted_refs() -> set[PageRef]:
    """The known deleted pages, as the refs a cleaned link maps to."""
    return {PageRef(wiki, title) for wiki, title in _DELETED}


def _page_refs(questions: Sequence[Question]) -> tuple[dict[str, PageRef], list[str]]:
    """Every cleaned link mapped to its page, and every link that names none."""
    refs: dict[str, PageRef] = {}
    refusals: list[str] = []
    for question in questions:
        for link in split_links(question.links):
            try:
                refs[link] = page_ref(link)
            except SnapshotError as refused:
                refusals.append(f"question {question.index}: {refused}")
    return refs, refusals


def _article_row(wiki: Wiki, revision: Revision, links: list[str]) -> dict[str, Any]:
    """One ``articles.jsonl`` row: the pinned revision, every link spelling, and its text."""
    parsed: dict[str, Any] = wiki.get(
        revision.wiki,
        {
            "action": "parse",
            "oldid": str(revision.revision_id),
            "prop": "text",
            "disableeditsection": "1",
            "disablelimitreport": "1",
        },
    )
    text: str = article_text(parsed["parse"]["text"]).rstrip("\n")
    return {
        "key": revision.key,
        "wiki": revision.wiki,
        "title": revision.title,
        "page_id": revision.page_id,
        "revision_id": revision.revision_id,
        "revision_timestamp": revision.timestamp,
        "links": links,
        "text": text,
        "years_from_templates": _years_from_templates(text, revision.source),
    }


def _years_from_templates(text: str, source: str) -> list[str]:
    """Years after the cut-off that the text shows but the revision's own source never writes.

    Wikipedia draws an old revision with TODAY's templates (decision 10 accepts it), so a
    2024 revision can read "equivalent to $14,300,000 in 2025". A year the source itself
    writes, such as a planned 2026 event, is the editor's and is not flagged.
    """
    written: set[str] = set(_YEAR.findall(source))
    return sorted({y for y in _YEAR.findall(text) if int(y) >= _FIRST_YEAR_AFTER_CUTOFF} - written)


def _question_row(
    question: Question, refs: dict[str, PageRef], revisions: dict[PageRef, Revision]
) -> dict[str, Any]:
    """One ``questions.jsonl`` row: its articles in link order, each once, and any it lacks."""
    pages: list[PageRef] = list(dict.fromkeys(refs[link] for link in split_links(question.links)))
    return {
        "index": question.index,
        "prompt_sha256": hashlib.sha256(question.prompt.encode("utf-8")).hexdigest(),
        "articles": list(dict.fromkeys(revisions[p].key for p in pages if p in revisions)),
        "missing_articles": [
            {"wiki": p.wiki, "title": p.title, "deleted": _DELETED[(p.wiki, p.title)]}
            for p in pages
            if p not in revisions
        ],
    }


# --- stage 5: the files ---------------------------------------------------------------------


def write_snapshot(snapshot: Snapshot, out_dir: Path) -> dict[str, str]:
    """Write both JSONL files byte-reproducibly and return each file's sha256."""
    out_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name, rows in (
        ("articles.jsonl", snapshot.articles),
        ("questions.jsonl", snapshot.questions),
    ):
        body: bytes = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ).encode("utf-8")
        (out_dir / name).write_bytes(body)
        digests[name] = hashlib.sha256(body).hexdigest()
    return digests


# --- the network, used only by main() --------------------------------------------------------


class HttpWiki:
    """The live MediaWiki API: sequential GETs, retried on lag and overload, cached on disk."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache: Path = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, wiki: str, params: dict[str, str]) -> dict[str, Any]:
        """One API call, answered from the cache when this exact URL was fetched before."""
        query: dict[str, str] = {**params, "format": "json", "formatversion": "2", "maxlag": "5"}
        url: str = f"https://{wiki}/w/api.php?{urllib.parse.urlencode(sorted(query.items()))}"
        cached: Path = self._cache / f"{hashlib.sha256(url.encode()).hexdigest()}.json"
        if not cached.exists():
            cached.write_bytes(_fetch(url))
        try:
            answer: dict[str, Any] = json.loads(cached.read_bytes())
        except json.JSONDecodeError as broken:
            cached.unlink()
            raise SnapshotError(f"unreadable answer from {url}") from broken
        if "error" in answer:
            raise SnapshotError(f"{url}: {answer['error']}")
        return answer


def _fetch(url: str) -> bytes:
    """GET with a project User-Agent; back off and retry on 429, 5xx, lag and network loss."""
    request: urllib.request.Request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT}
    )
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body: bytes = response.read()
            if b'"code":"maxlag"' not in body:
                return body
        except urllib.error.HTTPError as failed:
            if failed.code not in _RETRY_STATUS:
                raise SnapshotError(f"{url}: HTTP {failed.code}") from failed
        except (urllib.error.URLError, TimeoutError) as lost:
            if attempt == _MAX_ATTEMPTS:
                raise SnapshotError(f"{url}: {lost}") from lost
        time.sleep(2**attempt)
    raise SnapshotError(f"{url}: still failing after {_MAX_ATTEMPTS} attempts")


def read_questions(path: Path) -> list[Question]:
    """The 824 rows of the pinned questions file, refusing any other file."""
    body: bytes = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != QUESTIONS_SHA256:
        raise SnapshotError(f"{path} is not the pinned FRAMES questions file")
    csv.field_size_limit(sys.maxsize)
    rows: list[dict[str, str]] = list(
        csv.DictReader(body.decode("utf-8").splitlines(keepends=True), delimiter="\t")
    )
    return [
        Question(int(row[""]), row["Prompt"], list(ast.literal_eval(row["wiki_links"])))
        for row in rows
    ]


def _summary(snapshot: Snapshot, digests: dict[str, str]) -> str:
    """What to paste into the ticket: counts, sha256s, and prompt sizes in characters."""
    sizes: dict[str, int] = {row["key"]: len(row["text"]) for row in snapshot.articles}
    prompts: list[int] = sorted(sum(sizes[k] for k in q["articles"]) for q in snapshot.questions)
    middle: int = prompts[len(prompts) // 2]
    lines: list[str] = [f"{name}  sha256 {digest}" for name, digest in digests.items()]
    lines += [
        f"articles: {len(snapshot.articles)}  questions: {len(snapshot.questions)}",
        f"article characters per question: median {middle}, max {prompts[-1]}",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the snapshot into ``--out`` and print its summary; exit 1 on any refusal."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/frames_snapshot"))
    args: argparse.Namespace = parser.parse_args(argv)
    try:
        questions_file: Path = args.cache_dir / "test.tsv"
        if not questions_file.exists():
            args.cache_dir.mkdir(parents=True, exist_ok=True)
            questions_file.write_bytes(_fetch(QUESTIONS_URL))
        snapshot: Snapshot = build_snapshot(
            read_questions(questions_file), HttpWiki(args.cache_dir / "wiki")
        )
    except SnapshotError as refused:
        print(refused, file=sys.stderr)
        return 1
    print(_summary(snapshot, write_snapshot(snapshot, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

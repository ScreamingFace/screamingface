"""One indexable page per leaderboard, plus the sitemap and robots.txt that list them.

FEATURE: board pages. `portal/benchmark.html?id=<id>` is the same bytes for every board, so a
crawler or link-preview fetcher that runs no script sees one document with one title. These
routes give each public board its own address, `/benchmarks/<id>/`, and fill that board's name
and description into the same shell at request time. The portal scripts then run on top of it
unchanged.

WHY a route and not generated files: the portal has no build step and must not gain one. The
shell stays a plain file; only the response differs.

INVARIANT: nothing here decides what is public. A board is described only when
`list_benchmark_summaries()` returns it, and that function owns the private-board filter and its
revalidation. A board it does not return is served as the untouched shell, exactly what
`benchmark.html?id=<id>` has always sent for it, so no board field or scored state leaves here.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode
from xml.sax.saxutils import escape as xml_escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from tortoise.exceptions import OperationalError

from .scores.catalog import BenchmarkSummary, list_benchmark_summaries
from .scores.models import Benchmark

# WHY a constant: canonical and og:url must name the production host on every deployment, so a
# dev, staging or preview copy points search engines at production instead of at itself. The
# portal's own pages already hardcode this origin in og:url.
PUBLIC_ORIGIN = "https://leaderboard.screamingface.ai"
BOARD_FILE = "benchmark.html"
# WHY 70: results pages cut a title at roughly 60 to 70 characters. The brand comes last, so
# a cut costs the least useful part; past the limit the tagline goes instead.
TITLE_LIMIT = 70
TAGLINE = "models & fusions"
SCOPE = (
    "An open leaderboard for single models and fusions: ensembles, routers, cascades. "
    "Copy any result's recipe and rerun it."
)
NOINDEX = '<meta name="robots" content="noindex,follow">'
NO_STORE = {"Cache-Control": "no-store"}
ROBOTS = f"User-agent: *\nAllow: /\n\nSitemap: {PUBLIC_ORIGIN}/sitemap.xml\n"

_RELATIVE_URL = re.compile(r'\b(href|src)="(?!/|#|https?:|data:|mailto:)([^"]+)"')
_TITLE = re.compile(r"(<title>)[^<]*(</title>)")
_HEADING = re.compile(r'(<h1 id="benchmark-name">)[^<]*(</h1>)')
_LEAD = re.compile(r'(<p class="lead" id="benchmark-desc">)[^<]*(</p>)')
_HEAD_END = re.compile(r"()(</head>)")
_META_KEYS = (
    "description",
    "og:title",
    "og:description",
    "twitter:title",
    "twitter:description",
)


def _meta(key: str) -> re.Pattern[str]:
    return re.compile(rf'(<meta (?:name|property)="{re.escape(key)}" content=")[^"]*(")')


_META = {key: _meta(key) for key in _META_KEYS}


def _put(pattern: re.Pattern[str], value: str, markup: str) -> str:
    """Replace what `pattern` brackets with `value`, already escaped by the caller."""
    return pattern.sub(lambda match: match.group(1) + value + match.group(2), markup, count=1)


def board_path(benchmark_id: str) -> str:
    # INVARIANT: the id is one path segment. `safe=""` encodes "/" too, so an id can never add
    # a segment or, as "//host", turn a redirect target into another origin.
    return f"/benchmarks/{quote(benchmark_id, safe='')}/"


def board_title(name: str) -> str:
    full = f"{name} leaderboard: {TAGLINE} | ScreamingFace"
    return full if len(full) <= TITLE_LIMIT else f"{name} leaderboard | ScreamingFace"


def board_description(name: str, focus: str | None) -> str:
    # WHY no score, rank or leader: a search result keeps this text for days while a board's
    # lead changes within hours. It states what the board is, which stays true.
    subject = f"{name} leaderboard: {focus.rstrip('.')}." if focus else f"{name} leaderboard."
    return f"{subject} {SCOPE}"


@dataclass(frozen=True)
class BoardShell:
    """`benchmark.html` prepared for serving below `/benchmarks/<id>/`."""

    markup: str

    @classmethod
    def load(cls, portal_dir: Path) -> BoardShell:
        source = (portal_dir / BOARD_FILE).read_text(encoding="utf-8")
        # WHY: under /benchmarks/<id>/ a relative "main.js" would resolve to
        # /benchmarks/<id>/main.js. Rewritten in this copy only; the file on disk keeps its
        # relative URLs so it still opens from the filesystem.
        markup = _RELATIVE_URL.sub(r'\1="/\2"', source)
        for pattern in (_TITLE, _HEADING, _LEAD, _HEAD_END, *_META.values()):
            if len(pattern.findall(markup)) != 1:
                # WHY fail at startup: a shell edit that renames one of these would otherwise
                # drop that tag from every board page with nothing to show for it.
                raise RuntimeError(f"{BOARD_FILE} must match {pattern.pattern!r} exactly once")
        return cls(markup)

    def undescribed(self) -> str:
        """The shell with its generic head, kept out of the index."""
        return _put(_HEAD_END, f"  {NOINDEX}\n", self.markup)

    def describing(self, board: BenchmarkSummary) -> str:
        name = board.display_name
        title = html.escape(board_title(name))
        description = html.escape(board_description(name, board.focus))
        url = html.escape(PUBLIC_ORIGIN + board_path(board.id))
        head = [
            f'<link rel="canonical" href="{url}">',
            f'<meta property="og:url" content="{url}">',
        ]
        if board.best_score is None:
            head.append(NOINDEX)
        markup = _put(_TITLE, title, self.markup)
        for key, pattern in _META.items():
            markup = _put(pattern, title if key.endswith("title") else description, markup)
        markup = _put(_HEADING, html.escape(name), markup)
        # WHY description alone: benchmark.js writes exactly this into the same node, so the
        # page reads the same before and after the script runs.
        markup = _put(_LEAD, html.escape(board.description or board.focus or ""), markup)
        return _put(_HEAD_END, "".join(f"  {tag}\n" for tag in head), markup)


def sitemap(boards: list[BenchmarkSummary]) -> str:
    paths = ["/", "/about.html"]
    paths += [board_path(board.id) for board in boards if board.best_score is not None]
    urls = "".join(
        f"  <url><loc>{xml_escape(PUBLIC_ORIGIN + path)}</loc></url>\n" for path in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    )


async def _public_boards() -> list[BenchmarkSummary]:
    try:
        return await list_benchmark_summaries()
    except OperationalError as exc:
        # WHY 503 and not the bare shell: a crawler reads 503 as "retry later" and keeps the
        # page it has. A 200 with a generic head, or a 404, would teach it the board is gone.
        raise HTTPException(status_code=503, detail="Store unavailable") from exc


def register_board_pages(app: FastAPI, portal_dir: Path) -> None:
    """Add the board routes. Call before the static mount, which would otherwise answer first."""
    _register_board_routes(app, BoardShell.load(portal_dir))
    _register_old_address(app, portal_dir / BOARD_FILE)
    _register_discovery(app)


def _register_board_routes(app: FastAPI, shell: BoardShell) -> None:
    @app.get("/benchmarks/{benchmark_id}/", include_in_schema=False)
    async def board_page(benchmark_id: str) -> HTMLResponse:
        boards = await _public_boards()
        board = next((item for item in boards if item.id == benchmark_id), None)
        if board is not None:
            return HTMLResponse(shell.describing(board), headers=NO_STORE)
        if await Benchmark.exists(id=benchmark_id):
            return HTMLResponse(shell.undescribed(), headers=NO_STORE)
        raise HTTPException(status_code=404)

    @app.get("/benchmarks/{benchmark_id}", include_in_schema=False)
    async def board_page_without_slash(benchmark_id: str) -> RedirectResponse:
        return RedirectResponse(board_path(benchmark_id), status_code=301)


def _register_old_address(app: FastAPI, board_file: Path) -> None:
    @app.get(f"/{BOARD_FILE}", include_in_schema=False)
    async def old_board_address(request: Request) -> Response:
        params = parse_qsl(request.url.query, keep_blank_values=True)
        benchmark_id = next((value for key, value in params if key == "id"), "")
        if not benchmark_id:
            # INVARIANT: without an id this is the static file, byte for byte.
            return FileResponse(board_file, media_type="text/html")
        rest = urlencode([(key, value) for key, value in params if key != "id"])
        target = board_path(benchmark_id) + (f"?{rest}" if rest else "")
        return RedirectResponse(target, status_code=301)


def _register_discovery(app: FastAPI) -> None:
    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap_xml() -> Response:
        boards = await _public_boards()
        return Response(sitemap(boards), media_type="application/xml", headers=NO_STORE)

    @app.get("/robots.txt", include_in_schema=False)
    async def robots_txt() -> Response:
        return Response(ROBOTS, media_type="text/plain")

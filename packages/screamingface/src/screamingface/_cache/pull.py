"""The community-cache pull loop (epic OME-1311, spec decisions 8–11 and 14).

Page after page from the hosted Engine into the local gateway, until the cursor runs out:

- the first request of a call asks for `count=true`, the total the progress shows rows against;
- every page header's revisions are checked before any of its rows is loaded;
- rows are loaded in batches as the page streams in, so download and load overlap and no page is
  held whole;
- a transient failure (a dropped connection, a rate limit or edge error, a cut or garbled page) is
  retried with backoff, waiting longer when the Engine's `Retry-After` asks to;
- the cursor is kept in memory per `(url, models)`, together with the database it loads into, so
  calling again in the same process after a failure continues from the last completed page into
  the same database (spec decision 9: nothing is written to disk).

INVARIANT: the cursor only ever advances past a page that ended with its trailer. Rows loaded from
a page that did not are still valid entries, and loading them again adds nothing.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Callable, Hashable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Final, Protocol

from screamingface._cache.pages import CutPage, MalformedPage, PageHeader, walk_page
from screamingface._cache.progress import Reporter, Snapshot, reporter
from screamingface._cache.remote import TransientPageError
from screamingface.cache import CachePullError, PullResult
from screamingface.errors import ScreamingFaceError

if TYPE_CHECKING:
    from screamingface._cache.local import LocalGateway
    from screamingface.client import Client

# WHY 4 attempts with 2/4/8 s between them: enough to ride out a gateway restart or an edge blip
# (~14 s) without turning a genuinely unavailable Engine into a minute of silence.
_ATTEMPTS: Final = 4
_BACKOFF_S: Final = (2.0, 4.0, 8.0)
# WHY a cap on `Retry-After`: a rate-limit hint is honoured, but one of minutes would leave the pull
# silent that long. A longer hint waits the cap; a limit that outlasts every attempt stops the
# pull with "call again", which continues from the last loaded page.
_RETRY_AFTER_CAP_S: Final = 60.0


class PageSource(Protocol):
    @property
    def origin(self) -> str: ...

    def open(
        self, *, after: str | None, count: bool
    ) -> AbstractContextManager[tuple[Iterator[str], Callable[[], int]]]: ...


class Destination(Protocol):
    @property
    def identity(self) -> Hashable: ...

    def prepare(self) -> None: ...

    def check(self, remote: Any, result: PullResult) -> None: ...

    def load(self, rows: Sequence[Any], result: PullResult) -> tuple[int, int]: ...

    def holds(self, key_hash: str) -> bool: ...


@dataclass
class _Cursor:
    """One pull's progress, kept for a repeat call in the same process."""

    destination: Hashable
    after: str | None = None
    # The key of the last row of the last completed page that had rows: a resume checks the
    # database still has it.
    last_key: str | None = None
    rows_read: int = 0
    rows_added: int = 0
    rows_skipped: int = 0
    pages: int = 0


# INVARIANT (spec decision 9): process memory only. A finished pull's entry is removed, so the
# next call starts over — a v1 pull always walks from the start.
# INVARIANT: an entry exists only once a page has completed, and is continued only into the
# database it was loading. A refused or failed first attempt leaves nothing to resume, and a call
# into another database starts over rather than skip the pages it never received.
_CURSORS: dict[tuple[str, tuple[str, ...]], _Cursor] = {}

# INVARIANT (spec decision 14): one browser sign-in per process and hosted origin. A pull's Client
# outlives the call, so a repeat call or a resume reuses its Access session; it is never closed
# here, like the process-wide default Client.
_SESSIONS: dict[tuple[str, str, int], Client] = {}
_SESSIONS_LOCK = Lock()

# INVARIANT: one walk at a time per cursor key. A second call while one runs is refused rather
# than share the cursor, whose counts two walks would race.
_RUNNING: set[tuple[str, tuple[str, ...]]] = set()
_RUNNING_LOCK = Lock()


def close_sessions() -> None:
    """Close and forget this module's own pull Clients (`sf.close()` calls it)."""
    with _SESSIONS_LOCK:
        clients = list(_SESSIONS.values())
        _SESSIONS.clear()
    for client in clients:
        client.close()


def pull_into(
    models: tuple[str, ...], *, url: str | None, data_dir: Path, progress: bool | None
) -> PullResult:
    """Pull from the hosted Engine at `url` (production when None) into `data_dir`'s gateway."""
    from screamingface._cache.local import LocalGateway, gateway_database
    from screamingface._cache.remote import HostedPages
    from screamingface.client import DEFAULT_ENGINE_URL

    empty = PullResult(rows_read=0, rows_added=0, pages=0, resumed=False, complete=False)
    destination: LocalGateway = LocalGateway(gateway_database(data_dir), empty=empty)
    # WHY `is None`, not `or`: only None means production; a blank URL is refused by the Client.
    client = _session(DEFAULT_ENGINE_URL if url is None else url)
    source = HostedPages(client._http, models)  # noqa: SLF001 — the Access-signed session
    return run_pull(source, destination, models=models, report=reporter(progress))


def _session(url: str) -> Client:
    """The process's signed-in Client for `url`'s origin: this module's own once it has one,
    else the default Client when it is already open on that origin, else a new one of this
    module's, kept for the process.

    WHY the module's own first: it holds the Access token of an earlier pull, and a default
    Client the app opens later on the same origin has none yet (PR #1446 review).
    WHY the default Client only when it already exists: creating it would follow
    `SCREAMINGFACE_ENGINE_URL` or a local stack, which is where runs go, not where the cache
    comes from (spec decision 14).
    """
    from screamingface import _default_client
    from screamingface.client import Client

    origin = _default_client._comparable_origin(url)  # noqa: SLF001 — one origin rule
    with _SESSIONS_LOCK:
        own = _SESSIONS.get(origin)
        if own is not None and not own.closed:
            return own
        shared = _default_client._client  # noqa: SLF001 — read, never created here
        if (
            shared is not None
            and not shared.closed
            and _default_client._comparable_origin(shared.engine_url) == origin  # noqa: SLF001
        ):
            return shared
        client = Client(engine_url=url)
        _SESSIONS[origin] = client
        return client


def run_pull(
    source: PageSource,
    destination: Destination,
    *,
    models: tuple[str, ...],
    report: Reporter,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PullResult:
    key = (source.origin, models)
    with _RUNNING_LOCK:
        if key in _RUNNING:
            raise CachePullError(
                "A pull of the same url and models is already running in this process",
                code="pull_in_progress",
                hint="Wait for it to finish; it loads the same rows.",
                result=PullResult(0, 0, 0, resumed=False, complete=False),
            )
        _RUNNING.add(key)
    try:
        return _walk(source, destination, key, report, sleep=sleep, clock=clock)
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(key)


def _walk(
    source: PageSource,
    destination: Destination,
    key: tuple[str, tuple[str, ...]],
    report: Reporter,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> PullResult:
    models = key[1]
    loop = _Loop(source, destination, key, report, clock=clock)
    report.preparing(source.origin)
    try:
        destination.prepare()
        result = loop.walk(sleep)
        if models and result.rows_read == 0:
            # WHY: the filter is exact, so a typo matches nothing and the pull still finishes;
            # the runs that follow would then miss on every call with nothing to say why.
            warnings.warn(
                f"no rows in the hosted cache matched {', '.join(models)}; model names must "
                "match the hosted cache exactly (for example "
                "'openrouter/anthropic/claude-opus-5.5')",
                UserWarning,
                stacklevel=2,
            )
        return result
    except CachePullError as error:
        report.stopped(loop.snapshot(), error.message)
        raise
    except ScreamingFaceError as error:
        report.stopped(loop.snapshot(), error.message)
        raise CachePullError(
            error.message, code=error.code, hint=error.hint, result=loop.result(complete=False)
        ) from error
    except KeyboardInterrupt as interrupt:
        report.stopped(loop.snapshot(), "interrupted")
        # WHY the original interrupt, with the counts attached: a CachePullError would let
        # `except Exception` swallow a Ctrl-C (spec decision 14: it carries the counts).
        interrupt.result = loop.result(complete=False)  # pyright: ignore[reportAttributeAccessIssue]
        raise
    except Exception as error:
        # INVARIANT: every call that started the display stops it. An error nobody anticipated
        # still reaches the caller as itself, with its own traceback.
        report.stopped(loop.snapshot(), f"{type(error).__name__}: {error}")
        raise


class _Loop:
    """One call's walk: the cursor it continues, its counts, and the progress display."""

    def __init__(
        self,
        source: PageSource,
        destination: Destination,
        key: tuple[str, tuple[str, ...]],
        report: Reporter,
        *,
        clock: Callable[[], float],
    ) -> None:
        self._source = source
        self._destination = destination
        self._key = key
        saved = _CURSORS.get(key)
        identity = destination.identity
        # WHY the last key as well as the identity: a backup copied over the file keeps its
        # inode, and may lack the pages before the cursor. One indexed lookup, on resume only.
        # AIDEV-NOTE: a last row the local gateway skipped as unservable reads as missing too;
        # the pull then starts over, which costs a re-read and loses nothing.
        self._resumed = (
            saved is not None
            and saved.destination == identity
            and (saved.last_key is None or destination.holds(saved.last_key))
        )
        self._cursor = saved if saved and self._resumed else _Cursor(identity)
        self._report = report
        self._clock = clock
        self._started = clock()
        self._rows_at_start = self._cursor.rows_read
        self._total: int | None = None
        # The distinct rows read of the page in progress, across all its attempts.
        # INVARIANT: rows_read is never below rows_added. A retry of the same rows counts them
        # once, and a page that changed between attempts counts every row any attempt loaded.
        self._page_rows: set[object] = set()
        self._bytes_before = 0
        self._bytes: Callable[[], int] = lambda: 0

    def walk(self, sleep: Callable[[float], None]) -> PullResult:
        first = True
        while True:
            after = _with_retries(partial(self.page, count=first), self, sleep)
            first = False
            # INVARIANT: the cursor advances, and the pull reports complete, only into the
            # database it started loading. Checked once a page, before the cursor moves (a stat:
            # microseconds), so a database replaced mid-pull is caught on its last page too.
            if self._destination.identity != self._cursor.destination:
                raise CachePullError(
                    "The local gateway database was replaced during the pull",
                    code="destination_changed",
                    hint="Call pull_from_remote() again; it starts over into the new database.",
                    result=self.result(complete=False),
                )
            self._cursor.after, self._cursor.pages = after, self._cursor.pages + 1
            if after is not None:
                _CURSORS[self._key] = self._cursor
            else:
                _CURSORS.pop(self._key, None)
                result = self.result(complete=True)
                self._report.finished(self.snapshot(), result)
                return result

    def page(self, *, count: bool) -> str | None:
        skipped = [0]
        last: list[str | None] = [None]

        def header(value: PageHeader) -> None:
            self._destination.check(value.revisions, self.result(complete=False))
            if value.remaining is not None:
                self._total = self._cursor.rows_read + value.remaining

        def rows(batch: list[Any]) -> None:
            added, skips = self._destination.load(batch, self.result(complete=False))
            self._cursor.rows_added += added
            skipped[0] += skips
            # WHY `or object()`: a row with no key (skipped as unservable) still counts as read.
            self._page_rows.update(row.get("key_hash") or object() for row in batch)
            last[0] = batch[-1].get("key_hash") if batch else None
            self._report.update(self.snapshot(extra_rows=len(self._page_rows)))

        with self._source.open(after=self._cursor.after, count=count) as (lines, received):
            self._bytes = received
            try:
                after = walk_page(lines, on_header=header, on_rows=rows)
            finally:
                self._bytes_before += received()
                self._bytes = lambda: 0
        self._completed(skipped[0], last[0])
        return after

    def _completed(self, skipped: int, last_key: str | None) -> None:
        # WHY at the page's end: a retried page is read and skipped again, and counting each
        # attempt would count those rows twice.
        self._cursor.rows_read += len(self._page_rows)
        self._cursor.rows_skipped += skipped
        if last_key is not None:
            self._cursor.last_key = last_key
        self._page_rows = set()

    def result(self, *, complete: bool) -> PullResult:
        return PullResult(
            rows_read=self._cursor.rows_read + (0 if complete else len(self._page_rows)),
            rows_added=self._cursor.rows_added,
            pages=self._cursor.pages,
            resumed=self._resumed,
            complete=complete,
            rows_skipped=self._cursor.rows_skipped,
        )

    def snapshot(self, *, extra_rows: int = 0) -> Snapshot:
        return Snapshot(
            origin=self._source.origin,
            rows_read=self._cursor.rows_read + extra_rows,
            rows_added=self._cursor.rows_added,
            total=self._total,
            bytes_received=self._bytes_before + self._bytes(),
            elapsed_s=self._clock() - self._started,
            rows_at_start=self._rows_at_start,
        )


def _with_retries(
    read: Callable[[], str | None], loop: _Loop, sleep: Callable[[float], None]
) -> str | None:
    for attempt in range(_ATTEMPTS):
        try:
            return read()
        except (TransientPageError, CutPage) as exc:
            if attempt == _ATTEMPTS - 1:
                raise CachePullError(
                    f"The hosted Engine stopped answering: {exc}",
                    code="community_cache_unavailable",
                    hint="Call pull_from_remote() again to continue from the last loaded page.",
                    result=loop.result(complete=False),
                ) from exc
            hint = exc.retry_after if isinstance(exc, TransientPageError) else None
            sleep(max(_BACKOFF_S[attempt], min(hint or 0.0, _RETRY_AFTER_CAP_S)))
        except MalformedPage as exc:
            raise CachePullError(
                f"The hosted Engine sent a page this client cannot read: {exc}",
                code="malformed_page",
                result=loop.result(complete=False),
            ) from exc
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["close_sessions", "pull_into", "run_pull"]

"""The community-cache pull loop (epic OME-1311, spec decisions 8–11 and 14).

FEATURE: community cache, available to a local engine (epic OME-1311).
STORY: as a user of a local engine, I pull the community cache once and my later runs hit it; if
the pull stops, I call it again and it continues.

Pinned here: the loop walks pages until the cursor runs out and loads every row once; only the
first request asks for the count; revisions are checked on every header before its rows load; a
transient failure is retried and a persistent one stops the pull with the counts so far; a repeat
call in the same process continues from the last completed page, and a different filter or a
finished pull starts over; the cursor never advances past a page without its trailer; and every
failure reaches the caller as a `CachePullError` that says how far the pull got.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from screamingface._cache import pull as pull_module
from screamingface._cache.pages import PAGE_SCHEMA
from screamingface._cache.progress import Snapshot
from screamingface._cache.pull import run_pull
from screamingface._cache.remote import TransientPageError
from screamingface.cache import CachePullError, PullResult
from screamingface.errors import AuthenticationError

_REVISIONS = {"parameter_contract": "p1"}


@pytest.fixture(autouse=True)
def _fresh_cursors() -> Iterator[None]:
    pull_module._CURSORS.clear()
    yield
    pull_module._CURSORS.clear()


def _page(
    keys: list[str],
    after: str | None,
    *,
    remaining: int | None = None,
    revisions: dict[str, str] | None = None,
    trailer: bool = True,
) -> list[str]:
    header: dict[str, object] = {"schema": PAGE_SCHEMA, "revisions": revisions or _REVISIONS}
    if remaining is not None:
        header["remaining"] = remaining
    lines = [json.dumps(header), *(json.dumps({"key_hash": k}) for k in keys)]
    if trailer:
        lines.append(json.dumps({"next": after}))
    return lines


class _Source:
    """Pages by cursor; each entry may be a page or an exception to raise for that request."""

    origin = "https://engine.test"

    def __init__(self, pages: dict[str | None, list[object]]) -> None:
        self._pages = {cursor: list(answers) for cursor, answers in pages.items()}
        self.requests: list[tuple[str | None, bool]] = []

    @contextmanager
    def open(
        self, *, after: str | None, count: bool
    ) -> Iterator[tuple[Iterator[str], Callable[[], int]]]:
        self.requests.append((after, count))
        answer = self._pages[after].pop(0) if len(self._pages[after]) > 1 else self._pages[after][0]
        if isinstance(answer, BaseException):
            raise answer
        assert isinstance(answer, list)
        yield iter(answer), lambda: 100


class _Gateway:
    identity = "aigateway.sqlite3"

    def __init__(self, *, refuse_revisions: bool = False, refuse_prepare: bool = False) -> None:
        self.loaded: list[str] = []
        self.unservable: set[str] = set()
        self.checked: list[dict[str, str]] = []
        self._refuse_revisions = refuse_revisions
        self._refuse_prepare = refuse_prepare

    def prepare(self) -> None:
        if self._refuse_prepare:
            raise CachePullError(
                "no local gateway",
                code="local_gateway_missing",
                result=PullResult(0, 0, 0, False, False),
            )

    def check(self, remote: Any, result: PullResult) -> None:
        self.checked.append(dict(remote))
        if self._refuse_revisions:
            raise CachePullError("revisions differ", code="revision_mismatch", result=result)

    def load(self, rows: Any, result: PullResult) -> tuple[int, int]:
        keys = [row["key_hash"] for row in rows]
        new = [key for key in keys if key not in self.loaded and key not in self.unservable]
        self.loaded.extend(new)
        return len(new), sum(key in self.unservable for key in keys)


class _Report:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def preparing(self, origin: str) -> None:
        self.events.append(("preparing", origin))

    def update(self, snapshot: Snapshot) -> None:
        self.events.append(("update", snapshot))

    def finished(self, snapshot: Snapshot, result: PullResult) -> None:
        self.events.append(("finished", result))

    def stopped(self, snapshot: Snapshot, reason: str) -> None:
        self.events.append(("stopped", reason))


def _run(
    source: _Source,
    gateway: _Gateway,
    *,
    models: tuple[str, ...] = (),
    report: _Report | None = None,
) -> PullResult:
    return run_pull(
        source,
        gateway,
        models=models,
        report=report or _Report(),
        sleep=lambda _s: None,
        clock=lambda: 0.0,
    )


# --- a whole pull ---------------------------------------------------------------------------------


def test_a_pull_walks_every_page_and_loads_every_row_once() -> None:
    source = _Source(
        {None: [_page(["a", "b"], "c1", remaining=4)], "c1": [_page(["c", "d"], None)]}
    )
    gateway = _Gateway()

    result = _run(source, gateway)

    assert gateway.loaded == ["a", "b", "c", "d"]
    assert result == PullResult(rows_read=4, rows_added=4, pages=2, resumed=False, complete=True)
    assert source.requests == [(None, True), ("c1", False)]


def test_rows_already_held_locally_are_read_but_not_added() -> None:
    source = _Source({None: [_page(["a", "b"], None)]})
    gateway = _Gateway()
    gateway.loaded = ["a"]

    result = _run(source, gateway)

    assert (result.rows_read, result.rows_added) == (2, 1)


def test_rows_the_local_gateway_cannot_serve_are_skipped_and_counted_once() -> None:
    # WHY a cut first attempt: its skipped row is skipped again on the retry, and counted once.
    source = _Source({None: [_page(["a", "x"], None, trailer=False), _page(["a", "x", "b"], None)]})
    gateway = _Gateway()
    gateway.unservable = {"x"}

    result = _run(source, gateway)

    assert gateway.loaded == ["a", "b"]
    assert (result.rows_read, result.rows_added, result.rows_skipped) == (3, 2, 1)


def test_revisions_are_checked_on_every_page_header() -> None:
    source = _Source({None: [_page(["a"], "c1")], "c1": [_page(["b"], None)]})
    gateway = _Gateway()

    _run(source, gateway)

    assert gateway.checked == [_REVISIONS, _REVISIONS]


def test_a_revision_mismatch_stops_the_pull_before_its_rows_load() -> None:
    source = _Source({None: [_page(["a"], None)]})
    gateway = _Gateway(refuse_revisions=True)

    with pytest.raises(CachePullError) as raised:
        _run(source, gateway)

    assert raised.value.code == "revision_mismatch"
    assert gateway.loaded == []


def test_a_refused_destination_makes_no_request() -> None:
    source = _Source({None: [_page(["a"], None)]})

    with pytest.raises(CachePullError, match="no local gateway"):
        _run(source, _Gateway(refuse_prepare=True))

    assert source.requests == []


# --- retries --------------------------------------------------------------------------------------


def test_a_transient_failure_is_retried_and_the_pull_finishes() -> None:
    source = _Source(
        {None: [TransientPageError("503"), _page(["a"], None, trailer=False), _page(["a"], None)]}
    )
    gateway = _Gateway()

    result = _run(source, gateway)

    assert result.complete
    assert result.rows_read == 1
    assert gateway.loaded == ["a"]
    assert [count for _, count in source.requests] == [True, True, True]


def test_a_persistent_failure_stops_with_the_counts_so_far() -> None:
    source = _Source({None: [_page(["a"], "c1")], "c1": [TransientPageError("504")]})

    with pytest.raises(CachePullError) as raised:
        _run(source, _Gateway())

    assert raised.value.code == "community_cache_unavailable"
    assert raised.value.result == PullResult(1, 1, 1, False, False)
    assert len(source.requests) == 1 + pull_module._ATTEMPTS


def test_a_malformed_page_is_not_retried() -> None:
    source = _Source({None: [["not json"]]})

    with pytest.raises(CachePullError) as raised:
        _run(source, _Gateway())

    assert raised.value.code == "malformed_page"
    assert len(source.requests) == 1


def test_an_sdk_error_reaches_the_caller_as_a_pull_error_with_its_cause() -> None:
    failure = AuthenticationError("signed out", code="authentication_required")
    source = _Source({None: [failure]})
    report = _Report()

    with pytest.raises(CachePullError) as raised:
        _run(source, _Gateway(), report=report)

    assert raised.value.code == "authentication_required"
    assert raised.value.__cause__ is failure
    assert report.events[-1] == ("stopped", "signed out")


# --- resume ---------------------------------------------------------------------------------------


def test_a_repeat_call_continues_from_the_last_completed_page() -> None:
    gateway = _Gateway()
    failing = _Source({None: [_page(["a"], "c1")], "c1": [TransientPageError("boom")]})
    with pytest.raises(CachePullError):
        _run(failing, gateway)

    healed = _Source({"c1": [_page(["b"], None)]})
    result = _run(healed, gateway)

    assert healed.requests == [("c1", True)]
    assert result == PullResult(rows_read=2, rows_added=2, pages=2, resumed=True, complete=True)


def test_a_finished_pull_starts_over_next_time() -> None:
    pages: dict[str | None, list[object]] = {None: [_page(["a"], None)]}
    _run(_Source(pages), _Gateway())

    source = _Source(pages)
    result = _run(source, _Gateway())

    assert source.requests == [(None, True)]
    assert result.resumed is False


def test_a_different_filter_does_not_continue_another_filters_pull() -> None:
    with pytest.raises(CachePullError):
        _run(
            _Source({None: [_page(["a"], "c1")], "c1": [TransientPageError("x")]}),
            _Gateway(),
            models=("m1",),
        )

    source = _Source({None: [_page(["b"], None)]})
    result = _run(source, _Gateway(), models=("m2",))

    assert source.requests == [(None, True)]
    assert result.resumed is False


def test_an_interrupted_pull_keeps_its_cursor_for_the_next_call() -> None:
    class _Interrupting(_Source):
        @contextmanager
        def open(self, *, after: str | None, count: bool):  # type: ignore[override]
            if after == "c1":
                raise KeyboardInterrupt
            with super().open(after=after, count=count) as opened:
                yield opened

    report = _Report()
    with pytest.raises(KeyboardInterrupt):
        _run(_Interrupting({None: [_page(["a"], "c1")]}), _Gateway(), report=report)

    assert report.events[-1] == ("stopped", "interrupted")
    assert pull_module._CURSORS[("https://engine.test", ())].after == "c1"


def test_an_interrupted_pull_carries_its_counts() -> None:
    # WHY the KeyboardInterrupt itself: spec decision 14 gives an interrupted pull its counts,
    # and a CachePullError would let `except Exception` swallow the Ctrl-C.
    class _Interrupting(_Source):
        @contextmanager
        def open(self, *, after: str | None, count: bool):  # type: ignore[override]
            if after == "c1":
                raise KeyboardInterrupt
            with super().open(after=after, count=count) as opened:
                yield opened

    with pytest.raises(KeyboardInterrupt) as raised:
        _run(_Interrupting({None: [_page(["a", "b"], "c1")]}), _Gateway())

    assert raised.value.result == PullResult(  # type: ignore[attr-defined]
        rows_read=2, rows_added=2, pages=1, resumed=False, complete=False
    )


# --- progress -------------------------------------------------------------------------------------


def test_progress_shows_rows_against_the_counted_total() -> None:
    report = _Report()
    source = _Source({None: [_page(["a", "b"], "c1", remaining=3)], "c1": [_page(["c"], None)]})

    _run(source, _Gateway(), report=report)

    updates = [event for kind, event in report.events if kind == "update"]
    assert isinstance(updates[0], Snapshot)
    assert [(u.rows_read, u.total) for u in updates] == [(2, 3), (3, 3)]  # type: ignore[union-attr]
    assert report.events[0] == ("preparing", "https://engine.test")
    assert report.events[-1][0] == "finished"


def test_an_unexpected_failure_stops_the_progress_and_reaches_the_caller_as_itself() -> None:
    failure = ValueError("disk on fire")

    class _Broken(_Gateway):
        def load(self, rows: Any, result: PullResult) -> int:
            raise failure

    report = _Report()
    with pytest.raises(ValueError) as raised:
        _run(_Source({None: [_page(["a"], None)]}), _Broken(), report=report)

    assert raised.value is failure
    assert report.events[-1] == ("stopped", "ValueError: disk on fire")


def test_a_pull_into_another_database_does_not_continue_the_first_ones() -> None:
    class _Elsewhere(_Gateway):
        identity = "elsewhere/aigateway.sqlite3"

    with pytest.raises(CachePullError):
        _run(_Source({None: [_page(["a"], "c1")], "c1": [TransientPageError("x")]}), _Gateway())

    source = _Source({None: [_page(["a", "b"], None)]})
    result = _run(source, _Elsewhere())

    assert source.requests == [(None, True)]
    assert result == PullResult(rows_read=2, rows_added=2, pages=1, resumed=False, complete=True)


@pytest.mark.parametrize(
    "first_attempt",
    [
        pytest.param({"gateway": _Gateway(refuse_prepare=True)}, id="refused-destination"),
        pytest.param(
            {"pages": {None: [AuthenticationError("signed out", code="authentication_required")]}},
            id="failed-first-page",
        ),
    ],
)
def test_an_attempt_that_completed_no_page_leaves_nothing_to_resume(
    first_attempt: dict[str, Any],
) -> None:
    pages = first_attempt.get("pages", {None: [_page(["a"], None)]})
    with pytest.raises(CachePullError):
        _run(_Source(pages), first_attempt.get("gateway", _Gateway()))

    assert pull_module._CURSORS == {}
    result = _run(_Source({None: [_page(["a"], None)]}), _Gateway())
    assert result.resumed is False


def test_a_resumed_calls_progress_knows_where_this_call_started() -> None:
    gateway = _Gateway()
    with pytest.raises(CachePullError):
        _run(_Source({None: [_page(["a"], "c1")], "c1": [TransientPageError("x")]}), gateway)

    report = _Report()
    _run(_Source({"c1": [_page(["b"], None)]}), gateway, report=report)

    updates = [event for kind, event in report.events if kind == "update"]
    assert [(u.rows_read, u.rows_at_start) for u in updates] == [(2, 1)]  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("retry_after", "waited"),
    [(None, 2.0), (1.0, 2.0), (30.0, 30.0), (600.0, 60.0)],
    ids=["no-hint", "shorter-than-backoff", "longer-than-backoff", "capped"],
)
def test_a_retry_waits_for_the_engines_retry_after_within_a_cap(
    retry_after: float | None, waited: float
) -> None:
    slept: list[float] = []
    source = _Source(
        {None: [TransientPageError("rate limited", retry_after=retry_after), _page(["a"], None)]}
    )

    result = run_pull(
        source, _Gateway(), models=(), report=_Report(), sleep=slept.append, clock=lambda: 0.0
    )

    assert slept == [waited]
    assert result.complete is True

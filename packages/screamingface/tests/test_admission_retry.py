"""A Candidate the Engine has not started yet is shown as waiting for capacity (OME-1066).

FEATURE: OME-1066 — Engine admission (OME-1091) turns "no room" into a wait, not a failure.
STORY: as a researcher whose Evaluation starts while the Engine is busy, my Candidates are
shown as waiting for capacity and then start — and waiting never stops my other Candidates.

Since E5 P2 the Engine drives each Run and retries at capacity itself (spec D3), so the Client's
900 s admission loop is gone: a Candidate the Engine has not started yet is `pending` on the
Run's stream, however long it waits, and is never failed by the Client for waiting.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from _isolation_engine import candidate
from test_evaluation_outcome import valid_outcome

from screamingface._core.ports import _ConnectionNotice, _RunOutcome
from screamingface._engine import run_client
from screamingface._evaluation.following import _AsyncFollow, _SyncFollow
from screamingface._evaluation.outcome import _Failed
from screamingface._evaluation.progress import _ProgressObserver
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import _candidate_row_html
from screamingface.events import Event


class _Listener:
    """An `on_event` that also takes connection notices, as the runner's bound observer does."""

    def __init__(self) -> None:
        self.notices: list[tuple[str, int | None]] = []

    def __call__(self, event: Event) -> None:
        del event

    def connection(self, notice: _ConnectionNotice) -> None:
        self.notices.append((notice.state, notice.attempt))


class _Observer:
    """The runner's observer, as the follow sink drives it."""

    def __init__(self) -> None:
        self.listeners: dict[str, _Listener] = {}
        self.begun: list[str] = []
        self.failed: list[str] = []

    def bind(self, selected: Any) -> _Listener:
        return self.listeners.setdefault(selected.name, _Listener())

    def begin(self, selected: Any) -> None:
        self.begun.append(selected.name)

    def candidate_failed(self, selected: Any, exc: Exception) -> None:
        self.failed.append(selected.name)

    def candidate_stopped(self, selected: Any) -> None:
        self.failed.append(selected.name)


class _AsyncObserver(_Observer):
    async def begin(self, selected: Any) -> None:  # type: ignore[override]
        self.begun.append(selected.name)

    async def candidate_failed(self, selected: Any, exc: Exception) -> None:  # type: ignore[override]
        self.failed.append(selected.name)


_PAIR = (candidate("queued"), candidate("running"))


def _sink(observer: _Observer) -> _SyncFollow:
    return _SyncFollow(_PAIR, observer, None)  # type: ignore[arg-type]


def test_a_refused_start_waits_then_the_run_completes() -> None:
    observer = _Observer()
    sink = _sink(observer)

    sink.state(0, "pending")
    sink.state(0, "pending")
    sink.state(0, "scheduled")
    sink.settled(0, "succeeded", valid_outcome("queued"))

    assert observer.listeners["queued"].notices == [
        ("waiting_for_capacity", None),
        ("admitted", None),
    ]
    assert observer.begun == ["queued"]
    assert isinstance(sink.results[0], _RunOutcome)


@pytest.mark.asyncio
async def test_async_a_refused_start_waits_then_the_run_completes() -> None:
    observer = _AsyncObserver()
    sink = _AsyncFollow(_PAIR, observer, None)  # type: ignore[arg-type]

    await sink.state(0, "pending")
    await sink.state(0, "running")
    await sink.settled(0, "succeeded", valid_outcome("queued"))

    assert observer.listeners["queued"].notices == [
        ("waiting_for_capacity", None),
        ("admitted", None),
    ]
    assert observer.begun == ["queued"]


def test_a_start_that_is_never_admitted_ends_with_a_capacity_error() -> None:
    """The Client sets no budget on a wait: a Candidate the Engine has not started stays
    `pending` until the Engine starts it or the Run stops (spec D12)."""
    observer = _Observer()
    sink = _sink(observer)

    for _ in range(1000):
        sink.state(0, "pending")

    assert observer.failed == []
    assert 0 not in sink.results
    assert observer.listeners["queued"].notices == [("waiting_for_capacity", None)]


def test_a_waiting_start_does_not_stop_a_sibling() -> None:
    observer = _Observer()
    sink = _sink(observer)

    sink.state(0, "pending")
    sink.state(1, "running")
    sink.settled(1, "succeeded", valid_outcome("running"))
    sink.state(0, "scheduled")
    sink.settled(0, "succeeded", valid_outcome("queued"))

    assert [type(outcome) for _, outcome in sink.settled_in_order()] == [_RunOutcome] * 2
    assert observer.listeners["running"].notices == []


def test_a_candidate_the_run_stopped_while_it_waited_reads_stopped() -> None:
    observer = _Observer()
    sink = _sink(observer)

    sink.state(0, "pending")
    sink.settled(0, "stopped", RuntimeError("stopped before it ran"))

    assert isinstance(sink.results[0], _Failed)
    assert observer.failed == ["queued"]


# --- What the user sees -------------------------------------------------------------------


_WAITING = _ConnectionNotice(state="waiting_for_capacity", attempt=1)
_ADMITTED = _ConnectionNotice(state="admitted")
_QUEUED = _ConnectionNotice(state="waiting_for_capacity")


def test_terminal_progress_prints_generic_capacity_lines() -> None:
    stream = io.StringIO()
    observer = _ProgressObserver(stream)
    observer.connection(candidate("opus"), _WAITING)
    observer.connection(candidate("opus"), _ADMITTED)

    assert stream.getvalue().splitlines() == [
        "ScreamingFace · opus · waiting for Engine capacity (attempt 1)",
        "ScreamingFace · opus · Engine capacity available — starting",
    ]


def test_a_candidate_the_engine_queues_waits_with_no_attempt() -> None:
    stream = io.StringIO()
    _ProgressObserver(stream).connection(candidate("opus"), _QUEUED)

    assert stream.getvalue().splitlines() == [
        "ScreamingFace · opus · waiting for Engine capacity",
    ]


def test_panel_row_shows_the_wait_then_returns_to_its_status() -> None:
    selected = candidate("opus")
    progress = _EvaluationProgress(candidates=(selected,), case_count=1)
    progress.begin(selected)
    row = progress.rows[0]
    normal = _candidate_row_html(row, 1.0)

    progress.connection(selected, _WAITING)
    assert "Waiting for Engine capacity (attempt 1)" in _candidate_row_html(row, 1.0)
    assert progress.announcement == "opus waiting for Engine capacity (attempt 1)"

    progress.connection(selected, _ADMITTED)
    assert _candidate_row_html(row, 1.0) == normal
    assert progress.announcement == "opus Engine capacity available"

    progress.connection(selected, _QUEUED)
    assert progress.announcement == "opus waiting for Engine capacity"


def test_the_socket_sends_keepalive_pings_while_the_start_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT (review fix 6): an edge closes an idle WebSocket (Cloudflare: ~100 s), and a
    # Candidate may wait for capacity for hours. The follow's keepalive pings are traffic that
    # keeps it open, beside the Engine's heartbeats.
    seen: dict[str, Any] = {}
    monkeypatch.setattr(run_client.sync_ws, "connect", lambda url, **kw: seen.update(kw))
    client = run_client.RunClient(Any, "https://engine.test", _Auth(), None)  # type: ignore[arg-type]

    client._socket("run_" + "a" * 32)

    assert seen["ping_interval"] == run_client._KEEPALIVE_PING_S < 100


class _Auth:
    def websocket_headers(self) -> dict[str, str]:
        return {}

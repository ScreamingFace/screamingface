"""The "reconnecting (attempt n)" progress line (OME-1016 plan step 4.3, spec 2026-09-28 R4).

FEATURE: OME-1016 — a deploy mid-Run is visible, not silent.
STORY: as a researcher watching an Evaluation during an engine deploy, I see that a
candidate is reconnecting — and that it came back — instead of a frozen row.

INVARIANT: the notice is private to the built-in progress output. The user's `on_event`
callback receives only public Events (spec R5, open question Q1).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from _reconnect_engine import RESULT_BODY, StubEngine, candidate, stub_engine

from screamingface._core.ports import _ConnectionListener, _ConnectionNotice
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport
from screamingface._evaluation.model import Candidate, _compiled_candidate, _compiled_operation
from screamingface._evaluation.progress import _ProgressObserver
from screamingface._evaluation.runner import _AsyncEventObserver, _SyncEventObserver
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import _candidate_row_html
from screamingface._ui.evaluation_widget import _NotebookEvaluationView
from screamingface.events import Event, Started

_RECONNECTING = _ConnectionNotice(state="reconnecting", attempt=2)
_RECONNECTED = _ConnectionNotice(state="reconnected")


class _Listener:
    """An `on_event` that is also a connection listener, as the runner's bound observer is."""

    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[Event] = []
        self.notices: list[_ConnectionNotice] = []
        self._fail = fail

    def __call__(self, event: Event) -> None:
        self.events.append(event)

    def connection(self, notice: _ConnectionNotice) -> None:
        self.notices.append(notice)
        if self._fail:
            raise RuntimeError("progress renderer defect")


def _transport(engine: StubEngine) -> Url4CloudTransport:
    return Url4CloudTransport(engine.url, reconnect_base_delay_s=0.01)


def _expected_two_outages() -> list[tuple[str, int | None]]:
    # Two drops inside one outage window: the attempt count keeps growing (OME-1141).
    return [("reconnecting", 1), ("reconnected", None), ("reconnecting", 2), ("reconnected", None)]


# --- Transport: one notice per attempt, one on resume -------------------------------------


def test_transport_sends_one_notice_per_attempt_and_one_on_resume() -> None:
    listener = _Listener()
    with stub_engine(drops=2) as engine:
        transport = _transport(engine)
        try:
            outcome = transport.run(candidate(), listener)
        finally:
            transport.close()

    assert outcome.result_body == RESULT_BODY
    assert [(n.state, n.attempt) for n in listener.notices] == _expected_two_outages()
    assert all(isinstance(event, Event) for event in listener.events)


@pytest.mark.asyncio
async def test_async_transport_sends_the_same_notices() -> None:
    listener = _Listener()
    with stub_engine(drops=2) as engine:
        transport = AsyncUrl4CloudTransport(engine.url, reconnect_base_delay_s=0.01)
        try:
            outcome = await transport.run(candidate(), listener)
        finally:
            await transport.close()

    assert outcome.result_body == RESULT_BODY
    assert [(n.state, n.attempt) for n in listener.notices] == _expected_two_outages()


def test_a_failing_listener_does_not_end_the_run() -> None:
    # INVARIANT: progress is decorative; a renderer defect must not stop paid work.
    listener = _Listener(fail=True)
    with stub_engine() as engine:
        transport = _transport(engine)
        try:
            outcome = transport.run(candidate(), listener)
        finally:
            transport.close()

    assert outcome.result_body == RESULT_BODY
    assert [n.state for n in listener.notices] == ["reconnecting", "reconnected"]


def test_a_plain_callback_receives_only_public_events() -> None:
    events: list[object] = []
    with stub_engine() as engine:
        transport = _transport(engine)
        try:
            transport.run(candidate(), events.append)
        finally:
            transport.close()

    assert events
    assert all(isinstance(event, Event) for event in events)


# --- Runner: the bound observer forwards to the built-in output only -----------------------


class _Builtin:
    def __init__(self) -> None:
        self.seen: list[tuple[Candidate, _ConnectionNotice]] = []

    def observe(self, candidate: Candidate, event: Event) -> None:
        del candidate, event

    def connection(self, candidate: Candidate, notice: _ConnectionNotice) -> None:
        self.seen.append((candidate, notice))


def test_the_sync_bound_observer_forwards_notices_to_the_builtin_only() -> None:
    builtin, called = _Builtin(), []
    selected = candidate()
    bound = _SyncEventObserver(builtin, called.append).bind(selected)

    assert isinstance(bound, _ConnectionListener)
    bound.connection(_RECONNECTING)

    assert builtin.seen == [(selected, _RECONNECTING)]
    assert called == []  # the user callback never sees the private notice


def test_the_async_bound_observer_forwards_notices_to_the_builtin_only() -> None:
    builtin, called = _Builtin(), []
    selected = candidate()
    bound = _AsyncEventObserver(builtin, called.append).bind(selected)

    assert isinstance(bound, _ConnectionListener)
    bound.connection(_RECONNECTED)

    assert builtin.seen == [(selected, _RECONNECTED)]
    assert called == []


@pytest.mark.parametrize("builtin", [None, object()])
def test_a_bound_observer_without_a_connection_renderer_ignores_the_notice(
    builtin: object | None,
) -> None:
    called: list[Event] = []
    _SyncEventObserver(builtin, called.append).bind(candidate()).connection(_RECONNECTING)
    _AsyncEventObserver(builtin, called.append).bind(candidate()).connection(_RECONNECTING)
    assert called == []


def test_a_bound_observer_keeps_a_renderer_defect_inside_progress() -> None:
    class _Broken(_Builtin):
        def connection(self, candidate: Candidate, notice: _ConnectionNotice) -> None:
            raise RuntimeError("renderer defect")

    _SyncEventObserver(_Broken(), None).bind(candidate()).connection(_RECONNECTING)


# --- Terminal text --------------------------------------------------------------------------


def test_terminal_progress_prints_generic_reconnect_lines() -> None:
    stream = io.StringIO()
    observer = _ProgressObserver(stream)
    observer.connection(candidate(), _ConnectionNotice(state="reconnecting", attempt=1))
    observer.connection(candidate(), _ConnectionNotice(state="reconnected"))

    assert stream.getvalue().splitlines() == [
        "ScreamingFace · opus · connection lost — reconnecting (attempt 1)",
        "ScreamingFace · opus · connection restored",
    ]


# --- Notebook panel -------------------------------------------------------------------------


def _started(selected: Candidate) -> Started:
    return Started(
        id="event_1",
        run_id="run",
        sequence=1,
        timestamp=datetime.now(UTC),
        source="/trace/reconnect/node/root",
        url4=selected.url4,
    )


def _running_progress() -> tuple[_EvaluationProgress, Candidate]:
    selected = candidate()
    progress = _EvaluationProgress(candidates=(selected,), case_count=1)
    progress.begin(selected)
    progress.observe(selected, _started(selected))
    return progress, selected


def test_panel_row_shows_reconnecting_then_returns_to_its_status() -> None:
    progress, selected = _running_progress()

    progress.connection(selected, _RECONNECTING)
    row = progress.rows[0]
    assert "Reconnecting (attempt 2)" in _candidate_row_html(row, 5.0)
    assert progress.announcement == "opus reconnecting (attempt 2)"

    progress.connection(selected, _RECONNECTED)
    assert "Reconnecting" not in _candidate_row_html(row, 5.0)
    assert "Running" in _candidate_row_html(row, 5.0)
    assert progress.announcement == "opus connection restored"


def test_panel_ignores_a_notice_for_a_finished_row_and_rejects_an_unknown_candidate() -> None:
    progress, selected = _running_progress()
    progress.rows[0].terminal_status = "succeeded"

    progress.connection(selected, _RECONNECTING)
    assert "Reconnecting" not in _candidate_row_html(progress.rows[0], None)

    with pytest.raises(ValueError, match="unknown"):
        progress.connection(_other_candidate(), _RECONNECTING)


def _other_candidate() -> Candidate:
    return _compiled_candidate(
        name="other",
        kind="model",
        models=("provider/other",),
        url4="(@)!'other'",
        operations=(
            _compiled_operation(id="op_other", kind="model", label="other", depends_on=()),
        ),
    )


def test_notebook_view_renders_the_reconnect_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    selected = candidate()
    view = _NotebookEvaluationView((selected,), 1, tick=False)
    try:
        view.begin(selected)
        view.observe(selected, _started(selected))
        view.connection(selected, _RECONNECTING)
        assert "Reconnecting (attempt 2)" in view._activity_rows[0].summary.value  # noqa: SLF001
        view.connection(selected, _RECONNECTED)
        assert "Reconnecting" not in view._activity_rows[0].summary.value  # noqa: SLF001
    finally:
        view.close()

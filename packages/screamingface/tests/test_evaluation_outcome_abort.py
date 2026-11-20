"""Stopped siblings read as stopped, not failed (spec 2026-09-28 §5 items 1-3, review round 1).

FEATURE: OME-1071 — after an owner abort or a callback error, the SDK itself stops the other
Candidates: it cancels the Run (E5 P2 spec D14). They must not read as independent Candidate
failures.
STORY: as a researcher who pressed Ctrl-C (or whose `on_event` handler failed), the panel
and the terminal say the other Candidates were stopped — not that each of them failed.

The built-in progress state (`_EvaluationProgress`) and the terminal observer
(`_ProgressObserver`) are driven by the runner's follow of a scripted Run
(`_run_transport.py`); the final `abort` is the call that `evaluate_*` makes.
"""

from __future__ import annotations

import asyncio
import io
import threading
from typing import Any

import pytest
from _run_transport import AsyncScriptedRun, ScriptedRun, settled_async, settled_sync
from test_evaluation_outcome import valid_outcome
from test_live_candidate_progress import _START, candidate

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.outcome import _CandidatesFailed
from screamingface._evaluation.progress import _ProgressObserver
from screamingface._evaluation.runner import (
    _abort_event_observer,
    _AsyncEventObserver,
    _SyncEventObserver,
)
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface.errors import ExecutionError


class _CallerBug(Exception):
    pass


class _Builtin:
    """The panel state and the terminal output, both fed by the runner."""

    def __init__(self, candidates: tuple[Candidate, ...]) -> None:
        self.progress = _EvaluationProgress(candidates=candidates, case_count=1)
        self.stream = io.StringIO()
        self.terminal = _ProgressObserver(self.stream)

    def begin(self, selected: Candidate) -> None:
        self.progress.begin(selected)

    def observe(self, selected: Candidate, event: sf.Event) -> None:
        self.progress.observe(selected, event)

    def candidate_failed(self, selected: Candidate, exc: Exception) -> None:
        self.progress.candidate_failed(selected, exc)
        self.terminal.candidate_failed(selected, exc)

    def candidate_stopped(self, selected: Candidate) -> None:
        self.progress.candidate_stopped(selected)
        self.terminal.candidate_stopped(selected)

    def abort(self, exc: BaseException) -> None:
        self.progress.abort(exc)

    def status(self) -> dict[str, str]:
        return {row.candidate.name: row.status for row in self.progress.rows}


def _started(selected: Candidate) -> sf.events.Started:
    return sf.events.Started(
        id=f"started_{selected.name}",
        run_id=f"run_{selected.name}",
        sequence=1,
        timestamp=_START,
        source=f"/trace/{selected.name}",
        url4=selected.url4,
    )


def _caller_callback(name: str, raised: type[BaseException] = _CallerBug) -> Any:
    def on_event(event: sf.Event) -> None:
        if isinstance(event, sf.events.Started) and event.run_id == f"run_{name}":
            raise raised("handler failed")

    return on_event


class _SyncScene(ScriptedRun):
    """`a`'s start is shown while `b` runs, and showing it aborts (Ctrl-C lands while the
    caller's thread shows it, or the caller's callback raises); `b` ends only after the cancel."""

    def __init__(self) -> None:
        super().__init__()
        self.b_started = threading.Event()
        self.swept = threading.Event()

    def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
        if selected.name == "a":
            assert self.b_started.wait(5)
            on_event(_started(selected))  # the abort happens while this is shown
            assert self.swept.wait(5)
            raise AssertionError("unreachable")
        on_event(_started(selected))
        self.b_started.set()
        # WHY: the cancel ends this Candidate, so it settles with an ordinary error.
        assert self.swept.wait(5)
        raise ExecutionError("stream ended", code="websocket_disconnected")

    def on_cancel(self) -> None:
        self.swept.set()
        # WHY the pause: `b` fails DURING the cancel, so the flag must already be set.
        threading.Event().wait(0.05)


@pytest.mark.parametrize(
    ("abort", "raised", "a_status"),
    [("interrupt", KeyboardInterrupt, "stopped"), ("callback", _CallerBug, "run_failed")],
)
def test_swept_sibling_reads_as_stopped(
    abort: str, raised: type[BaseException], a_status: str
) -> None:
    candidates = (candidate("a"), candidate("b"))
    builtin = _Builtin(candidates)
    observer = _SyncEventObserver(builtin, _caller_callback("a", raised))

    with pytest.raises(raised) as caught:
        settled_sync(_SyncScene(), candidates, observer)
    _abort_event_observer(observer, caught.value)

    # INVARIANT: the swept sibling is `stopped`; only the Candidate that aborted may fail. Ctrl-C
    # is the owner's abort, so `a`, shown when it landed, says so too (#1982 review).
    assert builtin.status() == {"a": a_status, "b": "stopped"}
    assert "run failed" not in builtin.stream.getvalue()
    a_stopped = "ScreamingFace · a · run stopped\n" if a_status == "stopped" else ""
    assert builtin.stream.getvalue() == a_stopped + "ScreamingFace · b · run stopped\n"


def test_an_independent_failure_still_reads_as_failed_at_once() -> None:
    candidates = (candidate("a"), candidate("b"))
    builtin = _Builtin(candidates)

    class Transport(ScriptedRun):
        def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
            on_event(_started(selected))
            if selected.name == "b":
                raise ExecutionError("lost", code="websocket_disconnected")
            # WHY: `a` ends only once the panel already shows `b` as failed.
            for _ in range(500):
                if builtin.status()["b"] == "run_failed":
                    return valid_outcome(selected.name)
                threading.Event().wait(0.01)
            raise AssertionError("the failed row was not shown at once")

        def on_cancel(self) -> None:
            raise AssertionError("an independent failure sweeps nothing")

    observer = _SyncEventObserver(builtin, None)
    with pytest.raises(_CandidatesFailed):
        settled_sync(Transport(), candidates, observer)

    assert builtin.stream.getvalue() == "ScreamingFace · b · run failed (websocket_disconnected)\n"


class _AsyncScene(AsyncScriptedRun):
    """`a` aborts or waits; `b` fails while the cancel runs; `c` is held."""

    def __init__(self, abort: str) -> None:
        super().__init__()
        self.abort = abort
        self.started: set[str] = set()
        self.all_started = asyncio.Event()
        self.swept = asyncio.Event()

    async def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
        if selected.name != "a":
            await on_event(_started(selected))
        self.started.add(selected.name)
        if len(self.started) == 3:
            self.all_started.set()
        await self.all_started.wait()
        if selected.name == "a" and self.abort == "callback":
            await on_event(_started(selected))  # the caller's callback raises here
        if selected.name == "b":
            await self.swept.wait()
            raise ExecutionError("stream ended", code="websocket_disconnected")
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def on_cancel(self) -> None:
        self.swept.set()
        # WHY the pause: `b` fails DURING the cancel.
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("abort", ["cancel", "callback"])
async def test_async_swept_siblings_read_as_stopped(abort: str) -> None:
    candidates = (candidate("a"), candidate("b"), candidate("c"))
    builtin = _Builtin(candidates)
    callback = _caller_callback("a") if abort == "callback" else None
    observer = _AsyncEventObserver(builtin, callback)
    scene = _AsyncScene(abort)
    task = asyncio.create_task(settled_async(scene, candidates, observer))
    await asyncio.wait_for(scene.all_started.wait(), 5)
    if abort == "cancel":
        task.cancel()
    raised: type[BaseException] = asyncio.CancelledError if abort == "cancel" else _CallerBug

    with pytest.raises(raised) as caught:
        await task
    _abort_event_observer(observer, caught.value)

    expected_a = "stopped" if abort == "cancel" else "run_failed"
    assert builtin.status() == {"a": expected_a, "b": "stopped", "c": "stopped"}
    assert "run failed" not in builtin.stream.getvalue()


@pytest.mark.asyncio
async def test_async_an_independent_failure_still_reads_as_failed_at_once() -> None:
    candidates = (candidate("a"), candidate("b"))
    builtin = _Builtin(candidates)

    class Transport(AsyncScriptedRun):
        async def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
            await on_event(_started(selected))
            if selected.name == "b":
                raise ExecutionError("lost", code="engine_at_capacity")
            while builtin.status()["b"] != "run_failed":
                await asyncio.sleep(0.01)
            return valid_outcome(selected.name)

        async def on_cancel(self) -> None:
            raise AssertionError("an independent failure sweeps nothing")

    observer = _AsyncEventObserver(builtin, None)
    with pytest.raises(_CandidatesFailed):
        await asyncio.wait_for(settled_async(Transport(), candidates, observer), 5)

    assert builtin.stream.getvalue() == "ScreamingFace · b · run failed (engine_at_capacity)\n"


def test_a_stop_notice_leaves_unsubmitted_and_finished_rows_alone() -> None:
    fast, queued = candidate("fast"), candidate("queued")
    progress = _EvaluationProgress(candidates=(fast, queued), case_count=1)
    from test_live_candidate_progress import report_for

    progress.candidate_result(report_for(fast).candidates[0])
    progress.candidate_stopped(fast)
    progress.candidate_stopped(queued)

    assert [row.status for row in progress.rows] == ["finished", "queued"]
    with pytest.raises(ValueError, match="unknown Evaluation Candidate"):
        progress.candidate_stopped(candidate("other"))


def test_notebook_panel_shows_the_stopped_row(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from test_evaluation_outcome_runner import _fake_widgets
    from test_live_candidate_progress import _widget_text

    from screamingface._ui.evaluation_widget import _NotebookEvaluationView

    monkeypatch.setitem(sys.modules, "ipywidgets", _fake_widgets())
    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    swept, queued = candidate("swept"), candidate("queued")
    view = _NotebookEvaluationView((swept, queued), 1, "draco", tick=False)
    view.begin(swept)
    view.candidate_stopped(swept)

    # INVARIANT: the swept row reads `stopped` at once; a row never submitted is left alone.
    assert view._progress.rows[0].status == "stopped"  # noqa: SLF001
    assert view._progress.rows[1].status == "queued"  # noqa: SLF001
    assert view._progress.announcement == "swept stopped"  # noqa: SLF001
    assert "swept stopped" in _widget_text(view._html)  # noqa: SLF001
    view.close()

"""Runner, code-fallback and progress details of the Evaluation outcome (spec §5, §5.2).

FEATURE: OME-1071 / OME-1067 — one failed Candidate does not stop its siblings.
STORY: as a researcher watching the progress panel, I see a Candidate's row fail at once
while its siblings keep running; the final panel keeps both the finished and the failed rows.

The real-transport scenarios live in `test_evaluation_outcome.py`. This file pins what a
fake transport shows best: failures without a code, results that do not decode, the owner
abort of the async twin, and the progress hooks.
"""

from __future__ import annotations

import asyncio
import io
import sys
import threading
from dataclasses import replace
from typing import Any, cast

import httpx
import pytest
from test_client_run import _engine as _catalog_engine
from test_evaluation_outcome import valid_outcome
from test_live_candidate_progress import _fake_widgets, candidate, report_for

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.outcome import _CandidatesFailed, _Failed, failure_code
from screamingface._evaluation.progress import _ProgressObserver
from screamingface._evaluation.runner import (
    _AsyncEventObserver,
    _run_candidates_async,
    _run_candidates_sync,
    _SyncEventObserver,
)
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface.errors import ExecutionError

# --- failures without a code, and results that do not decode ----------------------------


def _scripted(name: str) -> _RunOutcome:
    if name == "boom":
        raise RuntimeError("a defect outside the SDK's error classes")
    if name == "garbled":
        return replace(valid_outcome(name), result_body="not json")
    return valid_outcome(name)


class _SyncScripted:
    def __init__(self) -> None:
        self.cancel_calls = 0

    def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
        return _scripted(selected.name)

    def cancel_active(self) -> None:
        self.cancel_calls += 1

    def close(self) -> None:
        pass


class _AsyncScripted:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
        return _scripted(selected.name)

    async def cancel_active(self) -> None:
        self.cancel_calls += 1

    async def close(self) -> None:
        pass


_SCRIPTED = [sf.Model("provider/opus", name=name) for name in ("ok", "boom", "garbled")]


def _assert_scripted(error: ExecutionError) -> None:
    failed = cast(dict[str, dict[str, str]], error.details)["failed"]
    # INVARIANT (spec §5 item 5): a failure without a code gets the stable fallback, and a
    # Run whose result does not decode is a failed Candidate (spec §5.2), in Candidate order.
    assert list(failed.items()) == [("boom", "unexpected_error"), ("garbled", "execution_failed")]
    assert isinstance(error.__cause__, RuntimeError)
    assert error.partial_report is not None
    assert [result.name for result in error.partial_report.candidates] == ["ok"]


def test_failures_without_a_code_and_undecodable_results_are_named() -> None:
    transport = _SyncScripted()
    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=httpx.MockTransport(_catalog_engine),
            run_transport=cast(Any, transport),
        ) as client,
        pytest.raises(ExecutionError) as caught,
    ):
        client.evaluate(_SCRIPTED, benchmark="draco", progress=False)

    _assert_scripted(caught.value)
    assert transport.cancel_calls == 0


@pytest.mark.asyncio
async def test_async_failures_without_a_code_and_undecodable_results_are_named() -> None:
    transport = _AsyncScripted()
    async with sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_catalog_engine),
        run_transport=cast(Any, transport),
    ) as client:
        with pytest.raises(ExecutionError) as caught:
            await client.evaluate(_SCRIPTED, benchmark="draco", progress=False)

    _assert_scripted(caught.value)
    assert transport.cancel_calls == 0


def test_failure_code_uses_the_sdk_code_or_the_stable_fallback() -> None:
    assert failure_code(ExecutionError("lost", code="websocket_disconnected")) == (
        "websocket_disconnected"
    )
    assert failure_code(sf.AuthenticationError("no")) == "authentication_failed"
    assert failure_code(ValueError("x")) == "unexpected_error"


# --- C1b at the runner: siblings run to their end, nothing is swept ----------------------


def test_an_ordinary_failure_waits_for_the_sibling_and_sweeps_nothing() -> None:
    failed = threading.Event()
    slow, broken = candidate("slow"), candidate("broken")

    class Transport:
        cancel_calls = 0

        def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            if selected == broken:
                failed.set()
                raise ExecutionError("lost", code="websocket_disconnected")
            # The sibling is still running when its neighbour has failed.
            assert failed.wait(5)
            return valid_outcome(selected.name)

        def cancel_active(self) -> None:
            Transport.cancel_calls += 1

    with pytest.raises(_CandidatesFailed) as caught:
        _run_candidates_sync(cast(Any, Transport()), (slow, broken), None)

    (first, first_outcome), (second, second_outcome) = caught.value.settled
    assert (first, first_outcome) == (slow, valid_outcome("slow"))
    assert second == broken
    assert isinstance(second_outcome, _Failed)
    assert Transport.cancel_calls == 0


@pytest.mark.asyncio
async def test_async_an_ordinary_failure_waits_for_the_sibling_and_sweeps_nothing() -> None:
    failed = asyncio.Event()
    slow, broken = candidate("slow"), candidate("broken")

    class Transport:
        cancel_calls = 0

        async def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            if selected == broken:
                failed.set()
                raise ExecutionError("lost", code="websocket_disconnected")
            await asyncio.wait_for(failed.wait(), 5)
            return valid_outcome(selected.name)

        async def cancel_active(self) -> None:
            Transport.cancel_calls += 1

    with pytest.raises(_CandidatesFailed) as caught:
        await _run_candidates_async(cast(Any, Transport()), (slow, broken), None)

    assert caught.value.settled[0] == (slow, valid_outcome("slow"))
    assert isinstance(caught.value.settled[1][1], _Failed)
    assert Transport.cancel_calls == 0


# --- C1a at the async runner: an outer cancellation sweeps once and keeps the note -------


@pytest.mark.asyncio
async def test_async_owner_abort_sweeps_once_and_records_a_rejected_stop() -> None:
    # INVARIANT (spec §5 item 1): the owner abort still stops everything; a failed sweep is a
    # note on the interruption, never a replacement of it.
    started = 0
    both = asyncio.Event()

    class Transport:
        cancel_calls = 0

        async def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            nonlocal started
            started += 1
            if started == 2:
                both.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def cancel_active(self) -> None:
            Transport.cancel_calls += 1
            raise RuntimeError("DELETE / failed with 401")

    task = asyncio.create_task(
        _run_candidates_async(cast(Any, Transport()), (candidate("a"), candidate("b")), None)
    )
    await asyncio.wait_for(both.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task

    assert Transport.cancel_calls == 1
    assert any(
        "Stopping active SF Engine runs also failed" in note
        for note in getattr(caught.value, "__notes__", ())
    )
    assert [other for other in asyncio.all_tasks() if other is not asyncio.current_task()] == []


# --- the caller-callback tag ---------------------------------------------------------------


def test_only_the_recorded_callback_exception_counts_as_the_callers() -> None:
    # INVARIANT (spec §5.1): identity, not type or equality — a Candidate failure of the
    # same class is never taken for the caller's exception.
    raised = ValueError("caller")

    def on_event(event: sf.Event) -> None:
        raise raised

    observer = _SyncEventObserver(None, on_event)
    bound = observer.bind(candidate("a"))
    with pytest.raises(ValueError):
        bound(cast(Any, object()))

    assert observer.raised_by_caller(raised) is True
    assert observer.raised_by_caller(ValueError("caller")) is False


@pytest.mark.asyncio
async def test_async_only_the_recorded_callback_exception_counts_as_the_callers() -> None:
    raised = ValueError("caller")

    async def on_event(event: sf.Event) -> None:
        raise raised

    observer = _AsyncEventObserver(None, on_event)
    bound = observer.bind(candidate("a"))
    with pytest.raises(ValueError):
        await bound(cast(Any, object()))

    assert observer.raised_by_caller(raised) is True
    assert observer.raised_by_caller(ValueError("caller")) is False


# --- progress: the failed row shows at once --------------------------------------------------


class _Builtin:
    def __init__(self) -> None:
        self.failed: list[tuple[str, str]] = []
        self.seen = threading.Event()

    def begin(self, selected: Candidate) -> None:
        pass

    def observe(self, selected: Candidate, event: sf.Event) -> None:
        pass

    def candidate_failed(self, selected: Candidate, exc: BaseException) -> None:
        self.failed.append((selected.name, failure_code(exc)))
        self.seen.set()


def test_the_failed_row_is_shown_while_the_sibling_still_runs() -> None:
    builtin = _Builtin()
    slow, broken = candidate("slow"), candidate("broken")

    class Transport:
        def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            if selected == broken:
                raise ExecutionError("lost", code="websocket_disconnected")
            # WHY: this Run ends only after the progress output has shown the failure.
            assert builtin.seen.wait(5)
            return valid_outcome(selected.name)

    with pytest.raises(_CandidatesFailed):
        _run_candidates_sync(
            cast(Any, Transport()), (slow, broken), _SyncEventObserver(builtin, None)
        )

    assert builtin.failed == [("broken", "websocket_disconnected")]


@pytest.mark.asyncio
async def test_async_the_failed_row_is_shown_while_the_sibling_still_runs() -> None:
    builtin = _Builtin()
    slow, broken = candidate("slow"), candidate("broken")

    class Transport:
        async def run(self, selected: Candidate, on_event: object) -> _RunOutcome:
            if selected == broken:
                raise ExecutionError("lost", code="engine_at_capacity")
            while not builtin.seen.is_set():
                await asyncio.sleep(0.01)
            return valid_outcome(selected.name)

    with pytest.raises(_CandidatesFailed):
        await asyncio.wait_for(
            _run_candidates_async(
                cast(Any, Transport()), (slow, broken), _AsyncEventObserver(builtin, None)
            ),
            5,
        )

    assert builtin.failed == [("broken", "engine_at_capacity")]


def test_terminal_progress_names_the_failed_candidate_and_its_code() -> None:
    stream = io.StringIO()
    _ProgressObserver(stream).candidate_failed(
        candidate("broken"), ExecutionError("lost", code="websocket_disconnected")
    )
    assert stream.getvalue() == "ScreamingFace · broken · run failed (websocket_disconnected)\n"


def test_panel_state_keeps_finished_and_failed_rows_after_the_final_abort() -> None:
    fast, broken, queued = candidate("fast"), candidate("broken"), candidate("queued")
    progress = _EvaluationProgress(candidates=(fast, broken, queued), case_count=1)
    progress.begin(broken)
    progress.candidate_failed(broken, ExecutionError("lost", code="websocket_disconnected"))
    assert progress.rows[1].status == "run_failed"
    assert progress.announcement == "broken run failed"
    # A late failure notice for a finished row must not relabel it.
    progress.candidate_result(report_for(fast).candidates[0])
    progress.candidate_failed(fast, ExecutionError("late"))
    assert progress.rows[0].status == "finished"

    final = ExecutionError("1 of 3 Candidates failed: broken (websocket_disconnected)")
    progress.abort(final)

    assert [row.status for row in progress.rows] == ["finished", "run_failed", "not_run"]
    assert progress.error == final.message


def test_panel_state_refuses_an_unknown_candidate() -> None:
    progress = _EvaluationProgress(candidates=(candidate("a"),), case_count=1)
    with pytest.raises(ValueError, match="unknown Evaluation Candidate"):
        progress.candidate_failed(candidate("b"), ExecutionError("x"))


def test_notebook_panel_shows_the_failed_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_live_candidate_progress import _widget_text

    from screamingface._ui.evaluation_widget import _NotebookEvaluationView

    monkeypatch.setitem(sys.modules, "ipywidgets", _fake_widgets())
    monkeypatch.setattr(_NotebookEvaluationView, "_show", lambda self: None)
    slow, broken = candidate("slow"), candidate("broken")
    view = _NotebookEvaluationView((slow, broken), 1, "draco", tick=False)
    view.begin(broken)
    view.candidate_failed(broken, ExecutionError("lost", code="websocket_disconnected"))

    assert view._progress.rows[1].status == "run_failed"  # noqa: SLF001
    assert view._progress.rows[0].status == "queued"  # noqa: SLF001
    assert view._progress.announcement == "broken run failed"  # noqa: SLF001
    assert "broken run failed" in _widget_text(view._html)  # noqa: SLF001
    view.close()

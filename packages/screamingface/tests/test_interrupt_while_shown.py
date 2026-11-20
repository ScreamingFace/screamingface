"""An interrupt that lands while a Candidate is shown stops that Candidate too (#1982 review).

FEATURE: OME-1071 on the follow (E5 P2 spec D14). The follow shows each Candidate's events on the
caller's thread, so Ctrl-C or a cancelled task often lands while one Candidate's progress line or
async `on_event` runs. That is the owner's abort, not that Candidate's own error: it reads
`stopped` like the rest, never `run_failed`, and the terminal says so.
STORY: as a researcher who pressed Ctrl-C, every Candidate that was running says "run stopped",
whichever one happened to be on screen.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _run_transport import AsyncScriptedRun, settled_async, settled_sync
from test_evaluation_outcome_abort import _Builtin, _started, _SyncScene
from test_live_candidate_progress import candidate

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.runner import (
    _abort_event_observer,
    _AsyncEventObserver,
    _SyncEventObserver,
)

_STOPPED = "ScreamingFace · a · run stopped\nScreamingFace · b · run stopped\n"


class _InterruptedWhileShowingA(_Builtin):
    """The progress output, interrupted by Ctrl-C while it writes `a`'s start."""

    def observe(self, selected: Candidate, event: sf.Event) -> None:
        if selected.name == "a" and isinstance(event, sf.events.Started):
            raise KeyboardInterrupt
        super().observe(selected, event)


def test_ctrl_c_while_a_line_is_shown_stops_that_candidate_too() -> None:
    candidates = (candidate("a"), candidate("b"))
    builtin = _InterruptedWhileShowingA(candidates)
    observer = _SyncEventObserver(builtin, None)

    with pytest.raises(KeyboardInterrupt) as caught:
        settled_sync(_SyncScene(), candidates, observer)
    _abort_event_observer(observer, caught.value)

    assert builtin.status() == {"a": "stopped", "b": "stopped"}
    assert builtin.stream.getvalue() == _STOPPED


class _AsyncScene(AsyncScriptedRun):
    """`b` starts, then `a`, and both are held; the caller's `on_event` for `a`'s start awaits."""

    def __init__(self) -> None:
        super().__init__()
        self.b_started = asyncio.Event()

    async def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
        if selected.name == "a":
            await self.b_started.wait()
        await on_event(_started(selected))
        self.b_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_a_task_cancelled_while_on_event_awaits_stops_that_candidate_too() -> None:
    candidates = (candidate("a"), candidate("b"))
    builtin = _Builtin(candidates)
    awaiting = asyncio.Event()

    async def on_event(event: sf.Event) -> None:
        if isinstance(event, sf.events.Started) and event.run_id == "run_a":
            awaiting.set()
            await asyncio.Event().wait()

    observer = _AsyncEventObserver(builtin, on_event)
    task = asyncio.create_task(settled_async(_AsyncScene(), candidates, observer))
    await asyncio.wait_for(awaiting.wait(), 5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    _abort_event_observer(observer, caught.value)

    assert builtin.status() == {"a": "stopped", "b": "stopped"}
    assert builtin.stream.getvalue() == _STOPPED

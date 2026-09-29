"""A cancelled Candidate task aborts the Evaluation at once (spec 2026-09-28 §4.1 C1a/C1c).

FEATURE: OME-1071 — review finding on #1121. `asyncio.wait(..., FIRST_EXCEPTION)` does not
wake when a child task is CANCELLED (only for a task that ended with an exception). A caller
`on_event` that raises `asyncio.CancelledError`, or a Run that ends cancelled on its own, left
the Evaluation waiting for its siblings: they kept spending, and one held sibling kept the
Evaluation from returning. The spec says both are an abort: stop everything, at once.
STORY: as a researcher whose async `on_event` handler was cancelled, the other Runs are
stopped immediately — they do not keep spending until each of them ends by itself.

Every scene HOLDS its siblings until the sweep. A wait that never wakes therefore shows up as
a timeout here, never as a pass.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, cast

import pytest
from test_evaluation_outcome_abort import _AsyncScene, _Builtin, _started
from test_live_candidate_progress import candidate

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.runner import (
    _abort_event_observer,
    _AsyncEventObserver,
    _run_candidates_async,
    _run_candidates_sync,
    _SyncEventObserver,
)
from screamingface.errors import ExecutionError

_LIMIT_S = 5


def _callback_raising(exc_type: type[BaseException]) -> Any:
    def on_event(event: sf.Event) -> None:
        if isinstance(event, sf.events.Started) and event.run_id == "run_a":
            raise exc_type("handler stopped")

    return on_event


@pytest.mark.asyncio
async def test_async_a_cancelled_callback_aborts_the_evaluation_at_once() -> None:
    candidates = (candidate("a"), candidate("b"), candidate("c"))
    builtin = _Builtin(candidates)
    observer = _AsyncEventObserver(builtin, _callback_raising(asyncio.CancelledError))
    scene = _AsyncScene("callback")

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(
            _run_candidates_async(cast(Any, scene), candidates, observer), _LIMIT_S
        )
    _abort_event_observer(observer, caught.value)

    # INVARIANT: the owner sweep ran BEFORE the siblings were cancelled, and both siblings
    # read as stopped — not running, and not failed.
    assert scene.swept.is_set()
    assert builtin.status()["b"] == "stopped"
    assert builtin.status()["c"] == "stopped"
    assert "run failed" not in builtin.stream.getvalue()


@pytest.mark.asyncio
async def test_async_a_run_that_ends_cancelled_by_itself_aborts_the_evaluation() -> None:
    candidates = (candidate("a"), candidate("b"))
    builtin = _Builtin(candidates)
    swept = asyncio.Event()

    class Transport:
        async def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
            await on_event(_started(selected))
            if selected.name == "a":
                await asyncio.sleep(0)
                raise asyncio.CancelledError  # cancelled from inside, not by the abort arm
            await asyncio.Event().wait()  # `b` is held until it is cancelled
            raise AssertionError("unreachable")

        async def cancel_active(self) -> None:
            swept.set()

    observer = _AsyncEventObserver(builtin, None)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(
            _run_candidates_async(cast(Any, Transport()), candidates, observer), _LIMIT_S
        )

    assert swept.is_set()
    assert builtin.status()["b"] == "stopped"


class _SyncScene:
    """`a` aborts through its callback; `b` is held until the sweep ends its stream."""

    def __init__(self) -> None:
        self.b_started = threading.Event()
        self.swept = threading.Event()

    def run(self, selected: Candidate, on_event: Any) -> _RunOutcome:
        if selected.name == "a":
            assert self.b_started.wait(_LIMIT_S)
            on_event(_started(selected))  # the caller's callback raises here
            raise AssertionError("unreachable")
        on_event(_started(selected))
        self.b_started.set()
        assert self.swept.wait(_LIMIT_S)
        raise ExecutionError("stream ended", code="websocket_disconnected")

    def cancel_active(self) -> None:
        self.swept.set()
        threading.Event().wait(0.05)  # `b` fails DURING the sweep


@pytest.mark.parametrize("raised", [KeyboardInterrupt, SystemExit])
def test_sync_a_callback_that_raises_a_base_exception_aborts_at_once(
    raised: type[BaseException],
) -> None:
    # PIN, not a fix: a worker thread stores any BaseException on its future, so the sync
    # twin's wait wakes at once. The async twin needed a fix; this keeps the twins equal.
    candidates = (candidate("a"), candidate("b"))
    builtin = _Builtin(candidates)
    scene = _SyncScene()
    observer = _SyncEventObserver(builtin, _callback_raising(raised))

    with pytest.raises(raised) as caught:
        _run_candidates_sync(cast(Any, scene), candidates, observer)
    _abort_event_observer(observer, caught.value)

    assert scene.swept.is_set()
    assert builtin.status()["b"] == "stopped"
    assert "run failed" not in builtin.stream.getvalue()

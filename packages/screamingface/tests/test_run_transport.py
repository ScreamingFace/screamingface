"""The follow-a-Run fake the Client's tests build on (`_run_transport.py`, E5 P2 plan CP1).

FEATURE: a detached Run (OME-1837). The Client has one transport port: it registers a Run with
every Candidate's start and follows it, and the Engine runs the Candidates. A test scripts each
Candidate as one function (return an outcome, raise, emit events, wait for a signal); the fake
plays every script as the Engine would and reports what happens, by index, on the caller's
thread, in the order the scripts make it happen.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from _run_transport import RUN_ID, AsyncPlaying, AsyncScriptedRun, ScriptedRun

from screamingface import events
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.model import Candidate, _compiled_candidate, _compiled_operation

_AT = datetime(2026, 11, 20, tzinfo=UTC)


def _candidate(name: str) -> Candidate:
    operation = _compiled_operation(id=f"op_{name}", kind="model", label=name, depends_on=())
    return _compiled_candidate(
        name=name,
        kind="model",
        models=(f"provider/{name}",),
        url4=f"(@)!'{name}'",
        operations=(operation,),
    )


def _outcome(name: str) -> _RunOutcome:
    return _RunOutcome(
        run_id=f"run_{name}",
        started_at=_AT,
        completed_at=_AT,
        result_body="{}",
        media_type="application/json",
        root_usage=None,
    )


def _log(name: str) -> events.Log:
    return events.Log(
        id=f"log_{name}",
        run_id=f"run_{name}",
        sequence=1,
        timestamp=_AT,
        source=f"/trace/{name}",
        severity_number=9,
        severity_text="INFO",
        body=name,
        attributes={},
    )


class _Sink:
    """Records every call, and the thread it came on."""

    shows_events = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []
        self.threads: set[int] = set()

    def state(self, index: int, state: str) -> None:
        self._seen(("state", index, state))

    def event(self, index: int, event: events.Event) -> None:
        assert isinstance(event, events.Log)
        self._seen(("event", index, event.body))

    def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None:
        detail = outcome.run_id if isinstance(outcome, _RunOutcome) else str(outcome)
        self._seen(("settled", index, f"{state}:{detail}"))

    def connection(self, notice: Any) -> None:
        raise AssertionError("no connection notice is scripted")

    def quiet(self) -> None:
        pass

    def _seen(self, call: tuple[str, int, str]) -> None:
        self.threads.add(threading.get_ident())
        self.calls.append(call)


class _AsyncSink(_Sink):
    async def state(self, index: int, state: str) -> None:  # type: ignore[override]
        super().state(index, state)

    async def event(self, index: int, event: events.Event) -> None:  # type: ignore[override]
        super().event(index, event)

    async def settled(  # type: ignore[override]
        self, index: int, state: str, outcome: _RunOutcome | Exception
    ) -> None:
        super().settled(index, state, outcome)


class _Scene(ScriptedRun):
    """`slow` waits until `fast` has settled; `broken` raises; each emits one event first."""

    def __init__(self, sink: _Sink) -> None:
        super().__init__()
        self.sink = sink
        self.script_threads: set[int] = set()

    def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
        self.script_threads.add(threading.get_ident())
        on_event(_log(candidate.name))
        if candidate.name == "slow":
            for _ in range(500):
                if ("settled", 1, "succeeded:run_fast") in self.sink.calls:
                    return _outcome("slow")
                threading.Event().wait(0.01)
            raise AssertionError("fast never settled first")
        if candidate.name == "broken":
            raise RuntimeError("boom")
        return _outcome(candidate.name)


def test_the_run_is_registered_once_with_every_candidate() -> None:
    fake = _Scene(_Sink())

    assert fake.register_run(None, (_candidate("slow"), _candidate("fast"))) == RUN_ID
    assert fake.registered == [("slow", "fast")]


def test_candidates_settle_in_the_scripted_order_on_the_callers_thread() -> None:
    sink = _Sink()
    fake = _Scene(sink)
    candidates = (_candidate("slow"), _candidate("fast"), _candidate("broken"))

    fake.follow_run(RUN_ID, candidates, sink)

    settled = [call for call in sink.calls if call[0] == "settled"]
    assert settled.index(("settled", 1, "succeeded:run_fast")) < settled.index(
        ("settled", 0, "succeeded:run_slow")
    )
    assert ("settled", 2, "failed:boom") in settled
    # Each Candidate starts, shows its event, then settles, in that order.
    for index, name in enumerate(("slow", "fast", "broken")):
        mine = [call for call in sink.calls if call[1] == index]
        assert [call[0] for call in mine] == ["state", "event", "settled"]
        assert mine[0] == ("state", index, "running")
        assert mine[1] == ("event", index, name)
    # INVARIANT: the Client starts no Candidate; it follows on its own thread.
    assert sink.threads == {threading.get_ident()}
    assert threading.get_ident() not in fake.script_threads


def test_a_sink_that_shows_no_events_gets_none_to_emit_through() -> None:
    seen: list[object] = []

    class Quiet(ScriptedRun):
        def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
            seen.append(on_event)
            return _outcome(candidate.name)

    sink = _Sink()
    sink.shows_events = False
    Quiet().follow_run(RUN_ID, (_candidate("a"),), sink)

    assert seen == [None]


def test_an_interruption_in_a_script_is_raised_on_the_follow_and_cancel_stops_the_rest() -> None:
    released = threading.Event()

    class Interrupted(ScriptedRun):
        def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
            if candidate.name == "a":
                raise KeyboardInterrupt
            assert released.wait(5)
            raise AssertionError("released by the cancel")

        def on_cancel(self) -> None:
            released.set()

    fake = Interrupted()
    with pytest.raises(KeyboardInterrupt):
        fake.follow_run(RUN_ID, (_candidate("a"), _candidate("b")), _Sink())
    fake.cancel_run(RUN_ID)

    assert fake.canceled == [RUN_ID]
    assert released.is_set()


class _AsyncScene(AsyncScriptedRun):
    def __init__(self, sink: _Sink) -> None:
        super().__init__()
        self.sink = sink

    async def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
        await on_event(_log(candidate.name))
        if candidate.name == "slow":
            while ("settled", 1, "succeeded:run_fast") not in self.sink.calls:
                await asyncio.sleep(0.01)
        if candidate.name == "broken":
            raise RuntimeError("boom")
        return _outcome(candidate.name)


@pytest.mark.asyncio
async def test_async_candidates_settle_in_the_scripted_order() -> None:
    sink = _AsyncSink()
    fake = _AsyncScene(sink)
    candidates = (_candidate("slow"), _candidate("fast"), _candidate("broken"))

    assert await fake.register_run(None, candidates) == RUN_ID
    await asyncio.wait_for(fake.follow_run(RUN_ID, candidates, sink), 5)

    settled = [call for call in sink.calls if call[0] == "settled"]
    assert settled.index(("settled", 1, "succeeded:run_fast")) < settled.index(
        ("settled", 0, "succeeded:run_slow")
    )
    assert ("settled", 2, "failed:boom") in settled
    assert fake.registered == [("slow", "fast", "broken")]


@pytest.mark.asyncio
async def test_async_a_follow_that_is_cancelled_leaves_no_script_running() -> None:
    started = asyncio.Event()

    class Held(AsyncScriptedRun):
        async def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    follow = asyncio.create_task(Held().follow_run(RUN_ID, (_candidate("a"),), _AsyncSink()))
    await asyncio.wait_for(started.wait(), 5)
    follow.cancel()
    with pytest.raises(asyncio.CancelledError):
        await follow

    assert [task for task in asyncio.all_tasks() if task is not asyncio.current_task()] == []


@pytest.mark.asyncio
async def test_async_plays_a_sync_fakes_script_and_reads_what_it_recorded() -> None:
    sink = _AsyncSink()
    played = AsyncPlaying(_Scene(sink))
    candidates = (_candidate("fast"),)

    await asyncio.wait_for(played.follow_run(RUN_ID, candidates, sink), 5)
    await played.cancel_run(RUN_ID)

    assert sink.calls == [
        ("state", 0, "running"),
        ("event", 0, "fast"),
        ("settled", 0, "succeeded:run_fast"),
    ]
    assert played.script_threads == {threading.get_ident()}
    assert played.canceled == [RUN_ID]

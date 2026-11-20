"""A follow-a-Run fake built from a scripted per-Candidate function (E5 P2 plan, CP1).

FEATURE: a detached Run (OME-1837). The Client's one transport port registers a Run with every
Candidate's start and follows it; the Engine runs the Candidates, and the Client starts none.
A test subclasses `ScriptedRun` (or `AsyncScriptedRun`) and writes `run`, the script
of one Candidate as the Engine runs it: return an outcome, raise, emit events through
`on_event`, or wait for a signal. `AsyncPlaying` plays a `ScriptedRun`'s script on the event loop,
so an async test reuses a sync fake. The fake plays every script at once, as the Engine's driver
would, and reports to the follow's sink, by index and on the caller's thread, in the order the
scripts make things happen: a script that waits lets its sibling settle first.

- A script that raises an `Exception` settles its Candidate `failed` with it.
- A script that raises any other `BaseException` (a `KeyboardInterrupt`, a `CancelledError`)
  interrupts the follow: it is raised on the caller's thread, where Ctrl-C lands.
- `on_event` is None when the sink shows no events, as the real follow then asks the Run's
  stream to leave them out.
- `cancel_run` records the Run and calls `on_cancel`, where a scene releases what it holds.
- The async fake plays a synchronous script too, and its `on_event` may be awaited or not.

`settled_sync` / `settled_async` drive the runner's own follow of such a Run, for the tests that
pin what the runner does with Candidates that settle, without a whole evaluation.
"""

from __future__ import annotations

import asyncio
import inspect
import queue
import threading
from collections.abc import Awaitable, Callable, Generator
from typing import Any

from screamingface._core.ports import _AsyncRunSink, _RunOutcome, _RunSink
from screamingface._evaluation.following import followed_async, followed_sync
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface._evaluation.outcome import settle
from screamingface._evaluation.reattach import refetched_async, settled_from_records
from screamingface.events import Event

RUN_ID = "run_scripted"
# WHY a timeout on each wait: a follow blocked on a queue must still see Ctrl-C (SIGINT).
_POLL_S = 0.05

type _Frame = tuple[str, int, Any]


class _Relay:
    """The `on_event` a script emits through: each event goes on the Run's stream for its
    Candidate, in the order the script emits it."""

    def __init__(self, put: Callable[[_Frame], object], index: int) -> None:
        self._put = put
        self._index = index

    def __call__(self, event: Event) -> None:
        self._put(("event", self._index, event))


class _Emitted:
    """What an async script's `on_event` returns: already done, so awaiting it is optional."""

    def __await__(self) -> Generator[None]:
        return
        yield


class _AsyncRelay(_Relay):
    def __call__(self, event: Event) -> _Emitted:  # type: ignore[override]
        super().__call__(event)
        return _Emitted()


class ScriptedRun:
    """The synchronous fake: each script runs on a thread of its own, as on the Engine."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, ...]] = []
        self.canceled: list[str] = []

    def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
        raise NotImplementedError

    def on_cancel(self) -> None:
        """The Engine stops the Run's Candidates; a scene releases what its scripts wait on."""

    def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str:
        self.registered.append(tuple(candidate.name for candidate in candidates))
        return RUN_ID

    def follow_run(self, run_id: str, candidates: tuple[Candidate, ...], sink: _RunSink) -> None:
        frames: queue.SimpleQueue[_Frame] = queue.SimpleQueue()
        shows = getattr(sink, "shows_events", True)

        def play(index: int, candidate: Candidate) -> None:
            frames.put(("state", index, "running"))
            try:
                relay = _Relay(frames.put, index) if shows else None
                outcome = self.run(candidate, relay)
            except Exception as exc:  # noqa: BLE001 - the Candidate's own failure
                frames.put(("settled", index, ("failed", exc)))
            except BaseException as exc:  # noqa: BLE001 - raised on the follow below
                frames.put(("interrupt", index, exc))
            else:
                frames.put(("settled", index, ("succeeded", outcome)))

        for index, candidate in enumerate(candidates):
            threading.Thread(
                target=play, args=(index, candidate), daemon=True, name=f"engine-{candidate.name}"
            ).start()
        left = len(candidates)
        while left:
            kind, index, value = _next(frames)
            left -= _deliver_sync(sink, kind, index, value)

    def cancel_run(self, run_id: str) -> None:
        self.canceled.append(run_id)
        self.on_cancel()

    def close(self) -> None:
        pass


def _next(frames: queue.SimpleQueue[_Frame]) -> _Frame:
    while True:
        try:
            return frames.get(timeout=_POLL_S)
        except queue.Empty:
            continue


def _deliver_sync(sink: _RunSink, kind: str, index: int, value: Any) -> int:
    """Hand one frame to the sink; 1 when it settled a Candidate."""
    if kind == "interrupt":
        raise value
    if kind == "state":
        sink.state(index, value)
    elif kind == "event":
        sink.event(index, value)
    else:
        state, outcome = value
        sink.settled(index, state, outcome)
        return 1
    return 0


class AsyncScriptedRun:
    """The asynchronous fake: each script runs as a task of its own on the caller's loop."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, ...]] = []
        self.canceled: list[str] = []

    def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome | Awaitable[_RunOutcome]:
        raise NotImplementedError

    def on_cancel(self) -> None | Awaitable[None]:
        """The async twin of `ScriptedRun.on_cancel`."""

    async def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str:
        self.registered.append(tuple(candidate.name for candidate in candidates))
        return RUN_ID

    async def follow_run(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _AsyncRunSink
    ) -> None:
        stream = _AsyncStream(self.run, getattr(sink, "shows_events", True))
        plays = [asyncio.create_task(stream.play(i, c)) for i, c in enumerate(candidates)]
        try:
            left = len(candidates)
            while left:
                kind, index, value = await stream.frames.get()
                left -= await _deliver_async(sink, kind, index, value)
        finally:
            # WHY: nobody follows the Run after this, so no script is left running on the loop.
            stream.ending = True
            for task in plays:
                task.cancel()
            await asyncio.gather(*plays, return_exceptions=True)

    async def cancel_run(self, run_id: str) -> None:
        self.canceled.append(run_id)
        await _settled(self.on_cancel())

    async def close(self) -> None:
        pass


class _AsyncStream:
    """The async Run's stream: each script's frames, in the order its task makes them."""

    def __init__(
        self, script: Callable[[Candidate, Any], _RunOutcome | Awaitable[_RunOutcome]], shows: bool
    ) -> None:
        self.frames: asyncio.Queue[_Frame] = asyncio.Queue()
        self.ending = False
        self._script = script
        self._shows = shows

    async def play(self, index: int, candidate: Candidate) -> None:
        put = self.frames.put_nowait
        put(("state", index, "running"))
        try:
            relay = _AsyncRelay(put, index) if self._shows else None
            outcome = await _settled(self._script(candidate, relay))
        except asyncio.CancelledError as exc:
            if not self.ending:  # cancelled from inside the script, not by the follow's end
                put(("interrupt", index, exc))
            raise
        except Exception as exc:  # noqa: BLE001 - the Candidate's own failure
            put(("settled", index, ("failed", exc)))
        except BaseException as exc:  # noqa: BLE001 - raised on the follow below
            put(("interrupt", index, exc))
        else:
            put(("settled", index, ("succeeded", outcome)))


async def _deliver_async(sink: _AsyncRunSink, kind: str, index: int, value: Any) -> int:
    if kind == "interrupt":
        raise value
    delivered: Awaitable[None]
    if kind == "state":
        delivered = sink.state(index, value)
    elif kind == "event":
        delivered = sink.event(index, value)
    else:
        state, outcome = value
        await sink.settled(index, state, outcome)
        return 1
    await delivered
    return 0


async def _settled[T](value: T | Awaitable[T]) -> T:
    """``value``, awaited when a script or hook gave an awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value


class AsyncPlaying(AsyncScriptedRun):
    """Plays a synchronous fake's script on the event loop; every other attribute (what the
    fake recorded) is read through to it."""

    def __init__(self, scripted: ScriptedRun) -> None:
        super().__init__()
        self.scripted = scripted

    def run(self, candidate: Candidate, on_event: Any) -> _RunOutcome:
        return self.scripted.run(candidate, on_event)

    def on_cancel(self) -> None:
        self.scripted.on_cancel()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.scripted, name)


def settled_sync(
    transport: ScriptedRun,
    candidates: tuple[Candidate, ...],
    observer: Any,
    on_complete: Callable[[Candidate, _RunOutcome], None] | None = None,
) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    """The runner's follow of the Run, settled in the Candidates' order. Raises the lone
    Candidate's own error, or `_CandidatesFailed` when one of several failed."""
    recorded, kept = followed_sync(transport, RUN_ID, candidates, observer, on_complete)
    return settle(settled_from_records(transport, candidates, recorded, kept))


async def settled_async(
    transport: AsyncScriptedRun,
    candidates: tuple[Candidate, ...],
    observer: Any,
    on_complete: Callable[[Candidate, _RunOutcome], None] | None = None,
) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    """The async twin of `settled_sync`."""
    recorded, kept = await followed_async(transport, RUN_ID, candidates, observer, on_complete)
    recorded, kept = await refetched_async(transport, candidates, recorded, kept)
    return settle(settled_from_records(transport, candidates, recorded, kept))

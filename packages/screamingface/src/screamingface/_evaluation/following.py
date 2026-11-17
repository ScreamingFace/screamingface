"""The runner's follow path: the Engine drives the Run, the Client follows it (E5 P2 spec D1,
D13, D14).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my evaluation reads the same as
before: results in the order I gave the Candidates, a failed Candidate named while its siblings
finish, and Ctrl-C stops what I started, though my notebook now starts nothing itself.

The transport follows the Run's one stream, on the caller's thread, and reports each Candidate's
state, events and outcome here, by index, with its result already fetched and kept. This module
drives the progress output, the live score and `on_event` from them, as the per-Candidate path
did. The Report is not built here: once the Run has ended, `reattach.settled_from_records`
builds it, reusing the results kept here (D14).

INVARIANT (D14): Ctrl-C, a cancelled task, the caller's own `on_event` or a defect cancels the
Run once. A follow that ends on its own (an expired sign-in, a connection it could not get back,
a Run that is gone) leaves the Run to the Engine, which is what D15 tells the user.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any

from screamingface._core.ports import (
    CANDIDATE_ENDED,
    _AsyncRunFollowing,
    _ConnectionNotice,
    _RunFollowing,
    _RunOutcome,
    recorded_of,
)
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.outcome import _Failed, _Settled
from screamingface.errors import ExecutionError, ScreamingFaceError
from screamingface.events import Event

if TYPE_CHECKING:
    from screamingface._evaluation.runner import _AsyncEventObserver, _SyncEventObserver

type _Completion = Callable[[Candidate, _RunOutcome], None] | None
#: Each Candidate's outcome, in the order given, and the results the follow kept, by index.
type Followed = tuple[tuple[_RunOutcome | Exception, ...], dict[int, _RunOutcome]]
#: How long a Candidate stays `pending` before the progress says it waits for Engine capacity.
#: WHY not at once: every Candidate is `pending` until the driver's first tick after
#: `POST /runs`, which a follower that joins at once sees, though nothing held it back.
_WAITING_AFTER_S = 5.0


class _Follow:
    """What both sinks keep: which Candidates began, waited and ended, each one's outcome, and
    the results kept here as they settled. ``bound`` is each Candidate's observer, by index,
    empty when nothing shows progress."""

    def __init__(
        self,
        candidates: tuple[Candidate, ...],
        bound: Mapping[int, Any],
        *,
        waiting_after_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.candidates = candidates
        self.begun: set[int] = set()
        self.waiting: set[int] = set()
        self.ended: set[int] = set()
        self.results: dict[int, _RunOutcome | _Failed] = {}
        self._bound = bound
        # WHY: with no progress output and no `on_event`, nothing reads a Candidate's events,
        # so the follow asks the Run's stream to leave them out (`?events=false`).
        self.shows_events = bool(bound)
        self._waiting_after_s = waiting_after_s
        self._clock = clock
        self._pending_since: dict[int, float] = {}

    def connection(self, notice: _ConnectionNotice) -> None:
        for index in self.begun - self.ended:
            if index in self._bound:
                self._bound[index].connection(notice)

    def _wait(self, index: int) -> None:
        if index not in self.waiting and index not in self.begun and index in self._bound:
            self.waiting.add(index)
            self._bound[index].connection(_ConnectionNotice("waiting_for_capacity"))

    def _pending(self, index: int) -> None:
        """A `pending` frame: the Candidate waits for capacity once it has been pending for
        ``waiting_after_s`` (at once with none)."""
        if not self._waiting_after_s:
            self._wait(index)
        elif index not in self.begun:
            self._pending_since.setdefault(index, self._clock())

    def quiet(self) -> None:
        """A heartbeat. WHY: while every Candidate waits for capacity, heartbeats are all the
        Run's stream sends, and the wait must still be shown."""
        self._due_waits()

    def _due_waits(self) -> None:
        """Say so for each Candidate pending past ``waiting_after_s``; run before each frame and
        on each heartbeat."""
        now = self._clock()
        for index, since in list(self._pending_since.items()):
            if index in self.begun:
                del self._pending_since[index]
            elif now - since >= self._waiting_after_s:
                del self._pending_since[index]
                self._wait(index)

    @property
    def complete(self) -> bool:
        """Whether every Candidate has ended. INVARIANT (OME-1067): a Run whose Candidates all
        ended is not running, so nothing is canceled for it, even when a callback raises; a
        Candidate has ended once the Engine says so, whether or not its result is here."""
        return len(self.ended) == len(self.candidates)

    def settled_in_order(self) -> _Settled:
        return tuple(
            (candidate, self.results.get(index) or _Failed(_not_received(candidate)))
            for index, candidate in enumerate(self.candidates)
        )

    def followed(self) -> Followed:
        """Each Candidate's outcome for the Report's build, and the results kept here. WHY a
        failed fetch hands over the recorded outcome: the Candidate succeeded on the Engine, so
        the build fetches its result again (spec D14) rather than failing it."""
        outcomes = tuple(
            _for_build(result) if isinstance(result, _Failed) else result
            for _, result in self.settled_in_order()
        )
        kept = {i: r for i, r in self.results.items() if isinstance(r, _RunOutcome)}
        return outcomes, kept


class _SyncFollow(_Follow):
    def __init__(
        self,
        candidates: tuple[Candidate, ...],
        observer: _SyncEventObserver | None,
        on_complete: _Completion,
        *,
        waiting_after_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            candidates,
            {} if observer is None else {i: observer.bind(c) for i, c in enumerate(candidates)},
            waiting_after_s=waiting_after_s,
            clock=clock,
        )
        self._observer = observer
        self._on_complete = on_complete

    def state(self, index: int, state: str) -> None:
        self._due_waits()
        if state == "pending":
            self._pending(index)
            return
        if state in CANDIDATE_ENDED:
            self.ended.add(index)
        self._begin(index)

    def event(self, index: int, event: Event) -> None:
        self._due_waits()
        self._begin(index)
        if index in self._bound:
            self._bound[index](event)

    def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None:
        self._begin(index)
        self.ended.add(index)
        candidate = self.candidates[index]
        if isinstance(outcome, Exception):
            self.results[index] = _Failed(outcome)
            # A failed fetch is not the Candidate's failure: the build fetches it again.
            if (
                recorded_of(outcome) is None
                and self._observer is not None
                and len(self.candidates) > 1
            ):
                if state == "stopped":
                    self._observer.candidate_stopped(candidate)
                else:
                    self._observer.candidate_failed(candidate, outcome)
            return
        self.results[index] = outcome
        if self._on_complete is not None:
            _observe(self._on_complete, candidate, outcome)

    def _begin(self, index: int) -> None:
        if index in self.begun:
            return
        self.begun.add(index)
        if self._observer is not None:
            self._observer.begin(self.candidates[index])
            if index in self.waiting:
                self._bound[index].connection(_ConnectionNotice("admitted"))


class _AsyncFollow(_Follow):
    def __init__(
        self,
        candidates: tuple[Candidate, ...],
        observer: _AsyncEventObserver | None,
        on_complete: _Completion,
        *,
        waiting_after_s: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            candidates,
            {} if observer is None else {i: observer.bind(c) for i, c in enumerate(candidates)},
            waiting_after_s=waiting_after_s,
            clock=clock,
        )
        self._observer = observer
        self._on_complete = on_complete

    async def state(self, index: int, state: str) -> None:
        self._due_waits()
        if state == "pending":
            self._pending(index)
            return
        if state in CANDIDATE_ENDED:
            self.ended.add(index)
        await self._begin(index)

    async def event(self, index: int, event: Event) -> None:
        self._due_waits()
        await self._begin(index)
        if index in self._bound:
            returned = self._bound[index](event)
            if inspect.isawaitable(returned):
                await returned

    async def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None:
        await self._begin(index)
        self.ended.add(index)
        candidate = self.candidates[index]
        if isinstance(outcome, Exception):
            self.results[index] = _Failed(outcome)
            # A failed fetch is not the Candidate's failure: the build fetches it again.
            if (
                recorded_of(outcome) is None
                and self._observer is not None
                and len(self.candidates) > 1
            ):
                if state == "stopped":
                    self._observer.candidate_stopped(candidate)
                else:
                    await self._observer.candidate_failed(candidate, outcome)
            return
        self.results[index] = outcome
        if self._on_complete is not None:
            _observe(self._on_complete, candidate, outcome)

    async def _begin(self, index: int) -> None:
        if index in self.begun:
            return
        self.begun.add(index)
        if self._observer is not None:
            await self._observer.begin(self.candidates[index])
            if index in self.waiting:
                self._bound[index].connection(_ConnectionNotice("admitted"))


def followed_sync(
    transport: _RunFollowing,
    run_id: str,
    candidates: tuple[Candidate, ...],
    observer: _SyncEventObserver | None,
    on_complete: _Completion,
) -> Followed:
    """Follow the Run to its end: each Candidate's outcome, and the results kept as they
    settled."""
    sink = _SyncFollow(candidates, observer, on_complete, waiting_after_s=_WAITING_AFTER_S)
    try:
        transport.follow_run(run_id, candidates, sink)
    except BaseException as exc:
        if _stops_the_run(exc, observer) and not sink.complete:
            _cancel_sync(transport, run_id, exc)
        raise
    return sink.followed()


async def followed_async(
    transport: _AsyncRunFollowing,
    run_id: str,
    candidates: tuple[Candidate, ...],
    observer: _AsyncEventObserver | None,
    on_complete: _Completion,
) -> Followed:
    """The async twin of ``followed_sync``."""
    sink = _AsyncFollow(candidates, observer, on_complete, waiting_after_s=_WAITING_AFTER_S)
    try:
        await transport.follow_run(run_id, candidates, sink)
    except BaseException as exc:
        if _stops_the_run(exc, observer) and not sink.complete:
            await _cancel_async(transport, run_id, exc)
        raise
    return sink.followed()


@contextmanager
def canceled_if_left_sync(transport: object, run_id: str | None) -> Iterator[None]:
    """Cancel the registered Run when the evaluation stops before it follows the Run.

    INVARIANT (D14): the Engine starts every Candidate once the Run is registered, so an error
    or Ctrl-C between registering and following (setting up this machine's result store, or
    the progress output) must not leave the Run spending with nobody following it.
    """
    try:
        yield
    except BaseException as exc:
        if run_id is not None and isinstance(transport, _RunFollowing):
            _cancel_sync(transport, run_id, exc)
        raise


@asynccontextmanager
async def canceled_if_left_async(transport: object, run_id: str | None) -> AsyncIterator[None]:
    """The async twin of ``canceled_if_left_sync``."""
    try:
        yield
    except BaseException as exc:
        if run_id is not None and isinstance(transport, _AsyncRunFollowing):
            await _cancel_async(transport, run_id, exc)
        raise


def _cancel_sync(transport: _RunFollowing, run_id: str, exc: BaseException) -> None:
    try:
        transport.cancel_run(run_id)
    except Exception as cancel_error:  # noqa: BLE001 - keep the interruption the user sees
        exc.add_note(f"Canceling Run {run_id} on the SF Engine also failed: {cancel_error}")


async def _cancel_async(transport: _AsyncRunFollowing, run_id: str, exc: BaseException) -> None:
    try:
        await transport.cancel_run(run_id)
    except Exception as cancel_error:  # noqa: BLE001 - keep the interruption the user sees
        exc.add_note(f"Canceling Run {run_id} on the SF Engine also failed: {cancel_error}")


def _stops_the_run(
    exc: BaseException, observer: _SyncEventObserver | _AsyncEventObserver | None
) -> bool:
    if isinstance(exc, ScreamingFaceError):
        # The follow's own end; unless the caller's callback raised it.
        return observer is not None and observer.raised_by_caller(exc)
    return True


def _for_build(failed: _Failed) -> _RunOutcome | Exception:
    return recorded_of(failed.error) or failed.error


def _observe(callback: Callable[..., object], *values: object) -> None:
    from screamingface._evaluation.runner import _observe_progress

    _observe_progress(callback, *values)


def _not_received(candidate: Candidate) -> ExecutionError:
    return ExecutionError(
        f"The Run ended without a result for Candidate {candidate.name!r}",
        code="result_not_received",
    )


__all__: list[str] = []

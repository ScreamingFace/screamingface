"""The runner's follow path: the Engine drives the Run, the Client follows it (E5 P2 spec D1,
D13, D14).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my evaluation reads the same as
before: results in the order I gave the Candidates, a failed Candidate named while its siblings
finish, and Ctrl-C stops what I started, though my notebook now starts nothing itself.

The transport follows the Run's one stream and reports each Candidate's state, events and
outcome here, by index; this module drives the progress output and `on_event` from them, as the
per-Candidate path did, and keeps each Candidate's outcome for the Report.

INVARIANT (D14): Ctrl-C, a cancelled task, the caller's own `on_event` or a defect cancels the
Run once. A follow that ends on its own (an expired sign-in, a connection it could not get back,
a Run that is gone) leaves the Run to the Engine, which is what D15 tells the user.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING

from screamingface._core.ports import (
    _AsyncRunFollowing,
    _ConnectionNotice,
    _RunFollowing,
    _RunOutcome,
)
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.outcome import _Failed, _Settled
from screamingface.errors import ExecutionError, ScreamingFaceError
from screamingface.events import Event

if TYPE_CHECKING:
    from screamingface._evaluation.runner import _AsyncEventObserver, _SyncEventObserver

type _Completion = Callable[[Candidate, _RunOutcome], None] | None


class _Follow:
    """What both sinks keep: which Candidates began, waited and settled, and their outcomes."""

    def __init__(self, candidates: tuple[Candidate, ...]) -> None:
        self.candidates = candidates
        self.begun: set[int] = set()
        self.waiting: set[int] = set()
        self.results: dict[int, _RunOutcome | _Failed] = {}

    @property
    def complete(self) -> bool:
        """Whether every Candidate has settled. INVARIANT (OME-1067): a Run whose Candidates all
        ended is not running, so nothing is canceled for it, even when a callback raises."""
        return len(self.results) == len(self.candidates)

    def settled_in_order(self) -> _Settled:
        return tuple(
            (candidate, self.results.get(index) or _Failed(_not_received(candidate)))
            for index, candidate in enumerate(self.candidates)
        )


class _SyncFollow(_Follow):
    def __init__(
        self,
        candidates: tuple[Candidate, ...],
        observer: _SyncEventObserver | None,
        on_complete: _Completion,
    ) -> None:
        super().__init__(candidates)
        self._observer = observer
        self._on_complete = on_complete
        self._bound = (
            {} if observer is None else {i: observer.bind(c) for i, c in enumerate(candidates)}
        )

    def state(self, index: int, state: str) -> None:
        if state == "pending":
            self._wait(index)
        else:
            self._begin(index)

    def event(self, index: int, event: Event) -> None:
        self._begin(index)
        if index in self._bound:
            self._bound[index](event)

    def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None:
        self._begin(index)
        candidate = self.candidates[index]
        if isinstance(outcome, Exception):
            self.results[index] = _Failed(outcome)
            if self._observer is not None and len(self.candidates) > 1:
                if state == "stopped":
                    self._observer.candidate_stopped(candidate)
                else:
                    self._observer.candidate_failed(candidate, outcome)
            return
        self.results[index] = outcome
        if self._on_complete is not None:
            _observe(self._on_complete, candidate, outcome)

    def connection(self, notice: _ConnectionNotice) -> None:
        for index in self.begun - self.results.keys():
            if index in self._bound:
                self._bound[index].connection(notice)

    def _wait(self, index: int) -> None:
        if index not in self.waiting and index not in self.begun and index in self._bound:
            self.waiting.add(index)
            self._bound[index].connection(_ConnectionNotice("waiting_for_capacity"))

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
    ) -> None:
        super().__init__(candidates)
        self._observer = observer
        self._on_complete = on_complete
        self._bound = (
            {} if observer is None else {i: observer.bind(c) for i, c in enumerate(candidates)}
        )

    async def state(self, index: int, state: str) -> None:
        if state == "pending":
            self._wait(index)
        else:
            await self._begin(index)

    async def event(self, index: int, event: Event) -> None:
        await self._begin(index)
        if index in self._bound:
            returned = self._bound[index](event)
            if inspect.isawaitable(returned):
                await returned

    async def settled(self, index: int, state: str, outcome: _RunOutcome | Exception) -> None:
        await self._begin(index)
        candidate = self.candidates[index]
        if isinstance(outcome, Exception):
            self.results[index] = _Failed(outcome)
            if self._observer is not None and len(self.candidates) > 1:
                if state == "stopped":
                    self._observer.candidate_stopped(candidate)
                else:
                    await self._observer.candidate_failed(candidate, outcome)
            return
        self.results[index] = outcome
        if self._on_complete is not None:
            _observe(self._on_complete, candidate, outcome)

    def connection(self, notice: _ConnectionNotice) -> None:
        for index in self.begun - self.results.keys():
            if index in self._bound:
                self._bound[index].connection(notice)

    def _wait(self, index: int) -> None:
        if index not in self.waiting and index not in self.begun and index in self._bound:
            self.waiting.add(index)
            self._bound[index].connection(_ConnectionNotice("waiting_for_capacity"))

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
) -> _Settled:
    """Every Candidate's outcome, in the order given, once the Run has ended."""
    sink = _SyncFollow(candidates, observer, on_complete)
    try:
        transport.follow_run(run_id, candidates, sink)
    except BaseException as exc:
        if _stops_the_run(exc, observer) and not sink.complete:
            try:
                transport.cancel_run(run_id)
            except Exception as cancel_error:  # noqa: BLE001 - keep the interruption the user sees
                exc.add_note(f"Canceling Run {run_id} on the SF Engine also failed: {cancel_error}")
        raise
    return _lone_raised(sink.settled_in_order())


async def followed_async(
    transport: _AsyncRunFollowing,
    run_id: str,
    candidates: tuple[Candidate, ...],
    observer: _AsyncEventObserver | None,
    on_complete: _Completion,
) -> _Settled:
    """The async twin of ``followed_sync``."""
    sink = _AsyncFollow(candidates, observer, on_complete)
    try:
        await transport.follow_run(run_id, candidates, sink)
    except BaseException as exc:
        if _stops_the_run(exc, observer) and not sink.complete:
            try:
                await transport.cancel_run(run_id)
            except Exception as cancel_error:  # noqa: BLE001 - keep the interruption the user sees
                exc.add_note(f"Canceling Run {run_id} on the SF Engine also failed: {cancel_error}")
        raise
    return _lone_raised(sink.settled_in_order())


def _stops_the_run(
    exc: BaseException, observer: _SyncEventObserver | _AsyncEventObserver | None
) -> bool:
    if isinstance(exc, ScreamingFaceError):
        # The follow's own end; unless the caller's callback raised it.
        return observer is not None and observer.raised_by_caller(exc)
    return True


def _lone_raised(settled: _Settled) -> _Settled:
    """WHY: a one-Candidate evaluation has always raised its Candidate's own error, never
    `candidates_failed`; the follow path keeps that."""
    if len(settled) == 1 and isinstance(settled[0][1], _Failed):
        raise settled[0][1].error
    return settled


def _observe(callback: Callable[..., object], *values: object) -> None:
    from screamingface._evaluation.runner import _observe_progress

    _observe_progress(callback, *values)


def _not_received(candidate: Candidate) -> ExecutionError:
    return ExecutionError(
        f"The Run ended without a result for Candidate {candidate.name!r}",
        code="result_not_received",
    )


__all__: list[str] = []

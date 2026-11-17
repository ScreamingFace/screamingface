"""The transports' Run half: register an evaluation as a Run, follow it, cancel it (E5 P2 spec
D1, D13, D14).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my notebook sends the evaluation once
and follows it; the Engine starts every Candidate, whether or not I stay.

INVARIANT (D1): nothing here starts a Candidate. `POST /runs` carries every start; the follow
reads one stream, handing each frame over on the caller's thread; each Candidate's outcome is
built from the Engine's record, and its result fetched from the Run's result route beside the
follow and kept before it settles (D14).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import ssl
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Self, cast
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from websockets.asyncio import client as async_ws
from websockets.sync import client as sync_ws

from screamingface._access.base import _TransportAuth
from screamingface._core.ports import (
    _AsyncRunSink,
    _EndedRun,
    _RunOutcome,
    _RunSink,
    with_recorded,
)
from screamingface._core.wire import LOGIN_NOT_STARTED
from screamingface._engine import run_follow, runs
from screamingface._engine.identity import engine_headers
from screamingface._engine.run_record import candidate_outcome
from screamingface._engine.run_request import run_request
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface.errors import AuthenticationError, ExecutionError

#: WHY bounded: a cancel happens while the caller is interrupting; a slow Engine must not hold
#: Ctrl-C for the client's whole 30 s timeout. For the same reason the cancel never starts a
#: sign-in (spec D15): a challenged cancel fails, and the Engine stops the unfollowed Run.
_CANCEL_TIMEOUT_S = 5.0
#: Above the largest frame the Engine's Run stream sends: a `candidate.settled` with a 48 KiB
#: record, or a result event carrying up to its 1 MiB inline body.
_MAX_FRAME_BYTES = 8 * 1024 * 1024
_KEEPALIVE_PING_S = 20.0
#: WHY short: a follow is closed when the user interrupts it, and closing is best-effort; Ctrl-C
#: must not wait on an Engine that does not answer the close.
_CLOSE_TIMEOUT_S = 2.0
#: How many results a follow downloads at once, as many as the Report's build.
_DOWNLOADS = 4
_logger = logging.getLogger(__name__)

type Save = Callable[[Candidate, _RunOutcome], _RunOutcome]
type AsyncSave = Callable[[Candidate, _RunOutcome], Awaitable[_RunOutcome]]
#: A settled Candidate waiting to be handed over: its frame, its outcome from the record, and
#: the download of its result, if it has one.
type _Settling[T] = tuple[run_follow.CandidateSettled, _RunOutcome | Exception, T | None]


@dataclass(frozen=True, slots=True)
class FollowTimings:
    """The follower's reconnect budget; tests shorten it."""

    budget_s: float = run_follow.RECONNECT_BUDGET_S
    base_delay_s: float = run_follow.RECONNECT_BASE_DELAY_S


def events_url(engine_url: str, run_id: str, *, events: bool = True) -> str:
    """The Run's stream; without ``events``, only its states, settled frames and end: all that
    `Run.wait()` reads. An Engine that does not know the option sends the whole stream."""
    parts = urlsplit(engine_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    base = parts.path.rstrip("/")
    query = "" if events else "events=false"
    return urlunsplit(
        (scheme, parts.netloc, f"{base}/runs/{quote(run_id, safe='')}/events", query, "")
    )


class RunClient:
    """Sync. ``save`` keeps a settled Candidate's result: saved to disk, or read into memory."""

    def __init__(
        self,
        http: httpx.Client,
        engine_url: str,
        caller_auth: _TransportAuth,
        ssl_context: ssl.SSLContext | None,
        timings: FollowTimings = FollowTimings(),
    ) -> None:
        self._http = http
        self._engine_url = engine_url
        self._auth = caller_auth
        self._ssl = ssl_context
        self._timings = timings

    def register(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> runs.RunRecord:
        request = run_request(evaluation, candidates, detach=detach, deadline_s=deadline_s)
        return runs.create_sync(runs.marked_request(self._http), request)

    def follow(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _RunSink, save: Save
    ) -> run_follow.RunEnded:
        """Hand each frame to ``sink`` on this thread until the Run ends. A succeeded
        Candidate's result downloads beside the follow, at most `_DOWNLOADS` at once, so the
        frames keep flowing and the socket keeps answering keepalives (spec R10); its `settled`
        is handed over once the download ends, in the order the Candidates settled, and the
        follow waits for the last before it returns. What the sink raises ends the follow at
        once, without waiting for a download. A result fetch never starts a sign-in (D15). A
        sink that shows no events (``shows_events`` false) is followed without them. A
        Candidate that succeeded without its record settles once the Run has ended, from the
        record the Engine holds then."""
        events = getattr(sink, "shows_events", True)
        with _ToSink(run_id, candidates, sink, save) as to_sink:
            ended = run_follow.follow_sync(
                lambda: self._socket(run_id, events=events),
                run_id,
                to_sink.frame,
                detached=False,
                on_connection=sink.connection,
                budget_s=self._timings.budget_s,
                base_delay_s=self._timings.base_delay_s,
            )
            if to_sink.held:
                for frame in _late_records(to_sink.held, self._reread(run_id)):
                    to_sink.settle(frame)
            to_sink.finish()
        return ended

    def _reread(self, run_id: str) -> runs.RunRecord | None:
        try:
            return runs.get_sync(runs.marked_request(self._http, login=False), run_id)
        except Exception:  # noqa: BLE001 - the Candidate's result reads as lost, as before
            _logger.warning("Could not read Run %s again for its late records", run_id)
            return None

    def cancel(self, run_id: str) -> None:
        request = runs.marked_request(self._http, timeout=_CANCEL_TIMEOUT_S, login=False)
        runs.cancel_sync(request, run_id)

    def wait(self, run_id: str, *, detached: bool) -> run_follow.RunEnded:
        return run_follow.follow_sync(
            lambda: self._socket(run_id, events=False),
            run_id,
            lambda _frame: None,
            detached=detached,
            budget_s=self._timings.budget_s,
            base_delay_s=self._timings.base_delay_s,
        )

    async def wait_async(self, run_id: str, *, detached: bool) -> run_follow.RunEnded:
        """``wait`` on the event loop: cancelling the awaiting task closes the socket, so the
        follow, and the hold it gives an attached Run, ends with it."""
        return await _waited(
            self._engine_url, self._auth, self._ssl, self._timings, run_id, detached
        )

    def _socket(
        self, run_id: str, *, events: bool = True
    ) -> AbstractContextManager[sync_ws.ClientConnection]:
        return sync_ws.connect(
            events_url(self._engine_url, run_id, events=events),
            additional_headers={**engine_headers(), **self._auth.websocket_headers()},
            open_timeout=30,
            close_timeout=_CLOSE_TIMEOUT_S,
            ping_interval=_KEEPALIVE_PING_S,
            max_size=_MAX_FRAME_BYTES,
            ssl=self._ssl,
        )


class AsyncRunClient:
    """The async twin of ``RunClient``."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        engine_url: str,
        caller_auth: _TransportAuth,
        ssl_context: ssl.SSLContext | None,
        timings: FollowTimings = FollowTimings(),
    ) -> None:
        self._http = http
        self._engine_url = engine_url
        self._auth = caller_auth
        self._ssl = ssl_context
        self._timings = timings

    async def register(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> runs.RunRecord:
        request = run_request(evaluation, candidates, detach=detach, deadline_s=deadline_s)
        return await runs.create_async(runs.marked_async_request(self._http), request)

    async def follow(
        self,
        run_id: str,
        candidates: tuple[Candidate, ...],
        sink: _AsyncRunSink,
        save: AsyncSave,
    ) -> run_follow.RunEnded:
        """The async twin of ``RunClient.follow``: each download is a task beside the follow,
        and each sink call is awaited in turn."""
        events = getattr(sink, "shows_events", True)
        async with _ToAsyncSink(run_id, candidates, sink, save) as to_sink:
            ended = await run_follow.follow_async(
                lambda: _async_socket(
                    self._engine_url, self._auth, self._ssl, run_id, events=events
                ),
                run_id,
                to_sink.frame,
                detached=False,
                on_connection=sink.connection,
                budget_s=self._timings.budget_s,
                base_delay_s=self._timings.base_delay_s,
            )
            if to_sink.held:
                for frame in _late_records(to_sink.held, await self._reread(run_id)):
                    await to_sink.settle(frame)
            await to_sink.finish()
        return ended

    async def _reread(self, run_id: str) -> runs.RunRecord | None:
        try:
            return await runs.get_async(runs.marked_async_request(self._http, login=False), run_id)
        except Exception:  # noqa: BLE001 - the Candidate's result reads as lost, as before
            _logger.warning("Could not read Run %s again for its late records", run_id)
            return None

    async def cancel(self, run_id: str) -> None:
        request = runs.marked_async_request(self._http, timeout=_CANCEL_TIMEOUT_S, login=False)
        await runs.cancel_async(request, run_id)

    async def wait(self, run_id: str, *, detached: bool) -> run_follow.RunEnded:
        """``RunClient.wait`` on the event loop: cancelling the awaiting task closes the socket."""
        return await _waited(
            self._engine_url, self._auth, self._ssl, self._timings, run_id, detached
        )


class _ToSink:
    """One follow's frames, handed to its sink on the follow's thread. A succeeded Candidate's
    result downloads in a small pool beside the follow, so the frame loop never waits on it;
    its `settled` is handed over at the next frame after its download ends (the Engine sends
    one at least every 15 s), behind any Candidate that settled before it. What waits is one
    entry per Candidate, never the frames behind it. A Candidate that succeeded without its
    record is ``held`` until the Run ends."""

    def __init__(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _RunSink, save: Save
    ) -> None:
        self._run_id = run_id
        self._candidates = candidates
        self._sink = sink
        self._save = save
        self.held: dict[int, run_follow.CandidateSettled] = {}
        self._pool = ThreadPoolExecutor(max_workers=_DOWNLOADS, thread_name_prefix="sf-result")
        self._settling: deque[_Settling[Future[_RunOutcome | Exception]]] = deque()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # WHY not waiting when the follow fails: Ctrl-C must not wait for a running download.
        self._pool.shutdown(wait=kind is None, cancel_futures=kind is not None)

    def frame(self, frame: run_follow.Frame) -> None:
        self._hand_over_downloaded()
        if isinstance(frame, run_follow.Quiet):
            self._sink.quiet()
            return
        _candidate(self._candidates, frame.index)
        if isinstance(frame, run_follow.CandidateState):
            self._sink.state(frame.index, frame.state)
        elif isinstance(frame, run_follow.CandidateEvent):
            self._sink.event(frame.index, frame.event)
        else:
            # The Candidate has ended on the Engine, before its result is fetched here.
            self._sink.state(frame.index, frame.state)
            if not _held(self.held, frame):
                self.settle(frame)

    def settle(self, frame: run_follow.CandidateSettled) -> None:
        candidate = _candidate(self._candidates, frame.index)
        outcome = _settled(self._run_id, candidate, frame)
        download = None
        if not isinstance(outcome, Exception):
            fetch = functools.partial(self._save, candidate, outcome)
            download = self._pool.submit(_fetched, fetch, self._run_id, outcome)
        self._settling.append((frame, outcome, download))
        self._hand_over_downloaded()

    def finish(self) -> None:
        """Wait for each download still running, handing each Candidate over in turn."""
        while self._settling:
            self._hand_over(self._settling.popleft())

    def _hand_over_downloaded(self) -> None:
        while self._settling and _ready(self._settling[0][2]):
            self._hand_over(self._settling.popleft())

    def _hand_over(self, settling: _Settling[Future[_RunOutcome | Exception]]) -> None:
        frame, outcome, download = settling
        if download is not None:
            outcome = download.result()
        self._sink.settled(frame.index, frame.state, outcome)


class _ToAsyncSink:
    """The async twin of ``_ToSink``: each download is a task, at most `_DOWNLOADS` at once,
    and each sink call is awaited in turn."""

    def __init__(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _AsyncRunSink, save: AsyncSave
    ) -> None:
        self._run_id = run_id
        self._candidates = candidates
        self._sink = sink
        self._save = save
        self.held: dict[int, run_follow.CandidateSettled] = {}
        self._slots = asyncio.Semaphore(_DOWNLOADS)
        self._settling: deque[_Settling[asyncio.Task[_RunOutcome | Exception]]] = deque()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for _frame, _outcome, download in self._settling:
            if download is not None:
                _abandon(download)

    async def frame(self, frame: run_follow.Frame) -> None:
        await self._hand_over_downloaded()
        if isinstance(frame, run_follow.Quiet):
            self._sink.quiet()
            return
        _candidate(self._candidates, frame.index)
        if isinstance(frame, run_follow.CandidateState):
            await self._sink.state(frame.index, frame.state)
        elif isinstance(frame, run_follow.CandidateEvent):
            await self._sink.event(frame.index, frame.event)
        else:
            # The Candidate has ended on the Engine, before its result is fetched here.
            await self._sink.state(frame.index, frame.state)
            if not _held(self.held, frame):
                await self.settle(frame)

    async def settle(self, frame: run_follow.CandidateSettled) -> None:
        candidate = _candidate(self._candidates, frame.index)
        outcome = _settled(self._run_id, candidate, frame)
        download = None
        if not isinstance(outcome, Exception):
            download = asyncio.create_task(self._download(candidate, outcome))
        self._settling.append((frame, outcome, download))
        await self._hand_over_downloaded()

    async def finish(self) -> None:
        """Wait for each download still running, handing each Candidate over in turn."""
        while self._settling:
            await self._hand_over(self._settling.popleft())

    async def _download(
        self, candidate: Candidate, outcome: _RunOutcome
    ) -> _RunOutcome | Exception:
        async with self._slots:
            return await _fetched_async(self._save(candidate, outcome), self._run_id, outcome)

    async def _hand_over_downloaded(self) -> None:
        while self._settling and _ready(self._settling[0][2]):
            await self._hand_over(self._settling.popleft())

    async def _hand_over(self, settling: _Settling[asyncio.Task[_RunOutcome | Exception]]) -> None:
        frame, outcome, download = settling
        if download is not None:
            outcome = await download
        await self._sink.settled(frame.index, frame.state, outcome)


def _ready(
    download: Future[_RunOutcome | Exception] | asyncio.Future[_RunOutcome | Exception] | None,
) -> bool:
    return download is None or download.done()


def _abandon(download: asyncio.Task[_RunOutcome | Exception]) -> None:
    """Cancel a download the ended follow no longer waits for. WHY read a finished one's
    error: asyncio logs an error nobody read as lost."""
    if not download.done():
        download.cancel()
    elif not download.cancelled():
        download.exception()


async def _waited(
    engine_url: str,
    auth: _TransportAuth,
    ssl_context: ssl.SSLContext | None,
    timings: FollowTimings,
    run_id: str,
    detached: bool,
) -> run_follow.RunEnded:
    """Follow the Run to its end on the event loop, without events (`Run.wait_async`)."""
    return await run_follow.follow_async(
        lambda: _async_socket(engine_url, auth, ssl_context, run_id, events=False),
        run_id,
        lambda _frame: None,
        detached=detached,
        budget_s=timings.budget_s,
        base_delay_s=timings.base_delay_s,
    )


@asynccontextmanager
async def _async_socket(
    engine_url: str,
    auth: _TransportAuth,
    ssl_context: ssl.SSLContext | None,
    run_id: str,
    *,
    events: bool = True,
) -> AsyncIterator[async_ws.ClientConnection]:
    """The Run's stream, async. WHY signed on every connect: a reconnect sends the sign-in the
    Client holds now, as the sync follow does; a refreshed sign-in is never replaced by the one
    the follow began with."""
    headers = {**engine_headers(), **(await auth.websocket_headers_async())}
    async with async_ws.connect(
        events_url(engine_url, run_id, events=events),
        additional_headers=headers,
        open_timeout=30,
        close_timeout=_CLOSE_TIMEOUT_S,
        ping_interval=_KEEPALIVE_PING_S,
        max_size=_MAX_FRAME_BYTES,
        ssl=ssl_context,
    ) as socket:
        yield socket


def _fetched(
    fetch: Callable[[], _RunOutcome], run_id: str, recorded: _RunOutcome
) -> _RunOutcome | Exception:
    """A settled Candidate's result, or the fetch's error naming the ``recorded`` outcome, so
    the Report built when the Run ends fetches it again (spec D14). A fetch that would need a
    sign-in ends the follow with how to pick the Run up (D15): the Run goes on."""
    try:
        return fetch()
    except AuthenticationError as exc:
        if exc.code == LOGIN_NOT_STARTED:
            raise run_follow.login_expired(run_id, detached=False) from exc
        return with_recorded(exc, recorded)
    except Exception as exc:  # noqa: BLE001 - fetched again when the Run ends (D14)
        return with_recorded(exc, recorded)


async def _fetched_async(
    fetch: Awaitable[_RunOutcome], run_id: str, recorded: _RunOutcome
) -> _RunOutcome | Exception:
    """The async twin of ``_fetched``."""
    try:
        return await fetch
    except AuthenticationError as exc:
        if exc.code == LOGIN_NOT_STARTED:
            raise run_follow.login_expired(run_id, detached=False) from exc
        return with_recorded(exc, recorded)
    except Exception as exc:  # noqa: BLE001 - fetched again when the Run ends (D14)
        return with_recorded(exc, recorded)


def _held(late: dict[int, run_follow.CandidateSettled], frame: run_follow.CandidateSettled) -> bool:
    """Whether ``frame`` is held until the Run ends: it succeeded without its record, which
    the Engine may fill after it sent the frame (#1878 review). A replay that carries the
    record settles it at once."""
    if frame.awaits_record:
        late[frame.index] = frame
        return True
    late.pop(frame.index, None)
    return False


def _late_records(
    late: dict[int, run_follow.CandidateSettled], run: runs.RunRecord | None
) -> list[run_follow.CandidateSettled]:
    """Each held frame with the record ``run``, read once the Run ended, holds; None where
    the Engine still has none, or the read failed."""
    records = {} if run is None else {c.index: c.record for c in run.candidates}
    return [replace(frame, record=records.get(index)) for index, frame in late.items()]


def _candidate(candidates: tuple[Candidate, ...], index: int) -> Candidate:
    """The frame's Candidate. A frame for one the Run does not have is the Engine's defect,
    raised as such, so the follow ends without canceling the user's Run."""
    if index >= len(candidates):
        raise ExecutionError(
            f"The SF Engine sent a frame for Candidate {index} of a Run with {len(candidates)}",
            code="engine_contract_error",
            permanent=True,
        )
    return candidates[index]


def ended_run(request: runs.Request, run: runs.RunRecord) -> _EndedRun | None:
    """The ended Run's context, read with ``request``, with its starts and outcomes from the
    full read ``run`` (E5 P2 spec D9b); None for a Run from before P2, which kept neither its
    context nor its starts."""
    if run.context is None or any(c.start is None for c in run.candidates):
        return None
    return _ended(run, runs.context_sync(request, run.id, run.context))


async def ended_run_async(request: runs.AsyncRequest, run: runs.RunRecord) -> _EndedRun | None:
    """The async twin of ``ended_run``."""
    if run.context is None or any(c.start is None for c in run.candidates):
        return None
    return _ended(run, await runs.context_async(request, run.id, run.context))


def _ended(run: runs.RunRecord, context: str) -> _EndedRun:
    return _EndedRun(
        context=context,
        starts=tuple(c.start for c in run.candidates if c.start is not None),
        outcomes=tuple(_recorded(run.id, candidate) for candidate in run.candidates),
    )


def _recorded(run_id: str, candidate: runs.CandidateRecord) -> _RunOutcome | Exception:
    try:
        return candidate_outcome(run_id, candidate)
    except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
        return exc


def _settled(
    run_id: str, candidate: Candidate, settled: run_follow.CandidateSettled
) -> _RunOutcome | Exception:
    """The settled Candidate's outcome from its record, or the error of one that did not
    succeed."""
    try:
        return _outcome(run_id, candidate, settled)
    except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
        return exc


def _outcome(
    run_id: str, candidate: Candidate, settled: run_follow.CandidateSettled
) -> _RunOutcome:
    """The settled Candidate's outcome from its record; raises when it did not succeed."""
    return candidate_outcome(
        run_id,
        runs.CandidateRecord(
            name=candidate.name,
            # The frame's state, which candidate_outcome checks is an ended one.
            state=cast(runs.CandidateState, settled.state),
            attempt_id=settled.attempt_id,
            started_at=None,
            finished_at=None,
            cost_usd=None,
            error_code=settled.error_code,
            index=settled.index,
            record=settled.record,
        ),
    )


__all__ = [
    "AsyncRunClient",
    "FollowTimings",
    "RunClient",
    "ended_run",
    "ended_run_async",
    "events_url",
]

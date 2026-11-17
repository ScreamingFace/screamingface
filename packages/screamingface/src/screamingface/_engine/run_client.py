"""The transports' Run half: register an evaluation as a Run, follow it, cancel it (E5 P2 spec
D1, D13, D14).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, my notebook sends the evaluation once
and follows it; the Engine starts every Candidate, whether or not I stay.

INVARIANT (D1): nothing here starts a Candidate. `POST /runs` carries every start; the follow
reads one stream; each Candidate's outcome is built from the Engine's record and its result read
from the Run's result route.
"""

from __future__ import annotations

import ssl
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from websockets.asyncio import client as async_ws
from websockets.sync import client as sync_ws

from screamingface._access.base import _TransportAuth
from screamingface._core.ports import _AsyncRunSink, _RunOutcome, _RunSink
from screamingface._engine import run_follow, runs
from screamingface._engine.identity import engine_headers
from screamingface._engine.run_record import candidate_outcome
from screamingface._engine.run_request import run_request
from screamingface._evaluation.model import Candidate, _Evaluation

#: WHY bounded: a cancel happens while the caller is interrupting; a slow Engine must not hold
#: Ctrl-C for the client's whole 30 s timeout.
_CANCEL_TIMEOUT_S = 5.0
#: Above the largest frame the Engine sends: a `candidate.settled` with a 48 KiB record, or a
#: result event carrying up to its 1 MiB inline body (see `transport._MAX_FRAME_BYTES`).
_MAX_FRAME_BYTES = 8 * 1024 * 1024
_KEEPALIVE_PING_S = 20.0
#: WHY short: a follow is closed when the user interrupts it, and closing is best-effort; Ctrl-C
#: must not wait on an Engine that does not answer the close.
_CLOSE_TIMEOUT_S = 2.0

type Save = Callable[[Candidate, _RunOutcome], _RunOutcome]
type AsyncSave = Callable[[Candidate, _RunOutcome], Awaitable[_RunOutcome]]


@dataclass(frozen=True, slots=True)
class FollowTimings:
    """The follower's reconnect budget; tests shorten it."""

    budget_s: float = run_follow.RECONNECT_BUDGET_S
    base_delay_s: float = run_follow.RECONNECT_BASE_DELAY_S


def events_url(engine_url: str, run_id: str) -> str:
    parts = urlsplit(engine_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    base = parts.path.rstrip("/")
    return urlunsplit(
        (scheme, parts.netloc, f"{base}/runs/{quote(run_id, safe='')}/events", "", "")
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
    ) -> str:
        request = run_request(evaluation, candidates, detach=detach, deadline_s=deadline_s)
        return runs.create_sync(runs.marked_request(self._http), request).id

    def follow(
        self,
        run_id: str,
        candidates: tuple[Candidate, ...],
        sink: _RunSink,
        save: Save,
        *,
        detached: bool = False,
    ) -> run_follow.RunEnded:
        def on_frame(frame: run_follow.Frame) -> None:
            if isinstance(frame, run_follow.CandidateState):
                sink.state(frame.index, frame.state)
            elif isinstance(frame, run_follow.CandidateEvent):
                sink.event(frame.index, frame.event)
            else:
                candidate = candidates[frame.index]
                try:
                    outcome: _RunOutcome | Exception = save(
                        candidate, _outcome(run_id, candidate, frame)
                    )
                except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
                    outcome = exc
                sink.settled(frame.index, frame.state, outcome)

        return run_follow.follow_sync(
            lambda: self._socket(run_id),
            run_id,
            on_frame,
            detached=detached,
            on_connection=sink.connection,
            budget_s=self._timings.budget_s,
            base_delay_s=self._timings.base_delay_s,
        )

    def cancel(self, run_id: str) -> None:
        runs.cancel_sync(runs.marked_request(self._http, timeout=_CANCEL_TIMEOUT_S), run_id)

    def _socket(self, run_id: str) -> AbstractContextManager[sync_ws.ClientConnection]:
        return sync_ws.connect(
            events_url(self._engine_url, run_id),
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
    ) -> str:
        request = run_request(evaluation, candidates, detach=detach, deadline_s=deadline_s)
        return (await runs.create_async(runs.marked_async_request(self._http), request)).id

    async def follow(
        self,
        run_id: str,
        candidates: tuple[Candidate, ...],
        sink: _AsyncRunSink,
        save: AsyncSave,
        *,
        detached: bool = False,
    ) -> run_follow.RunEnded:
        async def on_frame(frame: run_follow.Frame) -> None:
            if isinstance(frame, run_follow.CandidateState):
                await sink.state(frame.index, frame.state)
            elif isinstance(frame, run_follow.CandidateEvent):
                await sink.event(frame.index, frame.event)
            else:
                candidate = candidates[frame.index]
                try:
                    outcome: _RunOutcome | Exception = await save(
                        candidate, _outcome(run_id, candidate, frame)
                    )
                except Exception as exc:  # noqa: BLE001 - one Candidate's failure (spec C1b)
                    outcome = exc
                await sink.settled(frame.index, frame.state, outcome)

        # WHY read once: the follow never signs in again (D15), so the headers stay valid for
        # it or the follow ends with how to pick the Run up.
        headers = {**engine_headers(), **(await self._auth.websocket_headers_async())}
        return await run_follow.follow_async(
            lambda: self._socket(run_id, headers),
            run_id,
            on_frame,
            detached=detached,
            on_connection=sink.connection,
            budget_s=self._timings.budget_s,
            base_delay_s=self._timings.base_delay_s,
        )

    async def cancel(self, run_id: str) -> None:
        await runs.cancel_async(
            runs.marked_async_request(self._http, timeout=_CANCEL_TIMEOUT_S), run_id
        )

    def _socket(
        self, run_id: str, headers: dict[str, str]
    ) -> AbstractAsyncContextManager[async_ws.ClientConnection]:
        return async_ws.connect(
            events_url(self._engine_url, run_id),
            additional_headers=headers,
            open_timeout=30,
            close_timeout=_CLOSE_TIMEOUT_S,
            ping_interval=_KEEPALIVE_PING_S,
            max_size=_MAX_FRAME_BYTES,
            ssl=self._ssl,
        )


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


__all__ = ["AsyncRunClient", "FollowTimings", "RunClient", "events_url"]

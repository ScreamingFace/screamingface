"""Following a Run on its one event stream, `GET /runs/{id}/events` (E5 P2 spec §4.2, D13, D15).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, one connection shows me every
Candidate of my Run as it runs, survives a dropped connection, and tells me how to pick the Run
up again when my sign-in expires overnight.

The follower decodes the Run's frames and hands each to its caller; it starts nothing, and the
Candidates' outcomes come from the Engine's records (`run_record.py`). The caller opens the
socket, so this module holds the protocol alone and both transports share it.

INVARIANT (§4.2): a reconnect replays what the Engine still holds, and the follower delivers no
event and no settled Candidate twice. A gap is not an error: the stream keeps 20,000 frames per
Candidate and there is no replay request.
INVARIANT (D15): a follow that outlives the sign-in ends with how to pick the Run up; it never
starts a login of its own.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from typing import NoReturn, Protocol, cast

from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from screamingface._access.contract import _challenge_audience
from screamingface._core.ports import _ConnectionNotice, _ConnectionState
from screamingface._core.retry import _RETRYABLE_STATUS
from screamingface._engine.contract import display_event
from screamingface._engine.reconnect import _RecoveryWindow, reconnect_delay
from screamingface.errors import AuthenticationError, ExecutionError
from screamingface.events import Event

_logger = logging.getLogger(__name__)

#: WHY 90 s: inside the Engine's 120 s orphan grace (spec D10), so a follower that gets back
#: within the budget keeps an attached Run.
RECONNECT_BUDGET_S = 90.0
RECONNECT_BASE_DELAY_S = 0.5
#: The Engine sends a heartbeat every 15 s with nothing else to send, so a quiet minute is a lost
#: connection.
_RECEIVE_TIMEOUT_S = 60.0
_POLICY_VIOLATION = 1008
LOGIN_EXPIRED = "login_expired"


@dataclass(frozen=True, slots=True)
class CandidateState:
    """`pending` (waiting for a slot), `scheduled`, or `running` at its first event."""

    index: int
    state: str


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    index: int
    event: Event


@dataclass(frozen=True, slots=True)
class CandidateSettled:
    """The Candidate ended: its state, attempt, error code and record (§4.2, §4.3)."""

    index: int
    state: str
    attempt_id: str | None
    error_code: str | None
    record: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class RunEnded:
    state: str
    stopped_by: str | None


type Frame = CandidateState | CandidateEvent | CandidateSettled
type ConnectionCallback = Callable[[_ConnectionNotice], None]


class _SyncSocket(Protocol):
    def recv(self, timeout: float | None = None) -> str | bytes: ...


class _AsyncSocket(Protocol):
    async def recv(self) -> str | bytes: ...


class _HandlerRaised(Exception):
    """The caller's frame handler raised; carried past the connection-loss handling."""

    def __init__(self, original: BaseException) -> None:
        super().__init__()
        self.original = original


class _Frames:
    """Decodes one Run's frames, dropping what a reconnect repeats."""

    def __init__(self) -> None:
        self._sequences: dict[int, int] = {}
        self._settled: set[int] = set()

    def accept(self, raw: str | bytes) -> Frame | RunEnded | None:
        frame = _object(_json(raw))
        decode = {
            "candidate.state": _state,
            "candidate.event": self._event,
            "candidate.settled": self._settle,
            "run.ended": _ended,
        }.get(cast(str, frame.get("type")))
        # None: a heartbeat, or a kind newer than this Client, which has nothing to show.
        return None if decode is None else decode(frame)

    def _event(self, frame: Mapping[str, object]) -> CandidateEvent | None:
        index = _index(frame)
        try:
            event = display_event(_object(frame.get("event")))
        except ExecutionError:
            # WHY dropped, not raised: events are for display; the outcome is the record's.
            _logger.warning("An event of Candidate %d did not decode and is not shown", index)
            return None
        if event is None or event.sequence <= self._sequences.get(index, 0):
            return None
        self._sequences[index] = event.sequence
        return CandidateEvent(index, event)

    def _settle(self, frame: Mapping[str, object]) -> CandidateSettled | None:
        index = _index(frame)
        settled = CandidateSettled(
            index=index,
            state=_text(frame.get("state")),
            attempt_id=_optional_text(frame.get("attempt_id")),
            error_code=_optional_text(frame.get("error_code")),
            record=_optional_object(frame.get("record")),
        )
        if index in self._settled:
            return None
        self._settled.add(index)
        return settled


def follow_sync(
    open_socket: Callable[[], AbstractContextManager[_SyncSocket]],
    run_id: str,
    on_frame: Callable[[Frame], None],
    *,
    detached: bool,
    on_connection: ConnectionCallback | None = None,
    budget_s: float = RECONNECT_BUDGET_S,
    base_delay_s: float = RECONNECT_BASE_DELAY_S,
) -> RunEnded:
    """Follow the Run until it ends, handing each frame to ``on_frame``."""
    frames = _Frames()
    recovery = _RecoveryWindow(budget_s, started_at=time.monotonic())
    reconnecting = False
    while True:
        try:
            with open_socket() as socket:
                reconnecting = _connected(recovery, on_connection, reconnecting)
                return _pump_sync(socket, frames, on_frame)
        except _HandlerRaised as raised:
            raise raised.original from None
        except (WebSocketException, OSError, TimeoutError) as exc:
            delay = _lost(exc, recovery, run_id, detached, base_delay_s)
        _notify(on_connection, "reconnecting", recovery.attempts)
        reconnecting = True
        time.sleep(delay)


async def follow_async(
    open_socket: Callable[[], AbstractAsyncContextManager[_AsyncSocket]],
    run_id: str,
    on_frame: Callable[[Frame], None | Awaitable[None]],
    *,
    detached: bool,
    on_connection: ConnectionCallback | None = None,
    budget_s: float = RECONNECT_BUDGET_S,
    base_delay_s: float = RECONNECT_BASE_DELAY_S,
) -> RunEnded:
    """The async twin of ``follow_sync``; an awaitable ``on_frame`` is awaited."""
    frames = _Frames()
    recovery = _RecoveryWindow(budget_s, started_at=time.monotonic())
    reconnecting = False
    while True:
        try:
            async with open_socket() as socket:
                reconnecting = _connected(recovery, on_connection, reconnecting)
                return await _pump_async(socket, frames, on_frame)
        except _HandlerRaised as raised:
            raise raised.original from None
        except (WebSocketException, OSError, TimeoutError) as exc:
            delay = _lost(exc, recovery, run_id, detached, base_delay_s)
        _notify(on_connection, "reconnecting", recovery.attempts)
        reconnecting = True
        await asyncio.sleep(delay)


def _pump_sync(socket: _SyncSocket, frames: _Frames, on_frame: Callable[[Frame], None]) -> RunEnded:
    while True:
        accepted = frames.accept(socket.recv(timeout=_RECEIVE_TIMEOUT_S))
        if isinstance(accepted, RunEnded):
            return accepted
        if accepted is not None:
            try:
                on_frame(accepted)
            except BaseException as exc:
                raise _HandlerRaised(exc) from None


async def _pump_async(
    socket: _AsyncSocket, frames: _Frames, on_frame: Callable[[Frame], None | Awaitable[None]]
) -> RunEnded:
    while True:
        async with asyncio.timeout(_RECEIVE_TIMEOUT_S):
            raw = await socket.recv()
        accepted = frames.accept(raw)
        if isinstance(accepted, RunEnded):
            return accepted
        if accepted is not None:
            try:
                returned = on_frame(accepted)
                if inspect.isawaitable(returned):
                    await returned
            except BaseException as exc:
                raise _HandlerRaised(exc) from None


def _connected(
    recovery: _RecoveryWindow, on_connection: ConnectionCallback | None, reconnecting: bool
) -> bool:
    recovery.connected(time.monotonic())
    if reconnecting:
        _notify(on_connection, "reconnected")
    return False


def _lost(
    exc: BaseException, recovery: _RecoveryWindow, run_id: str, detached: bool, base_s: float
) -> float:
    """The delay before following again; raises when the follow cannot go on."""
    _raise_refusal(exc, run_id, detached)
    return _next_delay(recovery, exc, run_id, detached, base_s)


def _raise_refusal(exc: BaseException, run_id: str, detached: bool) -> None:
    """Raise when the Engine or the edge refused the follow; return for a lost connection."""
    if isinstance(exc, InvalidStatus):
        response = exc.response
        status = response.status_code
        if status in (401, 403) or _challenge_audience(status, response.headers) is not None:
            raise login_expired(run_id, detached=detached) from exc
        if status not in _RETRYABLE_STATUS:
            raise ExecutionError(
                f"The SF Engine refused to follow Run {run_id} (HTTP {status})",
                code="run_follow_refused",
                status=status,
                permanent=True,
            ) from exc
    elif isinstance(exc, ConnectionClosed):
        close = exc.rcvd
        if close is not None and close.code == _POLICY_VIOLATION:
            _raise_policy_close(close.reason, run_id, detached, exc)


def _raise_policy_close(reason: str, run_id: str, detached: bool, exc: BaseException) -> NoReturn:
    if reason == "identity_required":
        raise login_expired(run_id, detached=detached) from exc
    if reason == "run_not_found":
        raise ExecutionError(
            f"Run {run_id} is not one of yours, or no longer exists",
            code="run_not_found",
            status=404,
            permanent=True,
        ) from exc
    if reason == "runs_off":
        raise ExecutionError(
            "Runs are off on this SF Engine", code="runs_off", status=404, permanent=True
        ) from exc
    raise ExecutionError(
        f"The SF Engine refused to follow Run {run_id}", code="run_follow_refused", permanent=True
    ) from exc


def _next_delay(
    recovery: _RecoveryWindow, lost: BaseException, run_id: str, detached: bool, base_s: float
) -> float:
    now = time.monotonic()
    deadline = recovery.failed(now)
    if now >= deadline:
        raise _disconnected(run_id, detached, lost, now - recovery.started_at) from lost
    delay = reconnect_delay(recovery.attempts, base_s)
    recovery.attempts += 1
    _logger.warning("Lost the connection to Run %s; following it again in %.1fs", run_id, delay)
    return min(delay, deadline - now)


def login_expired(run_id: str, *, detached: bool) -> AuthenticationError:
    """D15: the Run never needs this sign-in, so the follow ends with how to pick it up."""
    return AuthenticationError(
        f"Your sign-in to the SF Engine has expired, so this follow of Run {run_id} ended. "
        + _what_happens(detached),
        code=LOGIN_EXPIRED,
        permanent=True,
        hint=f"Sign in again, then follow the Run with `sf.runs.get({run_id!r}).wait()`.",
    )


def _disconnected(
    run_id: str, detached: bool, lost: BaseException, elapsed_s: float
) -> ExecutionError:
    """WHY the close and the time: the close code separates the causes, and the elapsed time
    separates a size-driven failure (varies with the Report) from a duration-driven one (lands
    on the same second every time)."""
    return ExecutionError(
        f"Lost the SF Engine WebSocket of Run {run_id} after {elapsed_s:.1f}s "
        f"({_close_detail(lost)}) and could not get it back. " + _what_happens(detached),
        code="websocket_disconnected",
        permanent=False,
        hint=f"Follow the Run again with `sf.runs.get({run_id!r}).wait()`.",
    )


def _close_detail(cause: BaseException) -> str:
    """Which drop this was (OME-1141): an oversized frame, a drained proxy, a rolled Pod and a
    socket that never connected each read differently."""
    if isinstance(cause, InvalidStatus):
        detail = f"HTTP {cause.response.status_code} on connect"
    elif not isinstance(cause, ConnectionClosed):
        detail = type(cause).__name__
    # `rcvd` is the peer's close frame and `sent` is ours; whichever is present names the side
    # that decided. The client sends 1009 itself when a frame exceeds `max_size`.
    elif (close := cause.rcvd or cause.sent) is None:
        # RFC 6455 §7.1.5: the connection vanished without a close handshake.
        detail = "close 1006 abnormal closure, no close frame"
    else:
        origin = "engine sent" if cause.rcvd is not None else "client sent"
        reason = f" — {close.reason}" if close.reason else ""
        detail = f"{origin} close {close.code}{reason}"
    return detail


def _what_happens(detached: bool) -> str:
    if detached:
        return "The Run is still going on the SF Engine."
    return (
        "The Run is still going, but the SF Engine stops it once nobody has followed it for "
        "2 minutes."
    )


def _notify(
    callback: ConnectionCallback | None, state: _ConnectionState, attempt: int | None = None
) -> None:
    if callback is None:
        return
    try:
        callback(_ConnectionNotice(state, attempt))
    except Exception:  # noqa: BLE001 - INVARIANT: progress is decorative
        # A renderer defect must not end the follow of a Run that is spending.
        _logger.debug("A connection notice could not be shown", exc_info=True)


def _state(frame: Mapping[str, object]) -> CandidateState:
    return CandidateState(_index(frame), _text(frame.get("state")))


def _ended(frame: Mapping[str, object]) -> RunEnded:
    return RunEnded(_text(frame.get("state")), _optional_text(frame.get("stopped_by")))


def _json(raw: str | bytes) -> object:
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        _malformed()


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _malformed()
    return cast(Mapping[str, object], value)


def _optional_object(value: object) -> Mapping[str, object] | None:
    return None if value is None else _object(value)


def _index(frame: Mapping[str, object]) -> int:
    index = frame.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        _malformed()
    return index


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        _malformed()
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _malformed() -> NoReturn:
    raise ExecutionError(
        "The SF Engine sent a malformed Run event frame",
        code="engine_contract_error",
        permanent=True,
    )


__all__ = [
    "LOGIN_EXPIRED",
    "CandidateEvent",
    "CandidateSettled",
    "CandidateState",
    "Frame",
    "RunEnded",
    "follow_async",
    "follow_sync",
    "login_expired",
]

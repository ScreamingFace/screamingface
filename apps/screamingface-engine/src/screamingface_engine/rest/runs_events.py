"""`GET /runs/{id}/events`: one WebSocket for a whole Run (E5 P2 spec §4.2, R10).

FEATURE: a detached Run (OME-1837). STORY: as a researcher, I follow my Run from any machine: each
Candidate's state, its events while it runs, and its record when it ends; and while I follow, my
attached Run keeps going.

The route reads the registry's summary every `run_events_poll_s` and each live Candidate's event
stream itself. It holds no driver state, so any App pod serves it. On its own router, since
`RunsRoute` wraps HTTP routes only.

INVARIANT (spec §4.2): per Candidate, frames go out in order: its state, its events up to its
terminal frame, then `candidate.settled` once; `run.ended` comes after every `candidate.settled`.
INVARIANT (R10): a registry failure never closes the socket, so a database outage never orphans a
Run that is being followed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from screamingface_engine.config import Settings
from screamingface_engine.rest.runs_boundary import RUN_NOT_FOUND, RUNS_OFF, request_caller
from screamingface_engine.runs.ids import RUN_ID_PATTERN
from screamingface_engine.runs.records import (
    CandidateRecord,
    OwnerKey,
    RunRecord,
    is_terminal_candidate,
)
from screamingface_engine.runs.registry import RunRegistry
from screamingface_engine.ws.bridge import OUTBOUND_QUEUE_MAX_FRAMES
from url4.streaming.codec import encode
from url4.streaming.interfaces import EventConsumer
from url4.streaming.protocol import OutboundFrame, TerminatedEvent

_logger = logging.getLogger(__name__)

router = APIRouter()

_NORMAL = 1000
_INTERNAL_ERROR = 1011
_POLICY_VIOLATION = 1008
_TRY_AGAIN_LATER = 1013
# Why the route itself ends a follow, beside the close code.
_CLOSE_REASONS = {_POLICY_VIOLATION: RUN_NOT_FOUND}
_HEARTBEAT = '{"type":"heartbeat"}'
# How long a Candidate's `candidate.settled` waits for its terminal frame once the registry says
# it ended. WHY a bound: a subscription that stalls must not keep the follower from the record.
_FRAME_WAIT_S = 30.0


def _frame(**fields: Any) -> str:
    return json.dumps(fields, separators=(",", ":"))


def _event(index: int, event: OutboundFrame) -> str:
    # WHY spliced, not re-parsed: the CloudEvent goes out exactly as the codec wrote it (§4.2).
    return f'{{"type":"candidate.event","index":{index},"event":{encode(event).decode()}}}'


class _Follow:
    """One follower of one Run, for the life of its socket."""

    def __init__(
        self,
        ws: WebSocket,
        registry: RunRegistry,
        owner: OwnerKey,
        run_id: str,
        settings: Settings,
    ) -> None:
        self._ws = ws
        self._registry = registry
        self._owner = owner
        self._run_id = run_id
        self._settings = settings
        self._stream: EventConsumer = ws.app.state.stream
        self._job_runner = getattr(ws.app.state, "job_runner", None)
        # INVARIANT: bounded, as the topic bridge's queue: a stalled reader holds pumps back
        # instead of growing this process's memory. An `int` is the close code that ends it.
        self._out: asyncio.Queue[str | int] = asyncio.Queue(maxsize=OUTBOUND_QUEUE_MAX_FRAMES)
        self._shown: dict[int, str] = {}  # the state last sent of each Candidate seen live
        self._pumps: dict[int, asyncio.Task[None]] = {}
        self._through: set[int] = set()  # pumps that forwarded their terminal frame
        self._waiting: dict[int, float] = {}  # since when a settle waits for its frame
        self._settled: set[int] = set()
        self._stamped_at: float | None = None
        self._failing = False

    async def run(self, first: RunRecord) -> None:
        await self._stamp()
        writer = asyncio.ensure_future(self._writer())
        inbound = asyncio.ensure_future(self._inbound())
        poller = asyncio.ensure_future(self._poll(first))
        try:
            await asyncio.wait([writer, inbound], return_when=asyncio.FIRST_COMPLETED)
        finally:
            tasks = [writer, inbound, poller, *self._pumps.values()]
            for task in tasks:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
            await self._stamp()

    # --- the socket ----------------------------------------------------------------------

    async def _writer(self) -> None:
        heartbeat_s = self._settings.ws_heartbeat_s
        while True:
            try:
                item = await asyncio.wait_for(self._out.get(), timeout=heartbeat_s)
            except TimeoutError:
                item = _HEARTBEAT
            try:
                if isinstance(item, int):
                    await self._ws.close(code=item, reason=_CLOSE_REASONS.get(item))
                    return
                await self._ws.send_text(item)
            except (WebSocketDisconnect, RuntimeError):
                return

    async def _inbound(self) -> None:
        """A follower sends nothing; reading is how its leaving is noticed."""
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            while (await self._ws.receive())["type"] != "websocket.disconnect":
                pass

    # --- the registry ----------------------------------------------------------------------

    async def _poll(self, run: RunRecord | None) -> None:
        try:
            while True:
                if run is not None:
                    await self._stamp_when_due()
                    if await self._apply(run):
                        await self._out.put(_NORMAL)
                        return
                await asyncio.sleep(self._settings.run_events_poll_s)
                run = await self._read()
        except _RunGone:
            await self._out.put(_POLICY_VIOLATION)
        except Exception:
            _logger.exception("the event stream of %s failed", self._run_id)
            await self._out.put(_INTERNAL_ERROR)

    async def _read(self) -> RunRecord | None:
        """The Run's summary, or None when the registry could not answer (R10: poll again)."""
        try:
            run = await self._registry.summary(self._owner, self._run_id)
        except Exception as exc:
            self._failed(exc)
            return None
        self._failing = False
        if run is None:
            raise _RunGone  # retention deleted it while it was followed
        return run

    def _failed(self, exc: Exception) -> None:
        # WHY once per outage: the route polls every second, and the outage is one fact.
        if not self._failing:
            _logger.warning("the event stream of %s cannot read the registry", self._run_id)
            _logger.debug("the registry failure", exc_info=exc)
        self._failing = True

    async def _stamp_when_due(self) -> None:
        since = None if self._stamped_at is None else time.monotonic() - self._stamped_at
        if since is None or since >= self._settings.follow_stamp_s:
            await self._stamp()

    async def _stamp(self) -> None:
        """R10: the Run had a follower now. A stamp that fails is due again at the next poll."""
        try:
            await self._registry.followed(self._run_id, datetime.now(UTC))
        except Exception as exc:
            self._failed(exc)
            return
        self._stamped_at = time.monotonic()

    # --- the frames ------------------------------------------------------------------------

    async def _apply(self, run: RunRecord) -> bool:
        """Send what changed since the last poll; True once `run.ended` is sent."""
        ended: list[CandidateRecord] = []
        for candidate in run.candidates:
            if candidate.index in self._settled:
                continue
            if not is_terminal_candidate(candidate.state):
                await self._show(candidate)
            elif await self._ready(candidate):
                ended.append(candidate)
        if ended and not await self._settle(ended):
            return False
        if len(self._settled) < len(run.candidates):
            return False
        await self._out.put(_frame(type="run.ended", state=run.state, stopped_by=run.stopped_by))
        return True

    async def _show(self, candidate: CandidateRecord) -> None:
        """A live Candidate's state: each one's at join, then `scheduled` when it leaves
        `pending`. `running` is the pump's to send, at the Candidate's first event."""
        state = "pending" if candidate.state == "pending" else "scheduled"
        shown = self._shown.get(candidate.index)
        if shown is None or (shown == "pending" and state == "scheduled"):
            self._shown[candidate.index] = state
            await self._out.put(_frame(type="candidate.state", index=candidate.index, state=state))
        if state == "scheduled" and candidate.attempt_id is not None:
            self._pump_from(candidate.index, candidate.attempt_id)

    async def _ready(self, candidate: CandidateRecord) -> bool:
        """Whether an ended Candidate may settle: its events up to its terminal frame are sent,
        or the stream holds no terminal frame to wait for. One that ended before this follower
        saw it live settles at once, with its record and none of its past events."""
        index, topic = candidate.index, candidate.attempt_id
        if index not in self._shown or topic is None or index in self._through:
            return True
        pump = self._pumps.get(index)
        waited = time.monotonic() - self._waiting.setdefault(index, time.monotonic())
        if (pump is not None and pump.done()) or waited > _FRAME_WAIT_S:
            return True
        return not await self._frame_ahead(index, topic)

    async def _frame_ahead(self, index: int, topic: str) -> bool:
        """Whether the stream holds a terminal frame this follower has not been sent; if so, a
        pump forwards it. WHY the last frame: the runner reports its outcome only once its
        terminal frame landed (P1 R3), so a terminal frame the stream will hold is already
        there."""
        try:
            frame = await self._last_frame(topic)
        except Exception:
            return True  # it cannot tell: the next poll asks again
        if not isinstance(frame, TerminatedEvent):
            return False
        self._pump_from(index, topic)
        return True

    async def _settle(self, ended: Sequence[CandidateRecord]) -> bool:
        try:
            records = await self._registry.records(
                self._owner, self._run_id, [c.index for c in ended]
            )
        except Exception as exc:
            self._failed(exc)
            return False
        if records is None:
            raise _RunGone
        for candidate in ended:
            pump = self._pumps.pop(candidate.index, None)
            if pump is not None:
                pump.cancel()
            await self._out.put(
                _frame(
                    type="candidate.settled",
                    index=candidate.index,
                    state=candidate.state,
                    record=records.get(candidate.index),
                )
            )
            self._settled.add(candidate.index)
        return True

    async def _last_frame(self, topic: str) -> OutboundFrame | None:
        read = getattr(self._job_runner, "last_frame", None)
        return None if read is None else await read(topic)

    # --- a Candidate's events --------------------------------------------------------------

    def _pump_from(self, index: int, topic: str) -> None:
        if index not in self._pumps:
            task = asyncio.ensure_future(self._pump(index, topic))
            task.add_done_callback(_quietly)
            self._pumps[index] = task

    async def _pump(self, index: int, topic: str) -> None:
        """Forward the Candidate's events, from the oldest its stream still holds, up to its
        terminal frame."""
        async for event in self._stream.subscribe(topic, None):
            if self._shown.get(index) != "running":
                self._shown[index] = "running"
                await self._out.put(_frame(type="candidate.state", index=index, state="running"))
            await self._out.put(_event(index, event))
            if isinstance(event, TerminatedEvent):
                self._through.add(index)
                return


class _RunGone(Exception):
    """The Run is no longer the follower's to read."""


def _quietly(task: asyncio.Task[None]) -> None:
    """A pump that ended on its stream's failure: its Candidate settles without waiting."""
    if not task.cancelled() and task.exception() is not None:
        _logger.debug("a Run event pump ended", exc_info=task.exception())


async def _admitted(
    registry: RunRegistry | None, owner: OwnerKey | None, run_id: str
) -> RunRecord | tuple[int, str]:
    """The Run, for its owner; else why the follow is refused, as a close code and reason."""
    if registry is None or owner is None:
        return _POLICY_VIOLATION, RUNS_OFF if registry is None else "identity_required"
    try:
        run = await registry.summary(owner, run_id) if RUN_ID_PATTERN.fullmatch(run_id) else None
    except Exception:
        _logger.warning("the event stream of %s could not read the registry", run_id)
        return _TRY_AGAIN_LATER, "registry_unavailable"
    return (_POLICY_VIOLATION, RUN_NOT_FOUND) if run is None else run


@router.websocket("/runs/{run_id}/events")
async def run_events(websocket: WebSocket, run_id: str) -> None:
    """Closes with 1008 and the Problem's code as its reason when Runs are off (`runs_off`), the
    caller has no identity (`identity_required`), or the Run is not the caller's
    (`run_not_found`); with 1013 `registry_unavailable` when the registry cannot say whose it
    is, which a follower retries."""
    registry: RunRegistry | None = getattr(websocket.app.state, "run_registry", None)
    owner = request_caller(websocket)
    admitted = await _admitted(registry, owner, run_id)
    # WHY accept first: a close before the handshake reaches the client as a bare HTTP 403,
    # whatever its code, so a follower could not tell "retry" (1013) from "not yours" (1008).
    await websocket.accept()
    if isinstance(admitted, tuple) or registry is None or owner is None:
        code, reason = admitted if isinstance(admitted, tuple) else (_POLICY_VIOLATION, RUNS_OFF)
        await websocket.close(code=code, reason=reason)
        return
    await _Follow(websocket, registry, owner, run_id, websocket.app.state.settings).run(admitted)


__all__ = ["router"]

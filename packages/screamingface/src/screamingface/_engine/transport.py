"""SF Engine REST + WebSocket Run lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import random
import ssl
import time
from asyncio import Event as _AsyncEvent
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace as _dataclass_replace
from threading import Event as _ThreadEvent
from threading import Lock
from typing import Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from websockets.asyncio import client as async_ws
from websockets.asyncio.client import ClientConnection as AsyncClientConnection
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException
from websockets.sync import client as sync_ws
from websockets.sync.connection import Connection as SyncConnection
from websockets.typing import Subprotocol

from screamingface._access.auth import _default_caller_auth
from screamingface._access.base import _TransportAuth
from screamingface._access.contract import _challenge_audience
from screamingface._core.ports import (
    _ConnectionListener,
    _ConnectionNotice,
    _ConnectionState,
    _ResultArtifact,
    _RunOutcome,
)
from screamingface._core.retry import (
    _RETRYABLE_STATUS,
    RetryingAsyncTransport,
    RetryingTransport,
)
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.admission import _ADMISSION_BUDGET_S, _AdmissionWait
from screamingface._engine.identity import engine_headers
from screamingface._engine.reconnect import _RecoveryWindow
from screamingface._engine.run_lifecycle import _Lifecycle, _LifecycleStep
from screamingface._engine.trace import TraceContext, new_trace_context
from screamingface._evaluation.model import Candidate
from screamingface.errors import AuthenticationError, EngineUnavailableError, ExecutionError
from screamingface.events import Event

type SyncEventCallback = Callable[[Event], None]
type AsyncEventCallback = Callable[[Event], None | Awaitable[None]]
_SUBPROTOCOL = Subprotocol("cloudevents.json")
_ATTACH_RETRY_DELAYS = (0.0, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32)
_EVENT_RECEIVE_TIMEOUT_SECONDS = 120.0
# WHY: stopping happens while the caller is already interrupting. Inheriting the 30s client
# timeout would block Ctrl-C for half a minute per orphaned capability, and a user who waits
# that long presses Ctrl-C again — losing the very stop this exists to deliver.
_STOP_TIMEOUT_SECONDS = 5.0
# The Engine answers a stop for a Run it has already finished with one of these.
_ALREADY_STOPPED_STATUSES = frozenset({404, 409, 410})
# INVARIANT: this MUST stay above the Engine's INLINE result threshold plus the frame that
# carries it. The Engine sends a result body inline only up to its inline cap (default
# 1 MiB; larger results travel out-of-band as an artifact claim ticket — OME-892), wrapped
# in a CloudEvent whose `data.body` is a JSON string — escaping alone adds ~7% on a JSON
# report and can double it in the worst case, before the envelope. `websockets` defaults
# `max_size` to 2**20, which is EXACTLY the inline cap, so the default made every cap-sized
# result undeliverable: the client refused the frame with close 1009 and the Run surfaced
# as `websocket_disconnected`. Eight times the cap clears the worst-case expansion with
# room to spare, and the bound still exists so that a malformed or hostile stream cannot
# grow this process's heap without limit. An operator who raises the Engine's
# URL4_CLOUD_RESULT_INLINE_CAP_BYTES past 4 MiB must account for this client-side bound too.
_MAX_FRAME_BYTES = 8 * 1024 * 1024

# OME-1020 (spec §6 S3/S6): reconnect pacing. The budget is 90 s — STRICTLY inside the
# engine's subscriber-loss reaper grace (`orphan_grace_s = 120`, OME-890): a reconnecting
# client IS exactly the "no subscriber" the reaper waits on, so a budget at or above the
# grace lets the reaper kill the Run one attempt before the client gets back.
_RECONNECT_BUDGET_S = 90.0
_RECONNECT_BASE_DELAY_S = 0.5
_RECONNECT_MAX_DELAY_S = 15.0

# WHY explicit (review fix 6): a start may wait up to the admission budget (900 s) with no
# Run frames on its WebSocket, and an edge closes an idle WebSocket (Cloudflare: ~100 s).
# The `websockets` keepalive (sync: a background thread, `sync/connection.py` `keepalive`;
# asyncio: a task) sends a ping every interval even while the start loop blocks, and a ping
# is traffic to the edge. Its default is 20 s; naming it here makes the dependency visible
# and lets `test_admission_retry.py` prove the pings flow during a wait.
_KEEPALIVE_PING_S = 20.0

_logger = logging.getLogger(__name__)

# FEATURE (OME-1307, K3): the start header that names the cache revision a replay answers from, and
# the same header echoed on the start response as the Engine's acknowledgement.
_CACHE_REPLAY = "X-Cache-Replay"


def _reconnect_delay(
    attempt: int, base_s: float, *, max_s: float = _RECONNECT_MAX_DELAY_S
) -> float:
    """Full-jitter backoff (AWS): uniform in [0, min(cap, base * 2^attempt)]."""
    cap = min(max_s, base_s * (2**attempt))
    return random.random() * cap


class _SyncSender(Protocol):
    def send(self, message: str) -> None: ...


class _AsyncSender(Protocol):
    async def send(self, message: str) -> None: ...


class _ObserverRaised(Exception):
    """Protect a callback's original exception from transport error translation."""

    def __init__(self, original: BaseException) -> None:
        self.original = original


class Url4CloudTransport:
    """Synchronous adapter for the confirmed url4-cloud lifecycle."""

    def __init__(
        self,
        engine_url: str,
        caller_auth: _TransportAuth | None = None,
        *,
        reconnect_budget_s: float = _RECONNECT_BUDGET_S,
        reconnect_base_delay_s: float = _RECONNECT_BASE_DELAY_S,
        admission_budget_s: float = _ADMISSION_BUDGET_S,
    ) -> None:
        self._engine_url = engine_url
        self._owns_auth = caller_auth is None
        self._caller_auth = caller_auth or _default_caller_auth(engine_url)
        # WHY a retrying transport (OME-1107): a transient edge failure between the caller and
        # a healthy origin used to end the whole evaluation. Only requests the call site marked
        # `_REPLAY_SAFE` are re-sent, so `GET /?q=` — which starts billable work — never is.
        self._http = httpx.Client(
            base_url=engine_url,
            headers=engine_headers(),
            timeout=30.0,
            auth=self._caller_auth,
            transport=RetryingTransport(httpx.HTTPTransport()),
        )
        # INVARIANT: built from the same source as the client above, so the two halves of
        # this transport can never verify against different roots.
        self._ssl = _websocket_ssl_context(engine_url)
        # Test-only seams; production callers leave the defaults (spec §6 S3).
        self._reconnect_budget_s = reconnect_budget_s
        self._reconnect_base_delay_s = reconnect_base_delay_s
        self._admission_budget_s = admission_budget_s
        # Set by `cancel_active`: once the OWNER has aborted, reconnecting is pointless —
        # the sweep already stopped every Run this client owns. Cleared when the next Run
        # starts with none running (`_end_finished_abort`). WHY an Event behind `_aborted`:
        # a worker waiting for Engine capacity must wake the moment the owner aborts
        # (spec 2026-09-28 B3), not after a `Retry-After` that may be minutes long.
        self._abort = _ThreadEvent()
        self._active_lock = Lock()
        self._active_tokens: set[str] = set()
        # How many `run()` calls are in flight — NOT the registry size: a Run can leave the
        # registry before it ends. Guarded by `_active_lock`.
        self._running = 0

    @property
    def _aborted(self) -> bool:
        return self._abort.is_set()

    @_aborted.setter
    def _aborted(self, value: bool) -> None:
        if value:
            self._abort.set()
        else:
            self._abort.clear()

    def run(
        self,
        candidate: Candidate,
        on_event: SyncEventCallback | None,
    ) -> _RunOutcome:
        # INVARIANT (OME-967): the trace exists BEFORE the first outbound call. Minting the
        # capability is that first call, so a mint failure is already joinable.
        trace = new_trace_context()
        minted = [_mint_sync(self._http, trace=trace)]
        with self._active_lock:
            self._end_finished_abort()
            self._active_tokens.add(minted[0])
            self._running += 1
        lifecycle = _Lifecycle(candidate)
        started = time.monotonic()
        try:
            # WHY stamped here and not in `contract.py`: that layer decodes what the
            # Engine sent, while this id is what the CLIENT minted (OME-967). Only the
            # transport holds it, and the outcome is where a caller reads it back.
            return _dataclass_replace(
                self._run_reconnecting(lifecycle, minted, candidate, on_event, started, trace),
                trace_id=trace.trace_id,
            )
        except _ObserverRaised as exc:
            _copy_notes(exc, exc.original)
            raise exc.original
        except (WebSocketException, OSError, TimeoutError) as exc:
            raise _disconnected(exc, time.monotonic() - started) from exc
        finally:
            with self._active_lock:
                self._active_tokens.difference_update(minted)
                self._running -= 1

    def _end_finished_abort(self) -> None:
        """Clear the owner-abort flag when a Run starts and no Run is running (spec B1).

        WHY: `cancel_active` sets `_aborted` so that the Runs it swept stop reconnecting. It
        used to stay set for the Client's whole life, so after ONE Ctrl-C every later Run on
        this Client neither reconnected nor stopped its own Run after a lost stream.
        INVARIANT: while any Run is still running, the flag stays set — the Runs of that
        abort may still be unwinding. Both twins count running Runs, not registered
        capabilities, because the async sweep empties the registry while its Runs unwind.
        AIDEV-NOTE: the caller holds `_active_lock`.
        """
        if self._running == 0:
            self._aborted = False

    def _run_reconnecting(
        self,
        lifecycle: _Lifecycle,
        minted: list[str],
        candidate: Candidate,
        on_event: SyncEventCallback | None,
        started: float,
        trace: TraceContext,
    ) -> _RunOutcome:
        """Drive the Run across connection losses: BACKOFF and re-attach, bounded (spec §6 S3).

        The FIRST connection attaches fresh and starts the Run; every later connection
        resumes from the last accepted stream sequence with the SAME capability (valid for
        the Run's whole life after OME-1018). A handshake 401/403 that is not an Access
        challenge is FATAL — dead credentials, no probe on a single-engine fleet (D5). A
        connect/OS/timeout failure — or, once the Run started, a 5xx handshake refusal —
        backs off with full jitter; when the outage recovery budget
        is spent, THIS Run is stopped (never its siblings, OME-1067) and surfaces as
        `websocket_disconnected`.
        """
        recovery = _RecoveryWindow(self._reconnect_budget_s)
        run_started = False
        while True:
            try:
                with sync_ws.connect(
                    _websocket_url(self._engine_url, minted[-1]),
                    subprotocols=[_SUBPROTOCOL],
                    additional_headers={
                        **self._caller_auth.websocket_headers(),
                        **_trace_headers(trace),
                    },
                    open_timeout=30,
                    close_timeout=10,
                    ping_interval=_KEEPALIVE_PING_S,
                    max_size=_MAX_FRAME_BYTES,
                    ssl=self._ssl,
                ) as websocket:
                    _require_subprotocol(websocket.subprotocol)
                    if not run_started:
                        websocket.send(lifecycle.initial_attach())
                        self._start_run(minted[-1], candidate, trace, on_event)
                        run_started = True
                    else:
                        websocket.send(lifecycle.resume_attach())
                        _notify_connection(on_event, "reconnected")
                    recovery.connected(time.monotonic())
                    outcome = self._run_connected(websocket, lifecycle, on_event, minted)
                # FEATURE OME-892: redeem the claim ticket OUTSIDE the socket scope.
                # By now the run is over and the WS is closed — a fetch failure here
                # must surface as its own error, never trip the socket-scoped
                # stop-on-interrupt arm into writing to a dead connection.
                return _materialize_sync(self._http, outcome)
            except InvalidStatus as exc:
                if run_started and _is_transient_rejection(exc):
                    self._back_off(recovery, exc, started, on_event, minted[-1])
                else:
                    self._on_handshake_rejection(exc, minted, run_started, trace, recovery)
                    recovery.attempts += 1
            except (WebSocketException, OSError, TimeoutError) as exc:
                self._back_off(recovery, exc, started, on_event, minted[-1])

    def _start_run(
        self,
        token: str,
        candidate: Candidate,
        trace: TraceContext,
        on_event: SyncEventCallback | None,
    ) -> None:
        """Start the Run; stop it again when a replay start is not acknowledged.

        FEATURE (OME-1307, R24): the start was accepted, so an Engine that ignored the replay
        header may be running the Candidate as a paid run. Stop THIS run, then surface the error.
        """
        try:
            _start_sync(
                self._http,
                token,
                candidate.url4,
                trace=trace,
                answer_seed=candidate.answer_seed,
                cache_replay=candidate.cache_replay,
                admission=_new_admission(self._admission_budget_s, self._reconnect_base_delay_s),
                on_event=on_event,
                wait=self._abort.wait,
            )
        except ExecutionError as exc:
            if exc.code == "replay_unsupported" and not self._stop_own_run(token):
                raise _still_running(exc) from exc
            raise

    def _retire(self, minted: list[str]) -> None:
        """Take this Run's capabilities out of the owner sweep's reach."""
        with self._active_lock:
            self._active_tokens.difference_update(minted)

    def _back_off(
        self,
        recovery: _RecoveryWindow,
        exc: WebSocketException | OSError | TimeoutError,
        started: float,
        on_event: SyncEventCallback | None,
        token: str,
    ) -> None:
        """Spend one attempt of the outage budget, then announce the next connect (R4)."""
        deadline = recovery.failed(time.monotonic())
        recovery.attempts = self._on_stream_failure(
            exc, recovery.attempts, deadline, started, token
        )
        _notify_connection(on_event, "reconnecting", recovery.attempts)

    def _on_handshake_rejection(
        self,
        exc: InvalidStatus,
        minted: list[str],
        run_started: bool,
        trace: TraceContext,
        recovery: _RecoveryWindow,
    ) -> None:
        """Classify a refused handshake: Access challenge remints; anything else is FATAL.

        A non-Access 401/403 means dead credentials — retrying cannot help and no probe
        is needed on a single-engine fleet (D5). If the Run already started, stop it
        rather than orphan it (G3) — this Run only, never its siblings.
        """
        if _is_access_websocket_rejection(exc):
            if not run_started:
                self._remint_after_challenge(minted, trace)
                return
            # INVARIANT (spec 2026-09-28 F1): after the Run started, resume on the SAME
            # capability. Every mint names a NEW topic, so a fresh capability would attach
            # to a topic that holds none of this Run's frames.
            allowed_s = recovery.admit_challenge(time.monotonic())
            if allowed_s is not None:
                self._caller_auth.reauthenticate(timeout=allowed_s)
                return
            _logger.warning("SF Engine reconnect re-login limit reached; stopping the Run")
        if run_started:
            # INVARIANT (spec 2026-09-28 run isolation, C2): the refusal is about THIS
            # stream's handshake. Sibling Runs have their own sockets — stop only this one.
            self._stop_own_run(minted[-1])
        raise exc

    def _on_stream_failure(
        self,
        exc: WebSocketException | OSError | TimeoutError,
        attempts: int,
        budget_deadline: float,
        started: float,
        token: str,
    ) -> int:
        """Sleep the backoff delay, or raise the terminal disconnect error.

        WHY the abort check first: the owner's sweep (`cancel_active`) has already
        stopped every Run this client owns — reconnecting now is pointless and only
        delays the abort the user already chose (the SIGINT lands on the main thread;
        worker threads learn of it here).
        """
        if self._aborted or time.monotonic() >= budget_deadline:
            if not self._aborted:
                _logger.warning("SF Engine reconnect budget exhausted; stopping the Run")
                self._sweep_after_disconnect(token)
            raise _disconnected(exc, time.monotonic() - started) from exc
        delay = _reconnect_delay(attempts, self._reconnect_base_delay_s)
        _logger.warning(
            "SF Engine connection lost; reconnecting in %.1fs (attempt %d)",
            delay,
            attempts + 1,
        )
        time.sleep(delay)
        return attempts + 1

    def _sweep_after_disconnect(self, token: str) -> None:
        """Stop THIS Run after its reconnect gives up (G3 OME-1020; OME-1067).

        INVARIANT (spec 2026-09-28 run isolation, C3): one lost stream stops one Run. The
        siblings are independently attached — in the 2026-09-01 incident, the sweep that
        used to live here stopped a sibling with all of its cases complete.
        AIDEV-NOTE: the name predates run isolation. `test_reconnect_recovery_window.py`
        patches it by name, so it stays; the stop is best-effort (`_stop_own_run`).
        """
        self._stop_own_run(token)

    def _stop_own_run(self, token: str) -> bool:
        """Stop ONLY the Run this capability started (spec 2026-09-28 run isolation, §4).

        WHY not `cancel_active`: that sweep stops every Run this Client owns, and it is the
        OWNER's tool — an interrupt or a shutdown. One Run that cannot continue is not a
        reason to kill healthy siblings (incident 2026-09-01, OME-1071).
        Best-effort, like the sweep: a failed stop is logged and must not mask the Run's
        own error. The capability leaves the registry first, so a later owner sweep does
        not stop it a second time.
        """
        with self._active_lock:
            self._active_tokens.discard(token)
        try:
            _stop_sync(self._http, token)
        except Exception as stop_error:  # noqa: BLE001 - see the WHY above
            _logger.warning("Stopping the SF Engine Run also failed: %s", stop_error)
            return False
        return True

    def _remint_after_challenge(self, minted: list[str], trace: TraceContext) -> None:
        """Refresh Access auth and mint a fresh capability after a WS challenge.

        Only BEFORE the Run starts: the capability in hand has not started anything yet,
        so replacing it is free. WHY replace it at all: a re-authentication can take
        minutes and the challenge may predate the last mint; a fresh capability keeps the
        start independent of how long the login took. AIDEV-NOTE: the 60 s iat window that
        first motivated this is gone (OME-1018); `test_an_access_challenge_retries_with_a_
        freshly_minted_capability` still pins the pre-start remint.
        """
        self._caller_auth.reauthenticate()
        minted.append(_mint_sync(self._http, trace=trace))
        with self._active_lock:
            self._active_tokens.add(minted[-1])

    def cancel_active(self) -> None:
        """Stop every run currently owned by this synchronous Client."""

        # WHY inside the lock: a Run starting between the flag and the snapshot could clear
        # the flag (`_end_finished_abort`) for an abort that is only now taking effect.
        with self._active_lock:
            self._aborted = True
            tokens = tuple(self._active_tokens)
        if not tokens:
            return
        with ThreadPoolExecutor(
            max_workers=len(tokens),
            thread_name_prefix="screamingface-stop",
        ) as executor:
            futures = tuple(executor.submit(_stop_sync, self._http, token) for token in tokens)
        errors: list[Exception] = []
        for future in futures:
            error = future.exception()
            if isinstance(error, Exception):
                errors.append(error)
        if errors:
            raise ExceptionGroup("Could not stop every active SF Engine Run", errors)

    def _settled(self, step: _LifecycleStep, minted: list[str]) -> _RunOutcome | None:
        """The Run's outcome if this step completed it — its capabilities retired first."""
        if step.outcome is not None:
            self._retire(minted)
        return step.outcome

    def _run_connected(
        self,
        websocket: SyncConnection,
        lifecycle: _Lifecycle,
        on_event: SyncEventCallback | None,
        minted: list[str],
    ) -> _RunOutcome:
        outcome: _RunOutcome | None = None
        try:
            while True:
                try:
                    frame = websocket.recv(timeout=_EVENT_RECEIVE_TIMEOUT_SECONDS)
                except TimeoutError as exc:
                    raise _event_stream_timeout() from exc
                step = lifecycle.accept(frame)
                if step.command is not None:
                    websocket.send(step.command)
                    continue
                # INVARIANT (spec 2026-09-28 run isolation, 4.2): once the terminal frame is
                # accepted the Run is complete, and `_settled` retires its capabilities NOW —
                # before the caller's callback for this frame, the socket close and the
                # artifact fetch — so no stop, own or owner sweep, can reach a finished Run.
                outcome = self._settled(step, minted)
                if step.event is not None and on_event is not None:
                    _observe_sync(on_event, step.event)
                if outcome is not None:
                    return outcome
        # WHY: interruption must stop otherwise-invisible paid work — but a complete Run is
        # not running, so a callback that raises on its terminal frame sends no stop.
        except BaseException as exc:
            if outcome is None:
                _record_stop_failure(exc, _try_send_sync(websocket, lifecycle.stop()))
            raise

    def close(self) -> None:
        try:
            self._http.close()
        finally:
            if self._owns_auth:
                self._caller_auth.close()


class AsyncUrl4CloudTransport:
    """Asynchronous adapter with the same lifecycle semantics.

    INVARIANT: one instance is driven by exactly one event loop — ``httpx.AsyncClient`` is
    loop-bound after first use — so ``_active_tokens`` needs no lock. Every read and write of
    it happens with no ``await`` in between, which makes the region atomic already; an
    ``asyncio.Lock`` would introduce the suspension points it is meant to protect against.
    AIDEV-NOTE: the asymmetry with the synchronous twin's ``threading.Lock`` is deliberate.
    That one is genuinely required, because a thread pool drives it.
    """

    def __init__(
        self,
        engine_url: str,
        caller_auth: _TransportAuth | None = None,
        *,
        reconnect_budget_s: float = _RECONNECT_BUDGET_S,
        reconnect_base_delay_s: float = _RECONNECT_BASE_DELAY_S,
        admission_budget_s: float = _ADMISSION_BUDGET_S,
    ) -> None:
        self._engine_url = engine_url
        self._owns_auth = caller_auth is None
        self._caller_auth = caller_auth or _default_caller_auth(engine_url)
        # See the synchronous twin: retry is gated on `_REPLAY_SAFE`, never on the method.
        self._http = httpx.AsyncClient(
            base_url=engine_url,
            headers=engine_headers(),
            timeout=30.0,
            auth=self._caller_auth,
            transport=RetryingAsyncTransport(httpx.AsyncHTTPTransport()),
        )
        # INVARIANT: see the synchronous twin — one trust store for HTTP and WebSocket.
        self._ssl = _websocket_ssl_context(engine_url)
        # Test-only seams; production callers leave the defaults (spec §6 S3).
        self._reconnect_budget_s = reconnect_budget_s
        self._reconnect_base_delay_s = reconnect_base_delay_s
        self._admission_budget_s = admission_budget_s
        # Set by `cancel_active`: once the OWNER has aborted, reconnecting is pointless —
        # the sweep already stopped every Run this client owns. Cleared as in the sync
        # twin; an Event for the same reason. One loop per instance, no lock (class
        # INVARIANT). AIDEV-NOTE: imported by name, not via `asyncio.`, because tests
        # replace this module's `asyncio` with a namespace of `sleep` and `wait_for` only.
        self._abort = _AsyncEvent()
        self._active_tokens: set[str] = set()
        # In-flight `run()` calls; see the sync twin (spec 4.3).
        self._running = 0

    @property
    def _aborted(self) -> bool:
        return self._abort.is_set()

    @_aborted.setter
    def _aborted(self, value: bool) -> None:
        if value:
            self._abort.set()
        else:
            self._abort.clear()

    async def _wait_unless_aborted(self, delay: float) -> bool:
        """Wait `delay` seconds; True at once if the owner aborts meanwhile (spec B3)."""
        try:
            await asyncio.wait_for(self._abort.wait(), timeout=delay)
        except TimeoutError:
            return False
        return True

    async def cancel_active(self) -> None:
        """Stop every Run currently owned by this asynchronous Client."""

        self._aborted = True
        tokens = tuple(self._active_tokens)
        if not tokens:
            return
        # Retiring them here bounds the registry: a cancelled Run deliberately leaves its
        # capability behind, and this sweep is what owns clearing it.
        self._active_tokens.clear()
        results = await asyncio.gather(
            *(_stop_async(self._http, token) for token in tokens),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, Exception)]
        # INVARIANT: a CancelledError returned by gather is not an ordinary stop failure and
        # must not be reported as one — re-raise it so the interruption keeps propagating.
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result
        if errors:
            raise ExceptionGroup("Could not stop every active SF Engine Run", errors)

    async def run(
        self,
        candidate: Candidate,
        on_event: AsyncEventCallback | None,
    ) -> _RunOutcome:
        # INVARIANT (OME-967): see the sync twin — the trace precedes the first call.
        trace = new_trace_context()
        minted = [await _mint_async(self._http, trace=trace)]
        self._end_finished_abort()
        self._active_tokens.add(minted[0])
        self._running += 1
        cancelled = False
        started = time.monotonic()
        lifecycle = _Lifecycle(candidate)
        try:
            return _dataclass_replace(
                await self._run_reconnecting(
                    lifecycle, minted, candidate, on_event, started, trace
                ),
                trace_id=trace.trace_id,
            )
        # WHY: a cancelled Run keeps its capability registered so the Evaluation's sweep can
        # still stop it. asyncio.gather cancels its children and only re-raises once they have
        # all unwound, so by the time the sweep runs every Run here has already finished its
        # own cleanup — retiring the capability on this path would hand the sweep an empty
        # registry and silently orphan paid work. The sweep clears what it stops.
        # AIDEV-NOTE: the synchronous twin does not need this. Its sibling worker threads are
        # still mid-Run when the sweep reads the registry.
        except asyncio.CancelledError:
            cancelled = True
            raise
        except _ObserverRaised as exc:
            _copy_notes(exc, exc.original)
            raise exc.original
        except (WebSocketException, OSError, TimeoutError) as exc:
            raise _disconnected(exc, time.monotonic() - started) from exc
        finally:
            self._running -= 1
            if not cancelled:
                self._retire(minted)

    async def _start_run(
        self,
        token: str,
        candidate: Candidate,
        trace: TraceContext,
        on_event: AsyncEventCallback | None,
    ) -> None:
        """Async twin of the sync `_start_run`."""
        try:
            await _start_async(
                self._http,
                token,
                candidate.url4,
                trace=trace,
                answer_seed=candidate.answer_seed,
                cache_replay=candidate.cache_replay,
                admission=_new_admission(self._admission_budget_s, self._reconnect_base_delay_s),
                on_event=on_event,
                wait=self._wait_unless_aborted,
            )
        except ExecutionError as exc:
            if exc.code == "replay_unsupported" and not await self._stop_own_run(token):
                raise _still_running(exc) from exc
            raise

    def _retire(self, minted: list[str]) -> None:
        """Async twin of the sync `_retire`; no lock (class INVARIANT)."""
        self._active_tokens.difference_update(minted)

    def _end_finished_abort(self) -> None:
        """Async twin of the sync `_end_finished_abort` (spec B1); no lock (class INVARIANT)."""
        if self._running == 0:
            self._aborted = False

    async def _run_reconnecting(
        self,
        lifecycle: _Lifecycle,
        minted: list[str],
        candidate: Candidate,
        on_event: AsyncEventCallback | None,
        started: float,
        trace: TraceContext,
    ) -> _RunOutcome:
        """Async twin of the sync reconnecting loop — see its docstring (spec §6 S3)."""
        recovery = _RecoveryWindow(self._reconnect_budget_s)
        run_started = False
        while True:
            try:
                async with async_ws.connect(
                    _websocket_url(self._engine_url, minted[-1]),
                    subprotocols=[_SUBPROTOCOL],
                    additional_headers={
                        **(await self._caller_auth.websocket_headers_async()),
                        **_trace_headers(trace),
                    },
                    open_timeout=30,
                    close_timeout=10,
                    ping_interval=_KEEPALIVE_PING_S,
                    max_size=_MAX_FRAME_BYTES,
                    ssl=self._ssl,
                ) as websocket:
                    _require_subprotocol(websocket.subprotocol)
                    if not run_started:
                        await websocket.send(lifecycle.initial_attach())
                        await self._start_run(minted[-1], candidate, trace, on_event)
                        run_started = True
                    else:
                        await websocket.send(lifecycle.resume_attach())
                        _notify_connection(on_event, "reconnected")
                    recovery.connected(time.monotonic())
                    outcome = await self._run_connected(websocket, lifecycle, on_event, minted)
                # FEATURE OME-892: redeem outside the socket scope — see the sync twin.
                return await _materialize_async(self._http, outcome)
            except InvalidStatus as exc:
                if run_started and _is_transient_rejection(exc):
                    await self._back_off(recovery, exc, started, on_event, minted[-1])
                else:
                    await self._on_handshake_rejection(exc, minted, run_started, trace, recovery)
                    recovery.attempts += 1
            except (WebSocketException, OSError, TimeoutError) as exc:
                await self._back_off(recovery, exc, started, on_event, minted[-1])

    async def _back_off(
        self,
        recovery: _RecoveryWindow,
        exc: WebSocketException | OSError | TimeoutError,
        started: float,
        on_event: AsyncEventCallback | None,
        token: str,
    ) -> None:
        """Async twin of the sync `_back_off`."""
        deadline = recovery.failed(time.monotonic())
        recovery.attempts = await self._on_stream_failure(
            exc, recovery.attempts, deadline, started, token
        )
        _notify_connection(on_event, "reconnecting", recovery.attempts)

    async def _on_handshake_rejection(
        self,
        exc: InvalidStatus,
        minted: list[str],
        run_started: bool,
        trace: TraceContext,
        recovery: _RecoveryWindow,
    ) -> None:
        """Async twin of the sync handshake classification — see its docstring (D5, G3)."""
        if _is_access_websocket_rejection(exc):
            if not run_started:
                await self._caller_auth.reauthenticate_async()
                # WHY a NEW capability before the start: see the sync `_remint_after_challenge`.
                minted.append(await _mint_async(self._http, trace=trace))
                self._active_tokens.add(minted[-1])
                return
            # INVARIANT (spec 2026-09-28 F1): see the sync twin — the SAME capability, and a
            # re-login bounded by the outage budget and the challenge cap.
            allowed_s = recovery.admit_challenge(time.monotonic())
            if allowed_s is not None:
                await self._caller_auth.reauthenticate_async(timeout=allowed_s)
                return
            _logger.warning("SF Engine reconnect re-login limit reached; stopping the Run")
        if run_started:
            # INVARIANT (spec 2026-09-28 run isolation, C2): see the sync twin.
            await self._stop_own_run(minted[-1])
        raise exc

    async def _on_stream_failure(
        self,
        exc: WebSocketException | OSError | TimeoutError,
        attempts: int,
        budget_deadline: float,
        started: float,
        token: str,
    ) -> int:
        """Async twin of the sync backoff/terminal decision — see its docstring."""
        if self._aborted or time.monotonic() >= budget_deadline:
            if not self._aborted:
                _logger.warning("SF Engine reconnect budget exhausted; stopping the Run")
                await self._sweep_after_disconnect(token)
            raise _disconnected(exc, time.monotonic() - started) from exc
        delay = _reconnect_delay(attempts, self._reconnect_base_delay_s)
        _logger.warning(
            "SF Engine connection lost; reconnecting in %.1fs (attempt %d)",
            delay,
            attempts + 1,
        )
        await asyncio.sleep(delay)
        return attempts + 1

    async def _sweep_after_disconnect(self, token: str) -> None:
        """Async twin of the sync `_sweep_after_disconnect`: THIS Run only (C3)."""
        await self._stop_own_run(token)

    async def _stop_own_run(self, token: str) -> bool:
        """Async twin of the sync `_stop_own_run` — this Run only, best-effort."""
        self._active_tokens.discard(token)
        try:
            await _stop_async(self._http, token)
        except Exception as stop_error:  # noqa: BLE001 - see the sync twin
            _logger.warning("Stopping the SF Engine Run also failed: %s", stop_error)
            return False
        return True

    def _settled(self, step: _LifecycleStep, minted: list[str]) -> _RunOutcome | None:
        """The Run's outcome if this step completed it — its capabilities retired first."""
        if step.outcome is not None:
            self._retire(minted)
        return step.outcome

    async def _run_connected(
        self,
        websocket: AsyncClientConnection,
        lifecycle: _Lifecycle,
        on_event: AsyncEventCallback | None,
        minted: list[str],
    ) -> _RunOutcome:
        outcome: _RunOutcome | None = None
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=_EVENT_RECEIVE_TIMEOUT_SECONDS,
                    )
                except TimeoutError as exc:
                    raise _event_stream_timeout() from exc
                step = lifecycle.accept(frame)
                if step.command is not None:
                    await websocket.send(step.command)
                    continue
                # INVARIANT (spec 4.2): see the sync twin. This also keeps a completed Run off
                # the list a CANCELLED Run leaves behind for the sweep.
                outcome = self._settled(step, minted)
                if step.event is not None and on_event is not None:
                    await _observe_async(on_event, step.event)
                if outcome is not None:
                    return outcome
        # WHY: cancellation must stop otherwise-invisible paid work — not a complete Run.
        except BaseException as exc:
            if outcome is None:
                stop_error = await _try_send_async(websocket, lifecycle.stop())
                _record_stop_failure(exc, stop_error)
            raise

    async def close(self) -> None:
        try:
            await self._http.aclose()
        finally:
            if self._owns_auth:
                await asyncio.to_thread(self._caller_auth.close)


def _observe_sync(callback: SyncEventCallback, event: Event) -> None:
    try:
        callback(event)
    # WHY: preserve arbitrary application callback errors and interruptions without translation.
    except BaseException as exc:
        raise _ObserverRaised(exc) from exc


async def _observe_async(callback: AsyncEventCallback, event: Event) -> None:
    try:
        returned = callback(event)
        if inspect.isawaitable(returned):
            await returned
    # WHY: preserve arbitrary application callback errors and cancellation without translation.
    except BaseException as exc:
        raise _ObserverRaised(exc) from exc


def _notify_connection(
    on_event: object, state: _ConnectionState, attempt: int | None = None
) -> None:
    """Tell the built-in progress output about one reconnect step (spec 2026-09-28 R4).

    Sent after the backoff sleep, right before the connect it announces, so the line reads
    true: attempt n is under way. A plain `on_event` function is not a listener and gets
    nothing — the public Event stream is unchanged.
    """
    if not isinstance(on_event, _ConnectionListener):
        return
    try:
        on_event.connection(_ConnectionNotice(state=state, attempt=attempt))
    # WHY: progress is decorative; a renderer defect must never end a paid Run.
    except Exception:  # noqa: BLE001 - see the WHY above
        _logger.warning("ScreamingFace progress could not show a reconnect step", exc_info=True)


def _event_stream_timeout() -> ExecutionError:
    return ExecutionError(
        "SF Engine Run event stream stopped responding",
        code="event_stream_timeout",
        permanent=False,
    )


def _mint_sync(http: httpx.Client, *, trace: TraceContext | None = None) -> str:
    # AIDEV-NOTE (OME-967): `trace` is keyword-with-default so the capability mint stays
    # callable without one (artifact redemption, and a prior contract test). The RUN path
    # always passes it — minting is the first outbound call, and a mint failure is one of
    # the three pre-first-frame classes this ticket exists to make joinable.
    try:
        response = http.post(
            "/token", headers=_trace_headers(trace), extensions={_REPLAY_SAFE: True}
        )
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            "Could not reach the SF Engine capability endpoint",
            engine_url=_http_origin(http),
            trace_id=trace.trace_id if trace else None,
        ) from exc
    return _token(response)


async def _mint_async(http: httpx.AsyncClient, *, trace: TraceContext | None = None) -> str:
    try:
        response = await http.post(
            "/token", headers=_trace_headers(trace), extensions={_REPLAY_SAFE: True}
        )
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            "Could not reach the SF Engine capability endpoint",
            engine_url=_http_origin(http),
            trace_id=trace.trace_id if trace else None,
        ) from exc
    return _token(response)


def _token(response: httpx.Response) -> str:
    _require_success(response, "mint an execution capability")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExecutionError("SF Engine capability response must be JSON") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"token"}
        or not isinstance(payload["token"], str)
        or not payload["token"].strip()
    ):
        raise ExecutionError("SF Engine capability response is malformed")
    return payload["token"].strip()


def _start_sync(
    http: httpx.Client,
    token: str,
    url4: str,
    *,
    trace: TraceContext | None = None,
    answer_seed: int | None = None,
    cache_replay: str | None = None,
    admission: _AdmissionWait | None = None,
    on_event: object = None,
    wait: Callable[[float], bool] | None = None,
) -> None:
    """Start the Run; while the Engine has no free capacity (503), wait and send it again.

    FEATURE OME-1066: a 503 on start schedules nothing (spec 2026-09-28 E3), so the SAME
    start is re-sent after the Engine's `Retry-After`, inside one bounded budget. `wait`
    returns True when the owner aborted meanwhile — then the start is never re-sent (B3).
    AIDEV-NOTE: the defaults keep the old call shape (`_start_sync(http, token, url4)`)
    valid for direct callers; the transport always passes all three.
    """
    admission = admission or _new_admission(_ADMISSION_BUDGET_S, _RECONNECT_BASE_DELAY_S)
    wait = wait or _sleep_unaborted
    trace_id = trace.trace_id if trace else None
    while True:
        response = _send_start_sync(
            http, token, url4, trace=trace, answer_seed=answer_seed, cache_replay=cache_replay
        )
        delay = _readmission_delay(response, admission, trace_id)
        if delay is None:
            break
        _notify_connection(on_event, "waiting_for_capacity", admission.attempts)
        if wait(delay):
            raise _start_abandoned(trace_id)
    _finish_start(response, admission, on_event, trace_id)
    _require_replay_ack(response, cache_replay, trace_id)


def _send_start_sync(
    http: httpx.Client,
    token: str,
    url4: str,
    *,
    trace: TraceContext | None,
    answer_seed: int | None,
    cache_replay: str | None = None,
) -> httpx.Response:
    """One start request, re-sent only while the WebSocket attach is still registering."""
    for delay in _ATTACH_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            response = http.get(
                "/",
                params={"q": url4},
                headers={
                    "URL4-Capability": token,
                    "Prefer": "respond-async",
                    **_trace_headers(trace),
                    **_answer_seed_header(answer_seed),
                    **_cache_replay_header(cache_replay),
                },
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(
                "Could not start the SF Engine Run",
                engine_url=_http_origin(http),
                trace_id=trace.trace_id if trace else None,
            ) from exc
        if not _attachment_is_still_registering(response):
            break
    return response


# The Engine's answer when it did not admit a start (OME-1091, #1098) — and ONLY this status
# means "not admitted": another 5xx keeps failing at once (OME-1066 acceptance).
_NOT_ADMITTED = 503


def _is_engine_refusal(response: httpx.Response) -> bool:
    """A 503 the ENGINE wrote: RFC 9457 problem+json carrying `Retry-After`.

    INVARIANT (review fix 1): only the Engine's own refusal proves nothing was scheduled
    (spec E3). An edge proxy's 503 (Envoy "reset before headers", an HTML page) may hide a
    start the Engine took, so it is not re-sent — it stays today's fatal error.
    """
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    return (
        response.status_code == _NOT_ADMITTED
        and media_type == "application/problem+json"
        and "retry-after" in response.headers
    )


def _readmission_delay(
    response: httpx.Response, admission: _AdmissionWait, trace_id: str | None
) -> float | None:
    """Seconds to wait before re-sending the start, or None when `response` ends the loop.

    Raises the not-admitted error once the budget is spent. Shared by both twins.
    """
    if not _is_engine_refusal(response):
        return None
    delay = admission.next_delay(response, now=time.monotonic())
    if delay is None:
        raise _not_admitted(response, admission.waited_s(now=time.monotonic()), trace_id)
    return delay


def _finish_start(
    response: httpx.Response,
    admission: _AdmissionWait,
    on_event: object,
    trace_id: str | None,
) -> None:
    """Accept the start's final answer, and tell the progress output it was admitted.

    INVARIANT (review fix 1): after a re-send, `409 a run already exists` is THIS Run. One
    capability names one topic, so the only run there is one that an earlier attempt
    scheduled although its answer was a refusal (a queue-unavailable 503 after a publish
    whose ack was lost). Raising here would drop the capability unstopped and leave a paid
    Run with no reader; the WebSocket is already attached to its topic, so read it instead.
    """
    if not (admission.attempts and response.status_code == 409):
        _accepted(response, trace_id=trace_id)
    if admission.attempts:
        _notify_connection(on_event, "admitted")


def _new_admission(budget_s: float, base_delay_s: float) -> _AdmissionWait:
    """The ONE place a start's capacity wait is set up (both twins, and direct callers).

    The floor and the fallback backoff reuse the reconnect pacing: the same full-jitter
    helper, so a start and a reconnect back off alike.
    """
    return _AdmissionWait(
        budget_s=budget_s,
        floor_s=base_delay_s,
        backoff=lambda attempt: _reconnect_delay(attempt, base_delay_s),
    )


def _sleep_unaborted(delay: float) -> bool:
    time.sleep(delay)
    return False


async def _sleep_unaborted_async(delay: float) -> bool:
    await asyncio.sleep(delay)
    return False


def _not_admitted(
    response: httpx.Response, waited_s: float, trace_id: str | None
) -> ExecutionError:
    """The Engine kept refusing the start until the budget ran out (OME-1066).

    INVARIANT: a capacity refusal names Engine capacity — not a generic transport failure —
    so a researcher knows that waiting (or fewer Candidates at once) is the remedy. Any
    other refusal (a run-queue outage, #1098) says what the Engine said and nothing more.
    """
    detail, _code, problem = _problem_parts(response)
    if "capacity" in detail.casefold():
        return ExecutionError(
            f"SF Engine run capacity stayed full for {waited_s:.0f} s, so the Run did not "
            f"start: {detail}",
            code="engine_at_capacity",
            status=response.status_code,
            permanent=False,
            details=problem,
            hint="The Engine is busy with other Runs. Retry later, or evaluate fewer "
            "Candidates at once.",
            trace_id=trace_id,
        )
    return ExecutionError(
        f"SF Engine did not admit the Run for {waited_s:.0f} s: {detail}",
        code="engine_not_admitted",
        status=response.status_code,
        permanent=False,
        details=problem,
        hint="The Engine could not queue the Run. Retry later.",
        trace_id=trace_id,
    )


def _start_abandoned(trace_id: str | None) -> ExecutionError:
    return ExecutionError(
        "SF Engine Run start was abandoned because the Client stopped its Runs",
        code="run_aborted",
        trace_id=trace_id,
    )


def _stop_sync(http: httpx.Client, token: str) -> None:
    try:
        response = http.delete(
            "/",
            headers={"URL4-Capability": token},
            extensions={_REPLAY_SAFE: True},
            timeout=_STOP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            "Could not stop the SF Engine Run",
            engine_url=_http_origin(http),
        ) from exc
    _require_stopped(response)


async def _stop_async(http: httpx.AsyncClient, token: str) -> None:
    try:
        response = await http.delete(
            "/",
            headers={"URL4-Capability": token},
            extensions={_REPLAY_SAFE: True},
            timeout=_STOP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            "Could not stop the SF Engine Run",
            engine_url=_http_origin(http),
        ) from exc
    _require_stopped(response)


def _require_stopped(response: httpx.Response) -> None:
    """Treat an already-finished Run as a stopped Run.

    WHY: the in-band ai.url4.stop frame usually wins the race, so this REST fallback
    routinely arrives after the Run is already gone. "It is not running" is the outcome the
    caller asked for, not an error worth attaching to their interruption.
    """

    if response.status_code in _ALREADY_STOPPED_STATUSES:
        return
    _require_success(response, "stop the Run")


async def _start_async(
    http: httpx.AsyncClient,
    token: str,
    url4: str,
    *,
    trace: TraceContext | None = None,
    answer_seed: int | None = None,
    cache_replay: str | None = None,
    admission: _AdmissionWait | None = None,
    on_event: object = None,
    wait: Callable[[float], Awaitable[bool]] | None = None,
) -> None:
    """Async twin of `_start_sync` — the same capacity wait (OME-1066)."""
    admission = admission or _new_admission(_ADMISSION_BUDGET_S, _RECONNECT_BASE_DELAY_S)
    wait = wait or _sleep_unaborted_async
    trace_id = trace.trace_id if trace else None
    while True:
        response = await _send_start_async(
            http, token, url4, trace=trace, answer_seed=answer_seed, cache_replay=cache_replay
        )
        delay = _readmission_delay(response, admission, trace_id)
        if delay is None:
            break
        _notify_connection(on_event, "waiting_for_capacity", admission.attempts)
        if await wait(delay):
            raise _start_abandoned(trace_id)
    _finish_start(response, admission, on_event, trace_id)
    _require_replay_ack(response, cache_replay, trace_id)


async def _send_start_async(
    http: httpx.AsyncClient,
    token: str,
    url4: str,
    *,
    trace: TraceContext | None,
    answer_seed: int | None,
    cache_replay: str | None = None,
) -> httpx.Response:
    """Async twin of `_send_start_sync`."""
    for delay in _ATTACH_RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            response = await http.get(
                "/",
                params={"q": url4},
                headers={
                    "URL4-Capability": token,
                    "Prefer": "respond-async",
                    **_trace_headers(trace),
                    **_answer_seed_header(answer_seed),
                    **_cache_replay_header(cache_replay),
                },
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(
                "Could not start the SF Engine Run",
                engine_url=_http_origin(http),
                trace_id=trace.trace_id if trace else None,
            ) from exc
        if not _attachment_is_still_registering(response):
            break
    return response


def _answer_seed_header(answer_seed: int | None) -> dict[str, str]:
    """The run's declared sitting as its start header — nothing at all when undeclared.

    INVARIANT (OME-1193): absence is the default. An unseeded run's start request must be
    byte-identical to today's, mirroring the engine's own rule; the engine reads the header
    per OME-1038 and stamps the seed onto every answer call the run makes.
    """
    if answer_seed is None:
        return {}
    return {"X-Answer-Seed": str(answer_seed)}


def _cache_replay_header(cache_replay: str | None) -> dict[str, str]:
    """The cache revision a replay must answer from as its start header; nothing for a normal run.

    INVARIANT (OME-1307): absence is the default, as for the answer seed. Only `reproduce` sets it.
    """
    if cache_replay is None:
        return {}
    return {_CACHE_REPLAY: cache_replay}


def _require_replay_ack(
    response: httpx.Response, cache_replay: str | None, trace_id: str | None
) -> None:
    """A replay start must be echoed back with its own label (K3, R24).

    WHY: an Engine that predates replay ignores `X-Cache-Replay` and runs the Candidate as a normal,
    paid run. The echo is the Engine saying it took the header. A missing or different echo ends the
    start; the caller stops the run it just started.
    """
    if cache_replay is not None and response.headers.get(_CACHE_REPLAY) != cache_replay:
        raise ExecutionError(
            "SF Engine did not acknowledge the cache replay, so the Run was stopped",
            code="replay_unsupported",
            permanent=True,
            trace_id=trace_id,
        )


def _still_running(exc: ExecutionError) -> ExecutionError:
    """The unacknowledged replay's error, told that the stop failed too (R24).

    INVARIANT: the user is told. An Engine that ignored the replay header may be running the
    Candidate as a paid run, and this stop was the only thing meant to end it.
    """
    return ExecutionError(
        f"{exc.message}, and stopping it failed: the run may still be running on the Engine",
        code="replay_unsupported",
        permanent=True,
        hint="Stop the run from the Engine if you can. It may still spend provider money.",
        trace_id=exc.trace_id,
    )


def _attachment_is_still_registering(response: httpx.Response) -> bool:
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if response.status_code != 428 or media_type != "application/problem+json":
        return False
    try:
        problem = response.json()
    except ValueError:
        return False
    detail = problem.get("detail") if isinstance(problem, dict) else None
    return isinstance(detail, str) and "attach a websocket" in detail.casefold()


def _accepted(response: httpx.Response, *, trace_id: str | None = None) -> None:
    if response.status_code != 202:
        _raise_response(response, "start the Run", trace_id=trace_id)
    if response.headers.get("Preference-Applied") != "respond-async":
        raise ExecutionError(
            "SF Engine did not acknowledge asynchronous execution", trace_id=trace_id
        )
    if not response.headers.get("Location"):
        raise ExecutionError(
            "SF Engine asynchronous response is missing Location", trace_id=trace_id
        )


_FETCH_ARTIFACT = "fetch the Run's result artifact"


def _verified_artifact_text(artifact: _ResultArtifact, payload: bytes, digest_hex: str) -> str:
    """Admit fetched bytes as the result ONLY when they match the claim ticket exactly.

    INVARIANT: byte count and sha256 both match, or nothing downstream decodes —
    a mismatched fetch must never turn into a half-parsed Report (GitHub #642's lesson).
    """
    if len(payload) != artifact.size_bytes or digest_hex != artifact.sha256:
        raise ExecutionError(
            f"SF Engine result artifact failed integrity verification: expected "
            f"{artifact.size_bytes} bytes with sha256 {artifact.sha256}, received "
            f"{len(payload)} bytes with sha256 {digest_hex}",
            code="result_integrity_mismatch",
            permanent=True,
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExecutionError(
            "SF Engine result artifact is not UTF-8 text",
            code="result_integrity_mismatch",
            permanent=True,
        ) from exc


# WHY retry here when run start has its own delays: the run is DONE and paid for — the
# parcel sits on the server (fetching never deletes it), so a transient reset must never
# cost the outcome. Network-level failures retry; HTTP problem responses (4xx/5xx) and
# integrity mismatches are deterministic answers and do not.
_ARTIFACT_FETCH_RETRY_DELAYS = (0.0, 0.2, 0.8)


def _oversize(artifact: _ResultArtifact, received: int) -> ExecutionError:
    return ExecutionError(
        f"SF Engine result artifact exceeded its ticket: expected {artifact.size_bytes} "
        f"bytes, received at least {received}",
        code="result_integrity_mismatch",
        permanent=True,
    )


def _fetch_artifact_once_sync(http: httpx.Client, token: str, artifact: _ResultArtifact) -> str:
    """One fetch attempt. Lets `httpx.HTTPError` escape so the caller can retry it."""
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    received = 0
    with http.stream(
        "GET", f"/artifacts/{artifact.id}", headers={"URL4-Capability": token}
    ) as response:
        if not response.is_success:
            response.read()
            _raise_response(response, _FETCH_ARTIFACT)
        for chunk in response.iter_bytes():
            received += len(chunk)
            # INVARIANT: never buffer past the ticket's declared size — the ticket is
            # the memory bound, so a rogue 200 cannot OOM the researcher's process.
            if received > artifact.size_bytes:
                raise _oversize(artifact, received)
            digest.update(chunk)
            chunks.append(chunk)
    return _verified_artifact_text(artifact, b"".join(chunks), digest.hexdigest())


def _materialize_sync(http: httpx.Client, outcome: _RunOutcome) -> _RunOutcome:
    """Redeem an artifact outcome into a full `result_body` before anyone decodes it.

    INVARIANT: redemption presents a token minted AFTER the run ended, never the
    run-start token. Capability tokens live ~60 s while an evaluation can run for
    hours, so by redemption time every token minted before or during the run is
    expired — reusing one 401s and strands a paid result on the server (the
    2026-08-19 healthbench-worst30 live run, $30). The mint sits INSIDE the retry
    loop so a transient mint failure is retried like a transient fetch failure.
    """
    artifact = outcome.artifact
    if artifact is None:
        return outcome
    last_error: httpx.HTTPError | None = None
    for delay in _ARTIFACT_FETCH_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            body = _fetch_artifact_once_sync(http, _mint_sync(http), artifact)
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        return _dataclass_replace(outcome, result_body=body, artifact=None)
    raise EngineUnavailableError(
        "Could not fetch the Run's result artifact",
        engine_url=_http_origin(http),
    ) from last_error


async def _fetch_artifact_once_async(
    http: httpx.AsyncClient, token: str, artifact: _ResultArtifact
) -> str:
    """Async twin of `_fetch_artifact_once_sync`."""
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    received = 0
    async with http.stream(
        "GET", f"/artifacts/{artifact.id}", headers={"URL4-Capability": token}
    ) as response:
        if not response.is_success:
            await response.aread()
            _raise_response(response, _FETCH_ARTIFACT)
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > artifact.size_bytes:
                raise _oversize(artifact, received)
            digest.update(chunk)
            chunks.append(chunk)
    return _verified_artifact_text(artifact, b"".join(chunks), digest.hexdigest())


async def _materialize_async(http: httpx.AsyncClient, outcome: _RunOutcome) -> _RunOutcome:
    """Async twin of `_materialize_sync` — same fresh mint, same retry, same verification."""
    artifact = outcome.artifact
    if artifact is None:
        return outcome
    last_error: httpx.HTTPError | None = None
    for delay in _ARTIFACT_FETCH_RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            body = await _fetch_artifact_once_async(http, await _mint_async(http), artifact)
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        return _dataclass_replace(outcome, result_body=body, artifact=None)
    raise EngineUnavailableError(
        "Could not fetch the Run's result artifact",
        engine_url=_http_origin(http),
    ) from last_error


def _require_success(
    response: httpx.Response, operation: str, *, trace_id: str | None = None
) -> None:
    if not response.is_success:
        _raise_response(response, operation, trace_id=trace_id)


# How much of an unstructured body may reach an exception message. Long enough to carry a
# short plain-text reason, far short of a rendered error page.
_BODY_SNIPPET_LIMIT = 200


def _body_summary(response: httpx.Response) -> str:
    """A bounded, single-line stand-in for a non-`problem+json` body (OME-1107).

    WHY: this used to be `response.text.strip()` verbatim. An edge proxy answers with a full
    HTML error page, so a transient Cloudflare 520 reached the user as ~7KB of markup with the
    one useful token — the status code — buried inside it. Anything the Engine itself says
    arrives as `problem+json` and is read by the caller; everything else is an intermediary
    speaking a format we do not parse, and its bulk is noise.
    """
    status = f"HTTP {response.status_code}"
    try:
        body = response.text
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        body = ""
    collapsed = " ".join(body.split())
    # An HTML page carries no reason a human wants in a traceback — name the status and stop.
    if not collapsed or collapsed.lower().startswith(("<!doctype", "<html")):
        return status
    if len(collapsed) > _BODY_SNIPPET_LIMIT:
        collapsed = collapsed[:_BODY_SNIPPET_LIMIT].rstrip() + "…"
    return f"{status}: {collapsed}"


def _raise_response(
    response: httpx.Response, operation: str, *, trace_id: str | None = None
) -> None:
    # WHY the id reaches THIS function (OME-967): every response-derived failure funnels
    # here — mint, start, stop, artifact. A pre-first-frame failure is far more often an
    # Engine problem+json than an httpx transport error, so attaching the id only on the
    # transport branch would miss the common case.
    detail, code, details = _problem_parts(response)
    exception = AuthenticationError if response.status_code in {401, 403} else ExecutionError
    if exception is AuthenticationError:
        raise AuthenticationError(
            f"Could not {operation}: {detail}",
            code=code,
            status=response.status_code,
            permanent=True,
            details=details,
            trace_id=trace_id,
        )
    raise ExecutionError(
        f"Could not {operation}: {detail}",
        code=code,
        status=response.status_code,
        permanent=response.status_code < 500,
        details=details,
        trace_id=trace_id,
    )


def _problem_parts(response: httpx.Response) -> tuple[str, str | None, object]:
    """A failed response's (detail, code, details): the Engine's RFC 9457 fields, if any."""
    code: str | None = None
    problem: object = None
    detail = _body_summary(response)
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type != "application/problem+json":
        return detail, code, None
    try:
        problem = response.json()
    except ValueError:
        problem = None
    if isinstance(problem, dict):
        if isinstance(problem.get("detail"), str):
            detail = problem["detail"]
        if isinstance(problem.get("type"), str):
            code = problem["type"]
    return detail, code, problem


def _websocket_ssl_context(engine_url: str) -> ssl.SSLContext | None:
    """The trust store the WebSocket must use: the one the HTTP half already uses.

    WHY this cannot be left to `websockets`: given no context it builds one with
    `ssl.create_default_context()`, which trusts OpenSSL's own CA paths. `httpx` resolves
    `SSL_CERT_FILE`, then `SSL_CERT_DIR`, and otherwise falls back to the `certifi` bundle
    installed with this package. The two therefore agree only while those environment
    variables are set — and diverge in the DEFAULT case, where `httpx` trusts `certifi` and
    `websockets` trusts whatever OpenSSL was compiled to look at. A python.org macOS build
    whose ``Install Certificates.command`` was never run has nothing there at all.

    The split is invisible until it isn't: the Client mints its capability over HTTPS, which
    succeeds against `certifi`, and then fails to open a WebSocket to the SAME host with
    `SSLCertVerificationError`. A local Engine is reached over plain `ws://`, which never
    negotiates TLS, so this only ever appeared against a hosted Engine — and read as a
    property of being remote rather than a property of the trust store.

    Deferring to `httpx` rather than naming `certifi` here is deliberate: the invariant worth
    holding is that the two halves agree, including about the environment, not that either
    one trusts a particular bundle.

    Returns ``None`` for a plain-HTTP Engine, because `websockets` refuses a context on a
    ``ws://`` URI.
    """

    if urlsplit(engine_url).scheme != "https":
        return None
    return httpx.create_ssl_context()


def _websocket_url(engine_url: str, token: str) -> str:
    parts = urlsplit(engine_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/ws", urlencode({"ticket": token}), ""))


def _trace_headers(trace: TraceContext | None) -> dict[str, str]:
    """The run's trace context as headers, or nothing when there is no trace to send."""
    return trace.headers() if trace is not None else {}


def _http_origin(http: httpx.Client | httpx.AsyncClient) -> str:
    return str(http.base_url).rstrip("/")


def _is_transient_rejection(error: InvalidStatus) -> bool:
    """A handshake refusal from the edge or a restarting App, not from the credentials.

    WHY (spec 2026-08-26 §6 S3, "connect refused / 5xx / timeout -> BACKOFF"): while the
    App restarts, the edge answers the reconnect with 502/503. Treating that as FATAL
    swept every Run at exactly the moment the reconnect loop exists for.
    WHY `_RETRYABLE_STATUS` and not ">= 500": the reconnect crosses the same Cloudflare
    edge as the HTTP calls, so the same set applies (502-504, 520-524, 408, 429); 501/505
    say the server cannot speak the protocol, and waiting does not change that.
    WHY `Retry-After` is ignored here: the full-jitter backoff is already bounded by the
    outage budget, which must stay inside the engine's 120 s reaper grace — obeying a
    longer server hint would only let the reaper win.
    """
    return error.response.status_code in _RETRYABLE_STATUS


def _is_access_websocket_rejection(error: InvalidStatus) -> bool:
    # WHY: one predicate for all three call sites. This path used to accept a Location
    # carrying TWO kid parameters while the HTTP path required exactly one, and skipped the
    # audience-format check entirely.
    response = error.response
    return _challenge_audience(response.status_code, response.headers) is not None


def _require_subprotocol(selected: str | None) -> None:
    if selected != _SUBPROTOCOL:
        raise ExecutionError("SF Engine WebSocket did not negotiate cloudevents.json")


def _try_send_sync(websocket: _SyncSender, command: str) -> Exception | None:
    try:
        websocket.send(command)
    except (WebSocketException, OSError, RuntimeError) as exc:
        return exc
    return None


async def _try_send_async(websocket: _AsyncSender, command: str) -> Exception | None:
    try:
        await websocket.send(command)
    except (WebSocketException, OSError, RuntimeError) as exc:
        return exc
    return None


def _record_stop_failure(original: BaseException, stop_error: Exception | None) -> None:
    if stop_error is not None:
        original.add_note(f"SF Engine stop request also failed: {stop_error}")


def _copy_notes(source: BaseException, target: BaseException) -> None:
    for note in getattr(source, "__notes__", ()):
        target.add_note(note)


def _disconnected(cause: BaseException, elapsed_s: float) -> ExecutionError:
    """Report the disconnection with the two facts that identify which one it was.

    WHY: every cause of a dropped Run stream arrives here as the same message — an
    oversized frame, a proxy draining a listener, a rolled Pod, a refused capability. The
    close code separates them and the elapsed time separates a size-driven failure (varies
    with the Report) from a duration-driven one (lands on the same second every time).
    Without both, the error is a symptom report that no one can act on.
    """

    return ExecutionError(
        "SF Engine WebSocket disconnected before the Run completed "
        f"after {elapsed_s:.1f}s ({_close_detail(cause)})",
        code="websocket_disconnected",
        permanent=False,
    )


def _close_detail(cause: BaseException) -> str:
    if not isinstance(cause, ConnectionClosed):
        return type(cause).__name__
    # `rcvd` is the peer's close frame and `sent` is ours; whichever is present names the
    # side that decided. The client sends 1009 itself when a frame exceeds `max_size`, so
    # preferring `rcvd` alone would hide exactly that case behind "no close frame".
    close = cause.rcvd or cause.sent
    if close is None:
        # RFC 6455 §7.1.5: the connection vanished without a close handshake. Nothing on the
        # wire says 1006 — it is the code reserved for precisely this, and naming it is what
        # tells an operator to look at proxies and Pod lifetimes rather than at the Run.
        return "close 1006 abnormal closure, no close frame"
    origin = "engine sent" if cause.rcvd is not None else "client sent"
    reason = f" — {close.reason}" if close.reason else ""
    return f"{origin} close {close.code}{reason}"


__all__: list[str] = []

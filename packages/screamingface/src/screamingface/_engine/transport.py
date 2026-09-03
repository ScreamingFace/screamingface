"""SF Engine REST + WebSocket Run lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import random
import ssl
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace as _dataclass_replace
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
from screamingface._core.ports import _ResultArtifact, _RunOutcome
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.run_lifecycle import _Lifecycle
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

_logger = logging.getLogger(__name__)


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
    ) -> None:
        self._engine_url = engine_url
        self._owns_auth = caller_auth is None
        self._caller_auth = caller_auth or _default_caller_auth(engine_url)
        self._http = httpx.Client(base_url=engine_url, timeout=30.0, auth=self._caller_auth)
        # INVARIANT: built from the same source as the client above, so the two halves of
        # this transport can never verify against different roots.
        self._ssl = _websocket_ssl_context(engine_url)
        # Test-only seams; production callers leave the defaults (spec §6 S3).
        self._reconnect_budget_s = reconnect_budget_s
        self._reconnect_base_delay_s = reconnect_base_delay_s
        # Set by `cancel_active`: once the OWNER has aborted, reconnecting is pointless —
        # the sweep already stopped every Run this client owns. Plain bool, GIL-atomic.
        self._aborted = False
        self._active_lock = Lock()
        self._active_tokens: set[str] = set()

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
            self._active_tokens.add(minted[0])
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
        connect/OS/timeout failure backs off with full jitter; when the cumulative budget
        is spent, everything this client owns is stopped and the Run surfaces as
        `websocket_disconnected`.
        """
        budget_deadline = time.monotonic() + self._reconnect_budget_s
        attempts = 0
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
                    max_size=_MAX_FRAME_BYTES,
                    ssl=self._ssl,
                ) as websocket:
                    _require_subprotocol(websocket.subprotocol)
                    if not run_started:
                        websocket.send(lifecycle.initial_attach())
                        _start_sync(self._http, minted[-1], candidate.url4, trace=trace)
                        run_started = True
                    else:
                        websocket.send(lifecycle.resume_attach())
                    outcome = self._run_connected(websocket, lifecycle, on_event)
                # FEATURE OME-892: redeem the claim ticket OUTSIDE the socket scope.
                # By now the run is over and the WS is closed — a fetch failure here
                # must surface as its own error, never trip the socket-scoped
                # stop-on-interrupt arm into writing to a dead connection.
                return _materialize_sync(self._http, outcome)
            except InvalidStatus as exc:
                self._on_handshake_rejection(exc, minted, run_started, trace)
                attempts += 1
                continue
            except (WebSocketException, OSError, TimeoutError) as exc:
                attempts = self._on_stream_failure(exc, attempts, budget_deadline, started)
                continue

    def _on_handshake_rejection(
        self, exc: InvalidStatus, minted: list[str], run_started: bool, trace: TraceContext
    ) -> None:
        """Classify a refused handshake: Access challenge remints; anything else is FATAL.

        A non-Access 401/403 means dead credentials — retrying cannot help and no probe
        is needed on a single-engine fleet (D5). If the Run already started, stop it
        rather than orphan it (G3).
        """
        if _is_access_websocket_rejection(exc):
            self._remint_after_challenge(minted, trace)
            return
        if run_started:
            self._sweep_after_disconnect()
        raise exc

    def _on_stream_failure(
        self,
        exc: WebSocketException | OSError | TimeoutError,
        attempts: int,
        budget_deadline: float,
        started: float,
    ) -> int:
        """Sleep the backoff delay, or raise the terminal disconnect error.

        WHY the abort check first: the owner's sweep (`cancel_active`) has already
        stopped every Run this client owns — reconnecting now is pointless and only
        delays the abort the user already chose (the SIGINT lands on the main thread;
        worker threads learn of it here).
        """
        if self._aborted or time.monotonic() >= budget_deadline:
            if not self._aborted:
                _logger.warning("SF Engine reconnect budget exhausted; stopping Runs")
                self._sweep_after_disconnect()
            raise _disconnected(exc, time.monotonic() - started) from exc
        delay = _reconnect_delay(attempts, self._reconnect_base_delay_s)
        _logger.warning(
            "SF Engine connection lost; reconnecting in %.1fs (attempt %d)",
            delay,
            attempts + 1,
        )
        time.sleep(delay)
        return attempts + 1

    def _sweep_after_disconnect(self) -> None:
        """Stop every Run this client owns after a reconnect gives up (G3, OME-1020).

        Best-effort: a failed sweep must not mask the disconnect itself — the sweep's own
        failure is logged, not raised.
        """
        try:
            self.cancel_active()
        except Exception as stop_error:  # noqa: BLE001 - see the WHY above
            _logger.warning("Stopping active SF Engine runs also failed: %s", stop_error)

    def _remint_after_challenge(self, minted: list[str], trace: TraceContext) -> None:
        """Refresh Access auth and mint a fresh capability after a WS challenge.

        WHY a NEW capability rather than the one in hand: its iat window is 60s and the
        re-login can take minutes — see the async twin's inline comment.
        """
        self._caller_auth.reauthenticate()
        minted.append(_mint_sync(self._http, trace=trace))
        with self._active_lock:
            self._active_tokens.add(minted[-1])

    def cancel_active(self) -> None:
        """Stop every run currently owned by this synchronous Client."""

        self._aborted = True
        with self._active_lock:
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

    def _run_connected(
        self,
        websocket: SyncConnection,
        lifecycle: _Lifecycle,
        on_event: SyncEventCallback | None,
    ) -> _RunOutcome:
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
                if step.event is not None and on_event is not None:
                    _observe_sync(on_event, step.event)
                if step.outcome is not None:
                    return step.outcome
        # WHY: interruption must stop otherwise-invisible paid work.
        except BaseException as exc:
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
    ) -> None:
        self._engine_url = engine_url
        self._owns_auth = caller_auth is None
        self._caller_auth = caller_auth or _default_caller_auth(engine_url)
        self._http = httpx.AsyncClient(base_url=engine_url, timeout=30.0, auth=self._caller_auth)
        # INVARIANT: see the synchronous twin — one trust store for HTTP and WebSocket.
        self._ssl = _websocket_ssl_context(engine_url)
        # Test-only seams; production callers leave the defaults (spec §6 S3).
        self._reconnect_budget_s = reconnect_budget_s
        self._reconnect_base_delay_s = reconnect_base_delay_s
        # Set by `cancel_active`: once the OWNER has aborted, reconnecting is pointless —
        # the sweep already stopped every Run this client owns. One loop per instance;
        # plain bool, no lock (see the class INVARIANT above).
        self._aborted = False
        self._active_tokens: set[str] = set()

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
        self._active_tokens.add(minted[0])
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
            if not cancelled:
                self._active_tokens.difference_update(minted)

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
        budget_deadline = time.monotonic() + self._reconnect_budget_s
        attempts = 0
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
                    max_size=_MAX_FRAME_BYTES,
                    ssl=self._ssl,
                ) as websocket:
                    _require_subprotocol(websocket.subprotocol)
                    if not run_started:
                        await websocket.send(lifecycle.initial_attach())
                        await _start_async(self._http, minted[-1], candidate.url4, trace=trace)
                        run_started = True
                    else:
                        await websocket.send(lifecycle.resume_attach())
                    outcome = await self._run_connected(websocket, lifecycle, on_event)
                # FEATURE OME-892: redeem outside the socket scope — see the sync twin.
                return await _materialize_async(self._http, outcome)
            except InvalidStatus as exc:
                await self._on_handshake_rejection(exc, minted, run_started, trace)
                attempts += 1
                continue
            except (WebSocketException, OSError, TimeoutError) as exc:
                attempts = await self._on_stream_failure(exc, attempts, budget_deadline, started)
                continue

    async def _on_handshake_rejection(
        self, exc: InvalidStatus, minted: list[str], run_started: bool, trace: TraceContext
    ) -> None:
        """Async twin of the sync handshake classification — see its docstring (D5, G3)."""
        if _is_access_websocket_rejection(exc):
            await self._caller_auth.reauthenticate_async()
            # WHY a NEW capability rather than the one already in hand: a
            # re-authentication can take minutes, and the challenge may predate the
            # last mint. Minting is unauthenticated and per-Run, so replacing the
            # token is cheaper than widening any window.
            minted.append(await _mint_async(self._http, trace=trace))
            self._active_tokens.add(minted[-1])
            return
        if run_started:
            await self._sweep_after_disconnect()
        raise exc

    async def _on_stream_failure(
        self,
        exc: WebSocketException | OSError | TimeoutError,
        attempts: int,
        budget_deadline: float,
        started: float,
    ) -> int:
        """Async twin of the sync backoff/terminal decision — see its docstring."""
        if self._aborted or time.monotonic() >= budget_deadline:
            if not self._aborted:
                _logger.warning("SF Engine reconnect budget exhausted; stopping Runs")
                await self._sweep_after_disconnect()
            raise _disconnected(exc, time.monotonic() - started) from exc
        delay = _reconnect_delay(attempts, self._reconnect_base_delay_s)
        _logger.warning(
            "SF Engine connection lost; reconnecting in %.1fs (attempt %d)",
            delay,
            attempts + 1,
        )
        await asyncio.sleep(delay)
        return attempts + 1

    async def _sweep_after_disconnect(self) -> None:
        """Stop every Run this client owns after a reconnect gives up (G3, OME-1020).

        Best-effort: a failed sweep must not mask the disconnect itself — the sweep's own
        failure is logged, not raised.
        """
        try:
            await self.cancel_active()
        except Exception as stop_error:  # noqa: BLE001 - see the WHY above
            _logger.warning("Stopping active SF Engine runs also failed: %s", stop_error)

    async def _run_connected(
        self,
        websocket: AsyncClientConnection,
        lifecycle: _Lifecycle,
        on_event: AsyncEventCallback | None,
    ) -> _RunOutcome:
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
                if step.event is not None and on_event is not None:
                    await _observe_async(on_event, step.event)
                if step.outcome is not None:
                    return step.outcome
        # WHY: cancellation must stop otherwise-invisible paid work.
        except BaseException as exc:
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
    http: httpx.Client, token: str, url4: str, *, trace: TraceContext | None = None
) -> None:
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
    _accepted(response, trace_id=trace.trace_id if trace else None)


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
    http: httpx.AsyncClient, token: str, url4: str, *, trace: TraceContext | None = None
) -> None:
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
    _accepted(response, trace_id=trace.trace_id if trace else None)


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


def _raise_response(
    response: httpx.Response, operation: str, *, trace_id: str | None = None
) -> None:
    # WHY the id reaches THIS function (OME-967): every response-derived failure funnels
    # here — mint, start, stop, artifact. A pre-first-frame failure is far more often an
    # Engine problem+json than an httpx transport error, so attaching the id only on the
    # transport branch would miss the common case.
    code: str | None = None
    problem: object = None
    detail = response.text.strip() or f"HTTP {response.status_code}"
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type == "application/problem+json":
        try:
            problem = response.json()
        except ValueError:
            problem = None
        if isinstance(problem, dict):
            if isinstance(problem.get("detail"), str):
                detail = problem["detail"]
            if isinstance(problem.get("type"), str):
                code = problem["type"]
    exception = AuthenticationError if response.status_code in {401, 403} else ExecutionError
    if exception is AuthenticationError:
        raise AuthenticationError(
            f"Could not {operation}: {detail}",
            code=code,
            status=response.status_code,
            permanent=True,
            details=problem if media_type == "application/problem+json" else None,
            trace_id=trace_id,
        )
    raise ExecutionError(
        f"Could not {operation}: {detail}",
        code=code,
        status=response.status_code,
        permanent=response.status_code < 500,
        details=problem if media_type == "application/problem+json" else None,
        trace_id=trace_id,
    )


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

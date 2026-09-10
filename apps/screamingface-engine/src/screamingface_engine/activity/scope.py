"""Explicit operation scopes: timing, safe outcomes and joined heartbeat cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextvars import ContextVar, Token
from types import TracebackType
from uuid import uuid4

from screamingface_engine.activity.contract import (
    MAX_INTEGER,
    PREFIX,
    SCHEMA,
    TERMINAL,
    ActivityKind,
    Emitter,
    Scalar,
    facts,
    message,
    validate_state,
)
from screamingface_engine.activity.session import ActivitySession, current_session

_sleep = asyncio.sleep
_CURRENT: ContextVar[Operation | None] = ContextVar("activity_operation", default=None)


class Operation:
    def __init__(
        self,
        session: ActivitySession | None,
        emit: Emitter | None,
        kind: ActivityKind,
        values: dict[str, Scalar],
        on_heartbeat: Callable[[], None] | None,
    ) -> None:
        self._session, self._emit, self.kind = session, emit, kind
        self._facts = values
        self._on_heartbeat = on_heartbeat
        self._id = ""
        self._started = 0.0
        self._revision = 0
        self._closed = False
        self._terminal: str | None = None
        self._token: Token[Operation | None] | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._session and self._session.active and self._emit and not self._closed)

    def __enter__(self) -> Operation:
        if self.enabled:
            self._start()
        else:
            # INVARIANT: an inert nested operation must not inherit its parent's retry target.
            self._token = _CURRENT.set(None)
        return self

    def _start(self) -> None:
        try:
            assert self._session is not None
            self._id, self._started = uuid4().hex, self._session.monotonic()
            parent = _CURRENT.get()
            if parent is not None and parent.enabled and parent._session is self._session:
                self._facts[PREFIX + "parent_id"] = parent._id
            self._token = _CURRENT.set(self)
            self._record("started")
        except Exception:
            self._invalid()
            self._emit = None

    def _invalid(self) -> None:
        if self._session is not None:
            self._session.suppress("invalid")

    def _record(self, state: str) -> None:
        if not self.enabled:
            return
        try:
            self._publish(state)
        except Exception:
            self._invalid()

    def _publish(self, state: str) -> None:
        assert self._session is not None and self._emit is not None
        validate_state(self.kind, state)
        self._revision = min(MAX_INTEGER, self._revision + 1)
        attributes: dict[str, Scalar] = {
            **self._facts,
            PREFIX + "schema": SCHEMA,
            PREFIX + "kind": self.kind.value,
            PREFIX + "state": state,
            PREFIX + "id": self._id,
            PREFIX + "revision": self._revision,
            PREFIX + "elapsed_ms": max(
                0, round((self._session.monotonic() - self._started) * 1000)
            ),
            PREFIX + "observed_at_ms": int(self._session.wall() * 1000),
        }
        self._session.emit(self._emit, message(self.kind, state), attributes)

    def finish(self, *, outcome: str = "completed", **values: object) -> None:
        if not self.enabled or self._terminal is not None:
            return
        try:
            validate_state(self.kind, outcome)
            if outcome not in TERMINAL:
                raise ValueError("terminal outcome required")
            self._facts.update(facts(values))
            self._terminal = outcome
        except Exception:
            self._invalid()

    def retry(self, *, attempt: int, delay_seconds: float) -> None:
        if not self.enabled or self._terminal is not None:
            return
        try:
            self._facts.update(facts({"attempt": attempt, "retry_delay_ms": delay_seconds * 1000}))
            self._record("retrying")
        except Exception:
            self._invalid()

    async def _heartbeat(self) -> None:
        while self.enabled:
            await _sleep(60.0)
            if self.enabled and self._terminal is None:
                self._record("running")
                if self._on_heartbeat is not None:
                    self._on_heartbeat()

    async def __aenter__(self) -> Operation:
        self.__enter__()
        if self.enabled:
            heartbeat = self._heartbeat()
            try:
                self._task = asyncio.create_task(heartbeat)
            except Exception:
                heartbeat.close()
                self._invalid()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            state = self._terminal or "completed"
            if exc_type is not None:
                state = "cancelled" if issubclass(exc_type, asyncio.CancelledError) else "failed"
                if self._terminal == "refused":
                    state = "refused"
            self._record(state)
        finally:
            self._closed = True
            if self._token is not None:
                _CURRENT.reset(self._token)
                self._token = None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._task is not None:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
        finally:
            self.__exit__(exc_type, exc, tb)


def operation(
    *,
    emit: Emitter | None,
    kind: ActivityKind,
    on_heartbeat: Callable[[], None] | None = None,
    **values: object,
) -> Operation:
    session = current_session()
    if session is None or emit is None:
        return Operation(None, None, kind, {}, None)
    try:
        return Operation(session, emit, kind, facts(values), on_heartbeat)
    except Exception:
        session.suppress("invalid")
        return Operation(None, None, kind, {}, None)


def current_operation() -> Operation | None:
    op = _CURRENT.get()
    return op if op is not None and op.enabled and op._session is current_session() else None

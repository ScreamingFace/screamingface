"""Execution-owned observation ports and fault-isolated lifecycle dispatch.

Observers receive facts; they never control requests, results or retry decisions.
"""

from __future__ import annotations

import logging
import math
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager
from contextvars import ContextVar, Token
from types import TracebackType
from typing import Protocol

Scalar = str | int | float | bool | None
logger = logging.getLogger(__name__)


class LogEmitter(Protocol):
    """A caller-supplied structured sink; transport and node binding stay with its owner."""

    def __call__(
        self, body: str, attributes: Mapping[str, Scalar] | None = None, *, severity: str = "INFO"
    ) -> None: ...


class ModelObservation(Protocol):
    """Observe facts without controlling requests, retries or results.

    Close receives the original exit information and must tolerate partial startup.
    Adapters own resources; ordinary failures are contained, process control propagates.
    """

    async def start(self) -> None: ...
    async def close(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    def completed(self, finish_reason: str | None) -> None: ...
    def failed(self, code: str) -> None: ...
    def retry(self, *, attempt: int, delay_seconds: float) -> None: ...


class RunObserver(Protocol):
    """One factory-created observer per execution, reused across its inner steps.

    Each bind returns a fresh context manager that restores context on exit. Binding
    teardown receives the current step exception, but cannot suppress it or declare
    the whole run outcome; model close receives the call outcome separately.
    aclose releases run-owned resources. Callbacks must not perform execution work.
    """

    def bind(self) -> AbstractContextManager[None]: ...
    async def aclose(self) -> None: ...
    def model_call(self, model_id: str, emit: LogEmitter | None) -> ModelObservation: ...
    def bridge_loss(self, dropped: int) -> Mapping[str, Scalar]: ...


ObserverFactory = Callable[[], RunObserver]
_CURRENT: ContextVar[RunObservations | None] = ContextVar("run_observations", default=None)
_CALL: ContextVar[ModelCall | None] = ContextVar("model_observation", default=None)


def _fault(run: RunObservations | None) -> None:
    # INVARIANT: one best-effort warning per run, with no exception text or payload.
    if run is None or run.fault_reported:
        return
    run.fault_reported = True
    try:
        logger.warning("execution observer failed; execution continues")
    except Exception:
        # WHY: failure of the last-resort diagnostic must not break original work either.
        return


@contextmanager
def _guard(run: RunObservations | None) -> Iterator[None]:
    # WHY: the same guard covers synchronous callbacks and awaited callbacks.
    try:
        yield
    except Exception:
        _fault(run)


@contextmanager
def _bind(run: RunObservations, observer: RunObserver) -> Iterator[None]:
    context = None
    with _guard(run):
        candidate = observer.bind()
        candidate.__enter__()
        context = candidate
    error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        if context is not None:
            with _guard(run):
                context.__exit__(
                    type(error) if error is not None else None,
                    error,
                    error.__traceback__ if error is not None else None,
                )


class RunObservations:
    """Own observers and isolated dispatch without activity policy.

    Bind inner steps, never outward yields: generator consumers may change tasks.
    Final cleanup revokes dispatch.
    """

    def __init__(self, factories: tuple[ObserverFactory, ...]) -> None:
        self.observers: list[RunObserver] = []
        self.active = True
        self.fault_reported = False
        for factory in factories:
            with _guard(self):
                self.observers.append(factory())

    @contextmanager
    def bind(self) -> Iterator[None]:
        # INVARIANT: even an empty registration masks inherited execution observers.
        token = _CURRENT.set(self)
        try:
            with ExitStack() as stack:
                for observer in self.observers:
                    stack.enter_context(_bind(self, observer))
                yield
        finally:
            _CURRENT.reset(token)

    async def aclose(self) -> None:
        self.active = False
        for observer in reversed(self.observers):
            with _guard(self):
                await observer.aclose()


class ModelCall:
    """Bind callbacks to a call and its run; nested runs cannot target its retry.

    Observer scope exit cannot suppress the execution exception.
    """

    def __init__(self, model_id: str, emit: LogEmitter | None) -> None:
        self._run = _CURRENT.get()
        self._observers: list[ModelObservation] = []
        self._token: Token[ModelCall | None] | None = None
        self._closed = False
        if self._run is not None and self._run.active:
            for observer in self._run.observers:
                with _guard(self._run):
                    self._observers.append(observer.model_call(model_id, emit))

    async def __aenter__(self) -> ModelCall:
        self._token = _CALL.set(self)
        try:
            for observer in self._observers:
                with _guard(self._run):
                    await observer.start()
        except BaseException:
            await self.__aexit__(*sys.exc_info())
            raise
        return self

    def _notify(self, callback: Callable[[ModelObservation], None]) -> None:
        if self._closed or self._run is None or not self._run.active:
            return
        for observer in self._observers:
            with _guard(self._run):
                callback(observer)

    def completed(self, finish_reason: str | None) -> None:
        self._notify(lambda observer: observer.completed(finish_reason))

    def failed(self, code: str) -> None:
        self._notify(lambda observer: observer.failed(code))

    def retry(self, *, attempt: int, delay_seconds: float) -> None:
        self._notify(lambda observer: observer.retry(attempt=attempt, delay_seconds=delay_seconds))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            for observer in reversed(self._observers):
                with _guard(self._run):
                    await observer.close(exc_type, exc, tb)
        finally:
            self._closed = True
            if self._token is not None:
                _CALL.reset(self._token)


def current_model_call() -> ModelCall | None:
    call = _CALL.get()
    run = _CURRENT.get()
    return call if call and not call._closed and run and run.active and call._run is run else None


def bridge_loss_attributes(dropped: int) -> dict[str, Scalar]:
    attributes: dict[str, Scalar] = {}
    run = _CURRENT.get()
    if run is not None and run.active:
        for observer in run.observers:
            with _guard(run):
                snapshot = dict(observer.bridge_loss(dropped))
                if not all(_valid_attribute(k, v) for k, v in snapshot.items()):
                    raise ValueError("invalid observer attributes")
                attributes.update(snapshot)
    return attributes


def _valid_attribute(key: str, value: Scalar) -> bool:
    if isinstance(value, float):
        return isinstance(key, str) and math.isfinite(value)
    return isinstance(key, str) and (value is None or isinstance(value, (str, int)))

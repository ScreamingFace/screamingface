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
    """Observe one call without controlling its requests, retries or result.

    The dispatcher starts the observation, reports facts, then closes it with the
    original scope-exit information. Close must tolerate partially failed startup.
    Adapters own their resources; ordinary callback failures are contained, while
    cancellation and other process-control exceptions retain their semantics.
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
    cleanup is separate from operation outcomes; model close receives those errors.
    aclose releases run-owned resources. Callbacks must not perform execution work.
    """

    def bind(self) -> AbstractContextManager[None]: ...
    async def aclose(self) -> None: ...
    def model_call(self, model_id: str, emit: LogEmitter | None) -> ModelObservation: ...
    def bridge_loss(self, dropped: int) -> Mapping[str, Scalar]: ...


ObserverFactory = Callable[[], RunObserver]
_CURRENT: ContextVar[RunObservations | None] = ContextVar("run_observations", default=None)
_CALL: ContextVar[ModelCall | None] = ContextVar("model_observation", default=None)


def _fault(run: RunObservations | None = None) -> None:
    # INVARIANT: one best-effort warning per run, with no exception text or payload.
    run = run if run is not None else _CURRENT.get()
    if run is not None:
        if run.fault_reported:
            return
        run.fault_reported = True
    try:
        logger.warning("execution observer failed; execution continues")
    except Exception:
        # WHY: failure of the last-resort diagnostic must not break original work either.
        return


@contextmanager
def _bind(observer: RunObserver) -> Iterator[None]:
    try:
        context = observer.bind()
        context.__enter__()
    except Exception:
        _fault()
        yield
        return
    try:
        yield
    finally:
        try:
            context.__exit__(None, None, None)
        except Exception:
            _fault()


class RunObservations:
    """Own observer instances and isolate dispatch; no activity schema or policy.

    Bind around inner execution steps, never across an outward generator yield:
    another task may advance or close that generator. Final cleanup revokes dispatch.
    """

    def __init__(self, factories: tuple[ObserverFactory, ...]) -> None:
        self.observers: list[RunObserver] = []
        self.active = True
        self.fault_reported = False
        for factory in factories:
            try:
                self.observers.append(factory())
            except Exception:
                _fault(self)

    @contextmanager
    def bind(self) -> Iterator[None]:
        # INVARIANT: even an empty registration masks inherited execution observers.
        token = _CURRENT.set(self)
        try:
            with ExitStack() as stack:
                for observer in self.observers:
                    stack.enter_context(_bind(observer))
                yield
        finally:
            _CURRENT.reset(token)

    async def aclose(self) -> None:
        self.active = False
        for observer in reversed(self.observers):
            try:
                await observer.aclose()
            except Exception:
                _fault(self)


class ModelCall:
    """Scope observer callbacks to one call and its owning execution.

    Retry lookup checks both contexts so nested executions cannot update a parent
    call. Observer scope exit cannot suppress the execution exception.
    """

    def __init__(self, model_id: str, emit: LogEmitter | None) -> None:
        self._run = _CURRENT.get()
        self._observers: list[ModelObservation] = []
        self._token: Token[ModelCall | None] | None = None
        self._closed = False
        if self._run is not None and self._run.active:
            for observer in self._run.observers:
                try:
                    self._observers.append(observer.model_call(model_id, emit))
                except Exception:
                    _fault()

    async def __aenter__(self) -> ModelCall:
        self._token = _CALL.set(self)
        try:
            for observer in self._observers:
                try:
                    await observer.start()
                except Exception:
                    _fault()
        except BaseException:
            await self.__aexit__(*sys.exc_info())
            raise
        return self

    def _notify(self, callback: Callable[[ModelObservation], None]) -> None:
        if self._closed or self._run is None or not self._run.active:
            return
        for observer in self._observers:
            try:
                callback(observer)
            except Exception:
                _fault()

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
                try:
                    await observer.close(exc_type, exc, tb)
                except Exception:
                    _fault()
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
            try:
                snapshot = dict(observer.bridge_loss(dropped))
                if not all(_valid_attribute(k, v) for k, v in snapshot.items()):
                    raise ValueError("invalid observer attributes")
                attributes.update(snapshot)
            except Exception:
                _fault()
    return attributes


def _valid_attribute(key: str, value: Scalar) -> bool:
    return isinstance(key, str) and (
        value is None
        or isinstance(value, (str, int, bool))
        or isinstance(value, float)
        and math.isfinite(value)
    )

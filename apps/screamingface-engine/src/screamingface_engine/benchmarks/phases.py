"""Benchmark-owned phase facts; optional adapters own their interpretation and resources."""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import iscoroutinefunction
from types import TracebackType
from typing import Protocol, cast, runtime_checkable

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.observations import LogEmitter, RunObservations, current_observations
from url4.observe import current_log_sink


class PhaseScope(Protocol):
    """Inline sync hooks; async exit joins local resources without waiting for delivery.

    Exit must tolerate partially failed entry. Exit return values cannot suppress
    execution errors. Factories must defer resource acquisition until entry.
    """

    def __enter__(self) -> object: ...
    def __exit__(
        self, typ: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> object: ...
    async def __aenter__(self) -> object: ...
    async def __aexit__(
        self, typ: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> object: ...


@runtime_checkable
class PhaseObserver(Protocol):
    """Optional extension to a registered run observer. No request/result payloads cross it."""

    def phase(self, phase: ActivityKind, emit: LogEmitter | None) -> PhaseScope | None: ...


class _PhaseCall:
    def __init__(self, phase: ActivityKind, run: RunObservations) -> None:
        self.run = run
        self.scopes: list[PhaseScope] = []
        self.entered: list[PhaseScope] = []
        for observer in run.observers:
            with run.guard():
                if isinstance(observer, PhaseObserver):
                    scope = observer.phase(phase, current_log_sink())
                    if scope is not None:
                        self.scopes.append(scope)

    def __enter__(self) -> None:
        try:
            for scope in self.scopes:
                self.entered.append(scope)
                with self.run.guard():
                    scope.__enter__()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, typ, exc, tb) -> None:
        interrupted: BaseException | None = None
        for scope in reversed(self.entered):
            try:
                with self.run.guard():
                    scope.__exit__(typ, exc, tb)
            except BaseException as error:
                interrupted = interrupted or error
        if interrupted is not None:
            raise interrupted

    async def __aenter__(self) -> None:
        try:
            for scope in self.scopes:
                self.entered.append(scope)
                with self.run.guard():
                    await scope.__aenter__()
        except BaseException:
            await self.__aexit__(*sys.exc_info())
            raise

    async def __aexit__(self, typ, exc, tb) -> None:
        # INVARIANT: cancellation cannot skip other observers' scope restoration.
        # Returned truthy values never suppress the original execution exception.
        interrupted: BaseException | None = None
        for scope in reversed(self.entered):
            try:
                with self.run.guard():
                    await scope.__aexit__(typ, exc, tb)
            except BaseException as error:
                interrupted = interrupted or error
        if interrupted is not None:
            raise interrupted


def observe_phase(phase: ActivityKind):
    """Observe a whole native sync/async function using the shared phase vocabulary.

    Shared endpoint factories declare this once for all benchmark callers.
    Completion means the function returned, not that a case passed. Async work
    must be declared with async def; sync functions returning awaitables are not
    supported. The activity adapter owns records, admission and heartbeat timers.
    """

    if phase == ActivityKind.MODEL_CALL:
        raise ValueError("model calls use the model observation interface")

    def decorate[**P, R](handler: Callable[P, R]) -> Callable[P, R]:
        return _wrap_phase(phase, handler)

    return decorate


def _wrap_phase[**P, R](phase: ActivityKind, handler: Callable[P, R]) -> Callable[P, R]:
    if iscoroutinefunction(handler) or iscoroutinefunction(getattr(handler, "__call__", None)):
        async_handler = cast(Callable[P, Awaitable[object]], handler)

        @wraps(handler)
        async def async_call(*args: P.args, **kwargs: P.kwargs) -> object:
            run = current_observations()
            if run is None:
                return await async_handler(*args, **kwargs)
            async with _PhaseCall(phase, run):
                return await async_handler(*args, **kwargs)

        return cast(Callable[P, R], async_call)

    @wraps(handler)
    def sync_call(*args: P.args, **kwargs: P.kwargs) -> R:
        run = current_observations()
        if run is None:
            return handler(*args, **kwargs)
        with _PhaseCall(phase, run):
            return handler(*args, **kwargs)

    return sync_call

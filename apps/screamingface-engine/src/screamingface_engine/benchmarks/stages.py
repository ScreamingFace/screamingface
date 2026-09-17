"""Benchmark-owned stage facts; optional adapters own their interpretation and resources."""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from enum import StrEnum
from functools import wraps
from inspect import iscoroutinefunction
from types import TracebackType
from typing import Protocol, cast, runtime_checkable

from screamingface_engine.observations import LogEmitter, RunObservations, current_observations
from url4.observe import current_log_sink


class BenchmarkStage(StrEnum):
    CASE_LOADING = "case_loading"
    ANSWERING = "answering"
    GRADING_PREPARE = "grading_prepare"
    GRADING_CHECK = "grading_check"
    GRADING_REDUCE = "grading_reduce"
    AGGREGATION = "aggregation"


class StageScope(Protocol):
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
class StageObserver(Protocol):
    """Optional extension to a registered run observer. No request/result payloads cross it."""

    def stage(self, stage: BenchmarkStage, emit: LogEmitter | None) -> StageScope | None: ...


class _StageCall:
    def __init__(self, stage: BenchmarkStage, run: RunObservations) -> None:
        self.run = run
        self.scopes: list[StageScope] = []
        self.entered: list[StageScope] = []
        for observer in run.observers:
            with run.guard():
                if isinstance(observer, StageObserver):
                    scope = observer.stage(stage, current_log_sink())
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


def stage_scope(stage: BenchmarkStage) -> _StageCall | nullcontext[None]:
    """Observe work at its owner, independent of endpoint registration.

    Use ``with`` for synchronous work and ``async with`` around awaited work.
    The activity adapter owns records and timers; no observer means no activity.
    """
    run = current_observations()
    return nullcontext() if run is None else _StageCall(stage, run)


def reports_stage(stage: BenchmarkStage):
    """Declare activity on the implementation owning the work, not its installer.

    Shared endpoint factories declare this once for all their callers. Use an
    explicit stage_scope for a smaller region within a larger operation.
    """

    def decorate[**P, R](handler: Callable[P, R]) -> Callable[P, R]:
        return observe_stage(stage, handler)

    return decorate


def observe_stage[**P, R](stage: BenchmarkStage, handler: Callable[P, R]) -> Callable[P, R]:
    """Convenience for plain synchronous or native coroutine functions.

    Completion means the handler returned, not that a case passed. Sync work cannot
    heartbeat while blocking the event loop. Async handlers include callable objects.
    For mixed sync/awaitable work, use an explicit ``stage_scope`` around the
    actual execution instead.
    """

    if iscoroutinefunction(handler) or iscoroutinefunction(getattr(handler, "__call__", None)):
        async_handler = cast(Callable[P, Awaitable[object]], handler)

        @wraps(handler)
        async def async_call(*args: P.args, **kwargs: P.kwargs) -> object:
            run = current_observations()
            if run is None:
                return await async_handler(*args, **kwargs)
            async with stage_scope(stage):
                return await async_handler(*args, **kwargs)

        return cast(Callable[P, R], async_call)

    @wraps(handler)
    def sync_call(*args: P.args, **kwargs: P.kwargs) -> R:
        run = current_observations()
        if run is None:
            return handler(*args, **kwargs)
        with stage_scope(stage):
            return handler(*args, **kwargs)

    return sync_call

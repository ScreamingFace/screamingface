"""Generic run-scoped operation capture around the streaming Executor port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from screamingface_engine.grading_accounting import capture_grading_requests
from screamingface_engine.observations import ObserverFactory, RunObservations
from screamingface_engine.operation_calls import (
    RequestAccountingRecorder,
    capture_request_accounting,
)
from screamingface_engine.runner.summary import RunSummary
from url4.streaming.interfaces import ExecStep, Executor, TraceContext


class OperationCapturingExecutor(Executor):
    """Decorate one Executor without teaching it Benchmark or model semantics."""

    def __init__(self, inner: Executor, *, observers: tuple[ObserverFactory, ...] = ()) -> None:
        self._inner = inner
        self._observers = observers

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        observations = RunObservations(self._observers)
        requests: RequestAccountingRecorder = []
        registry = None
        iterator = self._inner.execute(url4, trace=trace)
        try:
            while True:
                # INVARIANT: ContextVar tokens never cross the outward yield. An abandoned
                # iterator may be finalized by a different task, while the reused objects keep
                # one run's accounting and grading ownership alive across every inner step.
                with observations.bind(), capture_request_accounting(requests):
                    with capture_grading_requests(registry) as registry:
                        try:
                            step = await anext(iterator)
                        except StopAsyncIteration:
                            return
                yield step
        finally:
            try:
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    # INVARIANT: cleanup shares this run, but tokens never cross outward yield.
                    with observations.bind(), capture_request_accounting(requests):
                        with capture_grading_requests(registry):
                            await close()
            finally:
                await observations.aclose()

    def last_summary(self) -> RunSummary | None:
        """Delegate the inner executor's process-level run summary (OME-1069).

        The inner `Url4Executor` records the summary in its own `execute`; the composition
        root holds THIS wrapper, so the accessor must travel through it. An inner executor
        that does not record a summary (a test double, say) answers None.
        """

        accessor = getattr(self._inner, "last_summary", None)
        if not callable(accessor):
            return None
        return cast(RunSummary | None, accessor())


__all__ = ["OperationCapturingExecutor"]

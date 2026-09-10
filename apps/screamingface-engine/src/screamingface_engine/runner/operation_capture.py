"""Generic run-scoped operation capture around the streaming Executor port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from screamingface_engine.grading_accounting import capture_grading_requests
from screamingface_engine.operation_calls import (
    RequestAccountingRecorder,
    capture_request_accounting,
)
from screamingface_engine.runner.summary import RunSummary
from url4.streaming.interfaces import ExecStep, Executor, TraceContext


class OperationCapturingExecutor(Executor):
    """Decorate one Executor without teaching it Benchmark or model semantics."""

    def __init__(self, inner: Executor) -> None:
        self._inner = inner

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        requests: RequestAccountingRecorder = []
        registry = None
        iterator = self._inner.execute(url4, trace=trace)
        try:
            while True:
                # INVARIANT: ContextVar tokens never cross the outward yield. An abandoned
                # iterator may be finalized by a different task, while the reused objects keep
                # one run's accounting and grading ownership alive across every inner step.
                with capture_request_accounting(requests):
                    with capture_grading_requests(registry) as registry:
                        try:
                            step = await anext(iterator)
                        except StopAsyncIteration:
                            return
                yield step
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                # The inner generator's own cleanup may publish final accounting, so reactivate
                # the same run state while closing it in whichever task owns this finalization.
                with capture_request_accounting(requests):
                    with capture_grading_requests(registry):
                        await close()

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

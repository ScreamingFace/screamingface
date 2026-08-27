"""Generic run-scoped operation capture around the streaming Executor port."""

from __future__ import annotations

from collections.abc import AsyncIterator

from screamingface_engine.grading_accounting import capture_grading_requests
from screamingface_engine.operation_calls import capture_operation_calls
from url4.streaming.interfaces import ExecStep, Executor, TraceContext


class OperationCapturingExecutor(Executor):
    """Decorate one Executor without teaching it Benchmark or model semantics."""

    def __init__(self, inner: Executor) -> None:
        self._inner = inner

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        with capture_operation_calls():
            with capture_grading_requests():
                iterator = self._inner.execute(url4, trace=trace)
                try:
                    async for step in iterator:
                        yield step
                finally:
                    close = getattr(iterator, "aclose", None)
                    if close is not None:
                        await close()


__all__ = ["OperationCapturingExecutor"]

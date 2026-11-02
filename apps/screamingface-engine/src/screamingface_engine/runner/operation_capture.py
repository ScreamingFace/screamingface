"""Generic run-scoped operation capture around the streaming Executor port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from screamingface_engine.artifacts import ArtifactWriter
from screamingface_engine.benchmarks.media_parking import MediaParking, parking_media
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

    def __init__(
        self,
        inner: Executor,
        *,
        observers: tuple[ObserverFactory, ...] = (),
        media_writer: ArtifactWriter | None = None,
    ) -> None:
        self._inner = inner
        self._observers = observers
        # FEATURE (OME-1271, PR 5): the run's result store, where each Case's pictures are
        # parked by sha256 at finish. None (a test double, say) parks nothing.
        self._media_writer = media_writer

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        observations = RunObservations(self._observers)
        requests: RequestAccountingRecorder = []
        registry = None
        # WHY one per run: it remembers what it parked, so a lineup's second Candidate
        # writes none of the pictures its first already parked.
        parking: MediaParking | None = (
            None if self._media_writer is None else MediaParking(self._media_writer)
        )
        iterator = None
        try:
            # INVARIANT: even synchronous iterator construction failures close observers.
            iterator = self._inner.execute(url4, trace=trace)
            while True:
                # INVARIANT: ContextVar tokens never cross the outward yield. An abandoned
                # iterator may be finalized by a different task, while the reused objects keep
                # one run's accounting and grading ownership alive across every inner step.
                with observations.bind(), capture_request_accounting(requests):
                    with capture_grading_requests(registry) as registry, parking_media(parking):
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

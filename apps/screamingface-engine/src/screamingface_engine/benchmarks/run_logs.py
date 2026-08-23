"""Benchmark adapter for the generic Runner run-Log scope."""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import Literal

from screamingface_engine.benchmarks.case_execution_contract import CaseExecutionObservation
from screamingface_engine.benchmarks.progress import (
    PROGRESS_BODY,
    EvaluationProgressTracker,
    discover_evaluation_progress,
)
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.run_log_contract import (
    LogScalar,
    StructuredLogEmitter,
)

_logger = logging.getLogger(__name__)


class _BenchmarkRunRecorder:
    """Own one execution's Benchmark claim and opaque structured-Log emitter."""

    __slots__ = (
        "_active",
        "_closed_warned",
        "_conflict_warned",
        "_disabled",
        "_emit",
        "_owner",
        "_progress",
        "_progress_warned",
        "_registry",
        "_unknown_warned",
    )

    def __init__(
        self,
        registry: BenchmarkRegistry,
        emit: StructuredLogEmitter,
        progress: EvaluationProgressTracker | None = None,
    ) -> None:
        self._registry = registry
        self._emit = emit
        self._owner: str | None = None
        self._progress = progress
        self._progress_warned = False
        self._active = True
        self._disabled = False
        self._closed_warned = False
        self._conflict_warned = False
        self._unknown_warned = False

    def emit(
        self,
        benchmark_id: str,
        body: str,
        attributes: Mapping[str, LogScalar],
    ) -> None:
        if not self._claim(benchmark_id):
            return
        self._submit(body, attributes)

    def _submit(
        self,
        body: str,
        attributes: Mapping[str, LogScalar],
    ) -> None:
        try:
            self._emit(body, attributes)
        except Exception as exc:  # noqa: BLE001 - the concrete adapter is observational too
            _logger.warning(
                "Benchmark run Log adapter emission failed (%s)",
                type(exc).__name__,
            )

    def _claim(self, benchmark_id: str) -> bool:
        allowed = False
        if not self._active:
            self._warn_closed_once()
        elif self._disabled:
            pass
        elif type(benchmark_id) is not str or self._registry.get(benchmark_id) is None:
            self._warn_unknown_once()
        elif self._owner is None:
            self._owner = benchmark_id
            allowed = True
        elif self._owner == benchmark_id:
            allowed = True
        elif self._owner != benchmark_id:
            self._disabled = True
            self._warn_conflict_once()
        return allowed

    def close(self) -> None:
        self._active = False

    def record_case_execution(self, observation: CaseExecutionObservation) -> None:
        if self._active and self._progress is not None:
            try:
                snapshot = self._progress.record_case_execution(observation)
                self._report_progress_diagnostic()
                if snapshot is not None:
                    # WHY no `_claim`: discovery identifies only this progress projection. It must
                    # not seize or conflict with ownership asserted by an operation that ran.
                    self._submit(PROGRESS_BODY, snapshot.attributes())
            except Exception as exc:  # noqa: BLE001 - progress must remain observational
                self._warn_progress_once(exc)

    def record_candidate_failure(self) -> None:
        if self._active and self._progress is not None:
            try:
                snapshot = self._progress.record_candidate_failure()
                self._report_progress_diagnostic()
                if snapshot is not None:
                    self._submit(PROGRESS_BODY, snapshot.attributes())
            except Exception as exc:  # noqa: BLE001 - progress must remain observational
                self._warn_progress_once(exc)

    def _report_progress_diagnostic(self) -> None:
        if self._progress is not None:
            diagnostic = self._progress.take_diagnostic_type()
            if diagnostic is not None:
                self._warn_progress_once(diagnostic)

    def _warn_progress_once(self, exc: Exception | str) -> None:
        if not self._progress_warned:
            diagnostic = exc if isinstance(exc, str) else type(exc).__name__
            _logger.warning("Benchmark progress observation failed (%s)", diagnostic)
            self._progress_warned = True

    def _warn_closed_once(self) -> None:
        if not self._closed_warned:
            _logger.warning("closed Benchmark run Log recorder ignored")
            self._closed_warned = True

    def _warn_unknown_once(self) -> None:
        if not self._unknown_warned:
            _logger.warning("unknown Benchmark run Log claim ignored")
            self._unknown_warned = True

    def _warn_conflict_once(self) -> None:
        if not self._conflict_warned:
            # INVARIANT: never interpolate either ID. A conflict is actionable without copying
            # producer-controlled identity or any Benchmark payload into operator diagnostics.
            _logger.warning("conflicting Benchmark run Log claims; instrumentation disabled")
            self._conflict_warned = True


_current_recorder: contextvars.ContextVar[_BenchmarkRunRecorder | None] = contextvars.ContextVar(
    "screamingface_engine_benchmark_run_log_recorder", default=None
)


class _BenchmarkRunScope(AbstractContextManager[None]):
    __slots__ = ("_recorder", "_token")

    def __init__(self, recorder: _BenchmarkRunRecorder) -> None:
        self._recorder = recorder
        self._token: contextvars.Token[_BenchmarkRunRecorder | None] | None = None

    def __enter__(self) -> None:
        self._token = _current_recorder.set(self._recorder)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self._recorder.close()
        if self._token is not None:
            _current_recorder.reset(self._token)
            self._token = None
        return False


class BenchmarkRunLogAdapter:
    """Adapt the immutable Benchmark registry onto the generic Runner run-scope port."""

    __slots__ = ("_assets_root", "_registry")

    def __init__(self, registry: BenchmarkRegistry, *, assets_root: Path = Path()) -> None:
        self._registry = registry
        self._assets_root = assets_root

    def open_run_scope(
        self,
        rendered_url4: str,
        emit_structured_log: StructuredLogEmitter,
    ) -> AbstractContextManager[None] | None:
        if not len(self._registry):
            return None
        progress = discover_evaluation_progress(
            self._registry,
            rendered_url4,
            assets_root=self._assets_root,
        )
        return _BenchmarkRunScope(
            _BenchmarkRunRecorder(self._registry, emit_structured_log, progress)
        )


def emit_benchmark_run_log(
    benchmark_id: str,
    body: str,
    attributes: Mapping[str, LogScalar],
) -> None:
    """Submit one Benchmark-owned record when called inside an active Engine execution.

    A call outside a run is an inert capability probe, not an error. A child task that retained a
    recorder beyond scope close is different: the recorder observes that stale use and refuses it.
    """

    recorder = _current_recorder.get()
    if recorder is not None:
        recorder.emit(benchmark_id, body, attributes)


def record_successful_case_execution(observation: CaseExecutionObservation) -> None:
    """Observe one validated Case return when a progress tracker is active."""

    recorder = _current_recorder.get()
    if recorder is not None:
        recorder.record_case_execution(observation)


def record_candidate_failure() -> None:
    """Observe one Candidate exception when a progress tracker is active."""

    recorder = _current_recorder.get()
    if recorder is not None:
        recorder.record_candidate_failure()


__all__ = [
    "BenchmarkRunLogAdapter",
    "emit_benchmark_run_log",
    "record_candidate_failure",
    "record_successful_case_execution",
]

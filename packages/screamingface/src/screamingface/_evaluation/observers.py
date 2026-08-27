"""Fail-open progress, callback, and diagnostic observation for Evaluations."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from threading import Lock

from screamingface._diagnostics.evaluation import _EvaluationDiagnostic
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface.events import Event
from screamingface.report import Report

_logger = logging.getLogger(__name__)


def _evaluation_diagnostic(
    *,
    engine_url: str,
    benchmark: object,
    candidates: object = None,
    mode: str | None = None,
) -> _EvaluationDiagnostic | None:
    try:
        return _EvaluationDiagnostic(
            engine_url=engine_url,
            benchmark=benchmark,
            candidates=candidates,
            mode=mode,
        )
    except Exception:
        _logger.exception("ScreamingFace diagnostic setup failed")
        return None


def _sync_event_observer(
    callback: Callable[[Event], None] | None,
    progress: bool | None,
    candidates: tuple[Candidate, ...] = (),
    case_count: int | None = None,
    benchmark: str | None = None,
    check_disclosure: str | None = None,
    diagnostic: _EvaluationDiagnostic | None = None,
) -> _SyncEventObserver | None:
    from screamingface._evaluation.progress import _progress_observer

    builtin = _progress_observer(
        progress,
        candidates=candidates,
        case_count=case_count,
        benchmark=benchmark,
        check_disclosure=check_disclosure,
    )
    if builtin is None and callback is None and diagnostic is None:
        return None
    return _SyncEventObserver(builtin, callback, diagnostic)


def _async_event_observer(
    callback: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    candidates: tuple[Candidate, ...] = (),
    case_count: int | None = None,
    benchmark: str | None = None,
    check_disclosure: str | None = None,
    diagnostic: _EvaluationDiagnostic | None = None,
) -> _AsyncEventObserver | None:
    from screamingface._evaluation.progress import _progress_observer

    builtin = _progress_observer(
        progress,
        candidates=candidates,
        case_count=case_count,
        benchmark=benchmark,
        check_disclosure=check_disclosure,
    )
    if builtin is None and callback is None and diagnostic is None:
        return None
    return _AsyncEventObserver(builtin, callback, diagnostic)


class _SyncEventObserver:
    def __init__(
        self,
        builtin: object | None,
        callback: Callable[[Event], None] | None,
        diagnostic: _EvaluationDiagnostic | None = None,
    ) -> None:
        self._builtin = builtin
        self._callback = callback
        self._diagnostic = diagnostic
        self._lock = Lock()

    def begin(self, candidate: Candidate) -> None:
        with self._lock:
            _begin_diagnostic(self._diagnostic, candidate)
            if self._builtin is not None:
                _begin_candidate_progress(self._builtin, candidate)

    def bind(self, candidate: Candidate) -> Callable[[Event], None]:
        def observe(event: Event) -> None:
            with self._lock:
                _observe_diagnostic(self._diagnostic, candidate, event)
                if self._builtin is not None:
                    _observe_candidate_progress(self._builtin, candidate, event)
                if self._callback is not None:
                    self._callback(event)

        return observe

    def reconcile(self, report: Report) -> None:
        _reconcile_progress(self._builtin, report)

    def abort(self, exc: BaseException) -> None:
        _abort_progress(self._builtin, exc)

    def close(self) -> None:
        _close_progress(self._builtin)


class _AsyncEventObserver:
    def __init__(
        self,
        builtin: object | None,
        callback: Callable[[Event], None | Awaitable[None]] | None,
        diagnostic: _EvaluationDiagnostic | None = None,
    ) -> None:
        self._builtin = builtin
        self._callback = callback
        self._diagnostic = diagnostic
        self._lock = asyncio.Lock()

    async def begin(self, candidate: Candidate) -> None:
        async with self._lock:
            _begin_diagnostic(self._diagnostic, candidate)
            if self._builtin is not None:
                _begin_candidate_progress(self._builtin, candidate)

    def bind(self, candidate: Candidate) -> Callable[[Event], Awaitable[None]]:
        async def observe(event: Event) -> None:
            async with self._lock:
                _observe_diagnostic(self._diagnostic, candidate, event)
                if self._builtin is not None:
                    _observe_candidate_progress(self._builtin, candidate, event)
                if self._callback is not None:
                    returned = self._callback(event)
                    if inspect.isawaitable(returned):
                        await returned

        return observe

    def reconcile(self, report: Report) -> None:
        _reconcile_progress(self._builtin, report)

    def abort(self, exc: BaseException) -> None:
        _abort_progress(self._builtin, exc)

    def close(self) -> None:
        _close_progress(self._builtin)


def _close_event_observer(observer: object) -> None:
    if isinstance(observer, (_SyncEventObserver, _AsyncEventObserver)):
        observer.close()


def _reconcile_event_observer(observer: object, report: Report) -> None:
    if isinstance(observer, (_SyncEventObserver, _AsyncEventObserver)):
        observer.reconcile(report)


def _abort_event_observer(observer: object, exc: BaseException) -> None:
    if isinstance(observer, (_SyncEventObserver, _AsyncEventObserver)):
        observer.abort(exc)


def _record_compiled_evaluation(
    context: _EvaluationDiagnostic | None,
    evaluation: _Evaluation,
) -> None:
    if context is None:
        return
    try:
        context.compiled(evaluation)
    except Exception:
        _logger.exception("ScreamingFace diagnostic enrichment failed")


def _record_validated_evaluation(
    context: _EvaluationDiagnostic | None,
    evaluation: _Evaluation,
) -> None:
    if context is None:
        return
    try:
        context.validated(evaluation)
    except Exception:
        _logger.exception("ScreamingFace diagnostic enrichment failed")


def _record_compiled_candidate(
    context: _EvaluationDiagnostic | None,
    candidate: Candidate,
) -> None:
    if context is None:
        return
    try:
        context.compiled_candidate(candidate)
    except Exception:
        _logger.exception("ScreamingFace diagnostic enrichment failed")


def _stage_diagnostic(context: _EvaluationDiagnostic | None, exc: BaseException) -> None:
    """Keep local diagnostics strictly subordinate to the operation's exception."""

    if context is None:
        return
    try:
        receipt = context.stage(exc)
    except Exception:
        _logger.exception("ScreamingFace diagnostic capture failed")
        return
    if receipt is None:
        _logger.warning("ScreamingFace diagnostic exceeded the local storage budget")
        return
    try:
        from screamingface._ui.diagnostic_view import _attach_notebook_renderer

        _attach_notebook_renderer(exc, receipt)
    except Exception:
        # INVARIANT: notebook presentation is subordinate to the original operation exception.
        _logger.debug("ScreamingFace diagnostic presentation unavailable", exc_info=True)


def _begin_diagnostic(context: _EvaluationDiagnostic | None, candidate: Candidate) -> None:
    if context is None:
        return
    try:
        context.begin(candidate)
    except Exception:
        _logger.exception("ScreamingFace diagnostic observation failed")


def _observe_diagnostic(
    context: _EvaluationDiagnostic | None,
    candidate: Candidate,
    event: Event,
) -> None:
    if context is None:
        return
    try:
        context.observe(candidate, event)
    except Exception:
        _logger.exception("ScreamingFace diagnostic observation failed")


def _close_progress(observer: object) -> None:
    close = getattr(observer, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        _logger.exception("ScreamingFace progress cleanup failed")


def _observe_candidate_progress(observer: object, candidate: Candidate, event: Event) -> None:
    selected = getattr(observer, "observe", None)
    if not callable(selected):
        _logger.error("ScreamingFace progress observer has no Candidate observation method")
        return
    _observe_progress(selected, candidate, event)


def _begin_candidate_progress(observer: object, candidate: Candidate) -> None:
    begin = getattr(observer, "begin", None)
    if not callable(begin):
        _logger.error("ScreamingFace progress observer has no Candidate begin method")
        return
    _observe_progress(begin, candidate)


def _reconcile_progress(observer: object | None, report: Report) -> None:
    if observer is None:
        return
    reconcile = getattr(observer, "reconcile", None)
    if not callable(reconcile):
        return
    try:
        reconcile(report)
    except Exception:
        _logger.exception("ScreamingFace progress reconciliation failed")
        _close_progress(observer)


def _abort_progress(observer: object | None, exc: BaseException) -> None:
    if observer is None:
        return
    abort = getattr(observer, "abort", None)
    if not callable(abort):
        _close_progress(observer)
        return
    try:
        abort(exc)
    except Exception:
        _logger.exception("ScreamingFace progress finalization failed")
        _close_progress(observer)


def _observe_progress(observer: Callable[..., object], *values: object) -> None:
    """Keep decorative progress output outside the Evaluation failure boundary."""

    try:
        observer(*values)
    except (OSError, ValueError):
        return
    except Exception:
        _logger.exception("ScreamingFace progress rendering failed")


__all__: list[str] = []

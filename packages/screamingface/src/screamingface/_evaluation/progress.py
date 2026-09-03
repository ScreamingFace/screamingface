"""Small built-in progress observer driven exclusively by public Events."""

from __future__ import annotations

import logging
import sys
import unicodedata
from typing import Protocol, TextIO

from screamingface._environment import ipykernel_loaded as _in_notebook
from screamingface._evaluation.model import Candidate
from screamingface.events import Event, Log, Span, Started, Terminated
from screamingface.report import Report

_logger = logging.getLogger(__name__)


class _EvaluationObserver(Protocol):
    def begin(self, candidate: Candidate) -> None: ...

    def observe(self, candidate: Candidate, event: Event) -> None: ...

    def reconcile(self, report: Report) -> None: ...

    def abort(self, exc: BaseException) -> None: ...


def _progress_observer(
    requested: bool | None,
    *,
    stream: TextIO | None = None,
    candidates: tuple[Candidate, ...] = (),
    case_count: int | None = None,
    benchmark: str | None = None,
    check_disclosure: str | None = None,
) -> _EvaluationObserver | None:
    selected_stream = sys.stderr if stream is None else stream
    in_notebook = _in_notebook()
    enabled = requested is not False and (
        requested is not None or in_notebook or selected_stream.isatty()
    )
    # In a notebook the live panel is preferred; text remains the fallback everywhere.
    rich = (
        _notebook_observer(candidates, case_count, benchmark, check_disclosure)
        if enabled and in_notebook and candidates
        else None
    )
    # The paid-check disclosure must never be silent (OME-845): the panel is its calm
    # carrier, and every path that ends without a panel — progress off, headless, panel
    # construction failure — falls back to the Python warning the panel replaced.
    if check_disclosure is not None and rich is None:
        import warnings

        from screamingface.warnings import EvaluationWarning

        warnings.warn(check_disclosure, EvaluationWarning, stacklevel=5)
    if not enabled:
        return None
    return _ProgressObserver(selected_stream) if rich is None else rich


def _notebook_observer(
    candidates: tuple[Candidate, ...],
    case_count: int | None,
    benchmark: str | None,
    check_disclosure: str | None = None,
) -> _EvaluationObserver | None:
    """The live panel, or None when it cannot be built (text progress then carries it).

    Building a widget touches ipywidgets' comm layer, which can fail for reasons well
    beyond a missing extra. Progress is decorative and must never take down paid Engine
    work, so ANY construction failure degrades to the text observer rather than raising.
    """

    try:
        from screamingface._ui.evaluation_widget import _NotebookEvaluationView

        return _NotebookEvaluationView(
            candidates,
            case_count,
            benchmark,
            check_disclosure=check_disclosure,
        )
    except Exception:
        _logger.debug("Rich notebook progress unavailable; using text progress", exc_info=True)
        return None


class _ProgressObserver:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def __call__(self, event: Event) -> None:
        message = _message(event)
        if message is not None:
            self._stream.write(f"ScreamingFace · {_terminal_text(message)}\n")
            self._stream.flush()

    def observe(self, candidate: Candidate, event: Event) -> None:
        del candidate
        self(event)

    def begin(self, candidate: Candidate) -> None:
        del candidate

    def reconcile(self, report: Report) -> None:
        del report

    def abort(self, exc: BaseException) -> None:
        del exc


def _message(event: Event) -> str | None:
    message: str | None = None
    if isinstance(event, Started):
        message = "Evaluation started"
    elif isinstance(event, Log):
        message = event.body or None
    elif isinstance(event, Span):
        message = _model_message(event)
    elif isinstance(event, Terminated):
        message = _termination_message(event.status)
    return message


def _termination_message(status: str) -> str:
    if status == "succeeded":
        return "Evaluation finished"
    return f"Evaluation {status.replace('_', ' ')}"


def _model_message(event: Span) -> str | None:
    """Render paid model work while hiding URL4's structural execution spans."""

    if event.request_model is None:
        return None
    outcome = (
        "refused"
        if event.refusal is not None
        else "failed"
        if event.status == "error"
        else "completed"
    )
    parts = [f"Model {outcome}", event.request_model]
    if event.start is not None and event.end is not None:
        parts.append(_duration((event.end - event.start).total_seconds()))
    if event.input_tokens is not None or event.output_tokens is not None:
        input_tokens = "?" if event.input_tokens is None else f"{event.input_tokens:,}"
        output_tokens = "?" if event.output_tokens is None else f"{event.output_tokens:,}"
        parts.append(f"{input_tokens} in / {output_tokens} out")
    if event.finish_reasons:
        parts.append(" → ".join(event.finish_reasons))
    return " · ".join(parts)


def _duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _terminal_text(value: str) -> str:
    """Keep untrusted Engine log text on one inert terminal line."""

    inert = "".join(
        " " if unicodedata.category(character).startswith("C") else character for character in value
    )
    return " ".join(inert.split())


__all__: list[str] = []

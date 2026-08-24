"""Stable ipywidgets host for live Evaluation progress."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from screamingface._evaluation.model import Candidate
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import _evaluation_fragments
from screamingface.events import Event
from screamingface.report import Report


class _NotebookEvaluationView:
    _TICK_SECONDS = 1.0
    _COALESCE_SECONDS = 0.1
    _MAX_TICK_SECONDS = 6 * 60 * 60

    def __init__(
        self,
        candidates: tuple[Candidate, ...],
        case_count: int | None,
        benchmark: str | None = None,
        *,
        check_disclosure: str | None = None,
        clock: Callable[[], float] | None = None,
        tick: bool = True,
    ) -> None:
        import ipywidgets as widgets

        self._progress = _EvaluationProgress(candidates=candidates, case_count=case_count)
        self._benchmark = benchmark
        self._check_disclosure = check_disclosure
        self._clock = time.monotonic if clock is None else clock
        self._started = self._clock()
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._dirty = threading.Event()
        self._tick = tick
        header, table, terminal = self._render_fragments()
        self._header: Any = widgets.HTML(value=header)
        # INVARIANT: this HTML widget owns scrollLeft and is never replaced. Value updates replace
        # its table descendants while Colab keeps the scroll position on this stable root node.
        self._table: Any = widgets.HTML(
            value=table,
            layout=widgets.Layout(overflow="auto", width="100%"),
            tabbable=True,
            tooltip="Candidate evaluation table",
        )
        self._table.add_class("sf-eval__table-scroll")
        self._terminal: Any = widgets.HTML(value=terminal)
        self._html: Any = widgets.VBox(
            children=(self._header, self._table, self._terminal),
            tooltip="ScreamingFace evaluation progress",
        )
        self._html.add_class("sf-ui")
        self._html.add_class("sf-eval")
        self._shown = False
        self._show()
        if tick:
            self._ticker = threading.Thread(
                target=self._tick_loop,
                name="screamingface-progress",
                daemon=True,
            )
            self._ticker.start()

    def observe(self, candidate: Candidate, event: Event) -> None:
        with self._lock:
            self._progress.observe(
                candidate,
                event,
                elapsed_seconds=self._clock() - self._started,
            )
            if not self._tick:
                self._refresh()
        self._dirty.set()

    def begin(self, candidate: Candidate) -> None:
        with self._lock:
            self._progress.begin(candidate)
            if not self._tick:
                self._refresh()
        self._dirty.set()

    def reconcile(self, report: Report) -> None:
        with self._lock:
            self._progress.reconcile(report)
            self._refresh()
        self._done.set()
        self._dirty.set()

    def abort(self, exc: BaseException) -> None:
        with self._lock:
            self._progress.abort(exc)
            self._refresh()
        self._done.set()
        self._dirty.set()

    def close(self) -> None:
        self._done.set()
        self._dirty.set()

    def _render_fragments(self) -> tuple[str, str, str]:
        elapsed = None if self._progress.finished else self._clock() - self._started
        return _evaluation_fragments(
            self._progress,
            self._benchmark,
            elapsed,
            self._check_disclosure,
        )

    def _refresh(self) -> None:
        header, table, terminal = self._render_fragments()
        self._header.value = header
        self._table.value = table
        self._terminal.value = terminal

    def _tick_loop(self) -> None:
        deadline = self._started + self._MAX_TICK_SECONDS
        while not self._done.is_set():
            dirty = self._dirty.wait(self._TICK_SECONDS)
            self._dirty.clear()
            if self._done.is_set():
                break
            if dirty and self._done.wait(self._COALESCE_SECONDS):
                break
            if self._clock() >= deadline:
                break
            try:
                with self._lock:
                    if self._progress.finished:
                        break
                    self._refresh()
            except Exception:
                break

    def _show(self) -> None:
        if self._shown:
            return
        from IPython.display import display

        display(self._html)
        self._shown = True


__all__: list[str] = []

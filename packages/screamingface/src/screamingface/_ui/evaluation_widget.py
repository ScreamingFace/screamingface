"""Stable ipywidgets host for live Evaluation progress."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from screamingface._evaluation.model import Candidate
from screamingface._ui.activity_groups import active_cases, stage_status
from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import STYLE as ACTIVITY_STYLE
from screamingface._ui.activity_widget import CandidateActivityRow
from screamingface._ui.evaluation_state import _EvaluationProgress
from screamingface._ui.evaluation_view import _evaluation_fragments
from screamingface.events import Event, Log
from screamingface.report import Report


class _NotebookEvaluationView:
    _TICK_SECONDS = 1.0
    _COALESCE_SECONDS = 0.2

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
        self._activity = ActivityLog()
        self._candidate_indexes = {c.name: i for i, c in enumerate(candidates)}
        self._progress = _EvaluationProgress(candidates=candidates, case_count=case_count)
        self._benchmark = benchmark
        self._check_disclosure = check_disclosure
        self._clock = time.monotonic if clock is None else clock
        self._started = self._clock()
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._dirty = threading.Event()
        self._tick = tick
        self._build_widgets(candidates)
        self._shown = False
        self._show()
        if tick:
            self._ticker = threading.Thread(
                target=self._tick_loop,
                name="screamingface-progress",
                daemon=True,
            )
            self._ticker.start()

    def _build_widgets(self, candidates: tuple[Candidate, ...]) -> None:
        import ipywidgets as widgets

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
        names = tuple(c.name for c in candidates)
        self._activity_rows = tuple(
            CandidateActivityRow(self._activity, names, index, lock=self._lock)
            for index in range(len(candidates))
        )
        self._refresh_rows()
        head: Any = widgets.HBox(
            children=(
                widgets.HTML(value="", layout=widgets.Layout(width="24px", min_width="24px")),
                self._table,
            ),
            layout=widgets.Layout(min_width="820px"),
        )
        head.add_class("sf-candidate-head")
        self._row_list: Any = widgets.VBox(
            children=(head, *(r.widget for r in self._activity_rows)),
            layout=widgets.Layout(overflow="auto", width="100%"),
        )
        self._html: Any = widgets.VBox(
            children=(
                widgets.HTML(value=ACTIVITY_STYLE),
                self._header,
                self._row_list,
                self._terminal,
            )
        )
        self._html.add_class("sf-ui")
        self._html.add_class("sf-eval")

    def observe(self, candidate: Candidate, event: Event) -> None:
        with self._lock:
            if isinstance(event, Log):
                self._activity.observe(self._candidate_indexes[candidate.name], event)
            self._progress.observe(
                candidate,
                event,
                elapsed_seconds=self._clock() - self._started,
            )
            index = self._candidate_indexes[candidate.name]
            if self._progress.rows[index].status not in {"queued", "running"}:
                self._activity.end(index)
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
            self._end_activity()
            self._progress.reconcile(report)
            self._refresh()
        self._done.set()
        self._dirty.set()

    def abort(self, exc: BaseException) -> None:
        with self._lock:
            self._end_activity()
            self._progress.abort(exc)
            self._refresh()
        self._done.set()
        self._dirty.set()

    def _end_activity(self) -> None:
        for index in self._candidate_indexes.values():
            self._activity.end(index)

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
            expandable=True,
        )

    def _refresh(self) -> None:
        header, table, terminal = self._render_fragments()
        self._header.value = header
        self._table.value = table
        self._terminal.value = terminal
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        elapsed = None if self._progress.finished else self._clock() - self._started
        for index, (view, row) in enumerate(
            zip(self._activity_rows, self._progress.rows, strict=True)
        ):
            now_ms = time.time() * 1000
            row.stage = stage_status(self._activity, index, now_ms=now_ms)
            row.active_cases = active_cases(self._activity, index, now_ms=now_ms)
            view.refresh(row, elapsed)

    def _tick_loop(self) -> None:
        while not self._done.is_set():
            dirty = self._dirty.wait(self._TICK_SECONDS)
            self._dirty.clear()
            if self._done.is_set():
                break
            if dirty and self._done.wait(self._COALESCE_SECONDS):
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

"""Stable expansion and scroll roots beneath each Candidate row."""

import time
from contextlib import AbstractContextManager
from threading import RLock
from typing import Any

from screamingface._ui.activity_state import ActivityLog
from screamingface._ui.activity_view import activity_html
from screamingface._ui.evaluation_state import _CandidateProgress
from screamingface._ui.evaluation_view import _candidate_row_html, _table_html


class CandidateActivityRow:
    _RENDER_STEP_SECONDS = 2

    def __init__(
        self,
        log: ActivityLog,
        candidates: tuple[str, ...],
        index: int,
        *,
        lock: AbstractContextManager[object] | None = None,
    ) -> None:
        import ipywidgets as widgets

        self._lock = lock if lock is not None else RLock()
        self._log, self._candidates, self._index = log, candidates, index
        self._finished = False
        self._running = False
        self._completed_at_ms: int | None = None
        self._rendered: tuple[tuple[object, ...], int] | None = None
        self.toggle: Any = widgets.ToggleButton(
            value=False,
            description=f"Activity for {candidates[index]}",
            icon="chevron-right",
            tooltip=f"Show activity for {candidates[index]}",
            layout=widgets.Layout(width="100%", height="100%"),
        )
        self.summary: Any = widgets.HTML(value="", layout=widgets.Layout(width="100%"))
        # WHY: keep the scroll viewport outside replaceable HTML content.
        self.html: Any = widgets.HTML(
            value="",
            layout=widgets.Layout(overflow="auto", height="auto", max_height="280px"),
            tabbable=True,
            tooltip=f"Activity for {candidates[index]}",
        )
        self.details: Any = widgets.VBox(
            children=(self.html,), layout=widgets.Layout(display="none")
        )
        summary: Any = widgets.HBox(
            children=(self.toggle, self.summary), layout=widgets.Layout(min_width="820px")
        )
        # WHY: a native toggle owns the whole summary hit area; logs remain outside it.
        summary.add_class("sf-candidate-summary")
        self.details.add_class("sf-candidate-details")
        self.widget: Any = widgets.VBox(
            children=(summary, self.details), layout=widgets.Layout(min_width="820px")
        )
        self.widget.add_class("sf-candidate-row")
        self.toggle.observe(self._toggle, names="value")

    def _toggle(self, change: object) -> None:
        with self._lock:
            self.details.layout.display = "" if self.toggle.value else "none"
            verb = "Hide" if self.toggle.value else "Show"
            self.toggle.tooltip = f"{verb} activity for {self._candidates[self._index]}"
            self._refresh_activity()

    def refresh(
        self, row: _CandidateProgress, elapsed: float | None, *, final: bool = False
    ) -> None:
        self.summary.value = _table_html(_candidate_row_html(row, elapsed))
        self._finished = row.status not in {"queued", "running"}
        self._running = row.status == "running"
        self._completed_at_ms = (
            int(row.result.completed_at.timestamp() * 1000)
            if row.result is not None and row.qualifier is None
            else None
        )
        # FEATURE: open live rows mid-run (OME-1612) — the browser opens a row without the kernel,
        # so every row's activity is kept current, open or not.
        # WHY: this runs each tick under the lock Engine events take, so a row renders at most once
        # per step: when its activity changed, or while running, because a running operation turns
        # "No recent update" by wall-clock age alone. The final refresh always renders.
        if final or self._rendered is None:
            self._refresh_activity()
            return
        key, step = self._rendered
        if self._step() != step and (self._running or self._render_key() != key):
            self._refresh_activity()

    def _render_key(self) -> tuple[object, ...]:
        return self._log.revision(self._index), self._completed_at_ms

    def _step(self) -> int:
        return int(time.time() // self._RENDER_STEP_SECONDS)

    def _refresh_activity(self) -> None:
        key, step = self._render_key(), self._step()
        self.html.value = activity_html(
            self._log,
            self._candidates,
            candidate=self._index,
            finished=self._finished,
            completed_at_ms=self._completed_at_ms,
        )
        # WHY: recorded after the render, so a render that raises is retried.
        self._rendered = key, step

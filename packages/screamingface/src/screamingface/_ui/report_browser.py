"""Live notebook Case browsing; only the current page enters widget state."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload
from uuid import uuid4

from screamingface._ui.report_files import download_link
from screamingface._ui.report_view import cases_page_html, report_html
from screamingface._ui.style import NO_MATH_CLASSES
from screamingface.errors import ScreamingFaceError

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult, Report

_PAGE_SIZE = 25
_BROWSER_STYLE = """<style>
.sf-report-browser .widget-button,.sf-report-browser input,.sf-report-browser select{
 border-radius:0!important;border:1px solid var(--sf-line-2)!important;
 background:var(--sf-bg)!important;color:var(--sf-ink)!important;box-shadow:none!important}
.sf-report-browser .widget-button:hover{background:var(--sf-surface)!important}
.sf-report-browser .widget-button:focus-visible{outline:2px solid var(--sf-accent)}
.sf-report-browser .widget-label{color:var(--sf-ink-2)}
.sf-report-browser .widget-button:disabled{opacity:.55;cursor:default}
.sf-report-browser .fa-spinner{animation:sf-export-spin 1s linear infinite}
@keyframes sf-export-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.sf-report-browser .fa-spinner{animation:none}}
</style>"""


class _Entries(Sequence[tuple["CandidateResult", "CaseResult"]]):
    """Flatten candidate positions without retaining their cases."""

    def __init__(self, report: Report) -> None:
        self.owners = report.candidates
        self.total = sum(len(owner.cases) for owner in self.owners)

    def __len__(self) -> int:
        return self.total

    @overload
    def __getitem__(self, index: int) -> tuple[CandidateResult, CaseResult]: ...

    @overload
    def __getitem__(self, index: slice) -> list[tuple[CandidateResult, CaseResult]]: ...

    def __getitem__(self, index: int | slice):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.total))]
        position = index + self.total if index < 0 else index
        if not 0 <= position < self.total:
            raise IndexError(index)
        for owner in self.owners:
            if position < len(owner.cases):
                return owner, owner.cases[position]
            position -= len(owner.cases)
        raise IndexError(index)


class ReportBrowser:
    """Kernel-backed controls over the immutable Report, with bounded case access."""

    def __init__(self, report: Report) -> None:
        import ipywidgets as widgets

        self.w = widgets
        self.report = report
        self.entries = _Entries(report)
        self.matches = range(len(self.entries))
        self.page = 0
        self._exporting = False
        self._export_task = None
        self.directory = Path("screamingface-reports") / uuid4().hex
        self.snapshot = self.directory / "report.json"
        self.notice = widgets.HTML()
        self._controls()
        self._assemble()
        self._render_page()

    def _controls(self) -> None:
        w = self.w
        self.previous = w.Button(description="Previous", icon="chevron-left")
        self.next = w.Button(description="Next", icon="chevron-right")
        self.count = w.Label()
        self.cases = w.HTML()
        self.previous.on_click(lambda _: self._move(-1))
        self.next.on_click(lambda _: self._move(1))

    def _assemble(self) -> None:
        w = self.w
        self.exports = w.HTML(value=self._snapshot_link())
        self.export = w.Button(description="Export full JSON")
        self.export.on_click(self._export_json)
        self.widget = w.VBox(
            [
                w.HTML(
                    value=_BROWSER_STYLE + report_html(self.report, cases=False, download=False)
                ),
                self.notice,
                self.exports,
                self.export,
                self._row([self.previous, self.count, self.next]),
                self.cases,
            ]
        )
        for name in ("sf-ui", "sf-report-browser", *NO_MATH_CLASSES):
            self.widget.add_class(name)

    def _row(self, children: list[Any]) -> Any:
        return self.w.HBox(children, layout=self.w.Layout(flex_flow="row wrap"))

    def _snapshot_link(self) -> str:
        if not self.snapshot.exists():
            return ""
        return download_link(self.snapshot, "Download all results · JSON (lossless)")

    def _move(self, direction: int) -> None:
        last = max(0, (len(self.matches) - 1) // _PAGE_SIZE)
        self.page = min(last, max(0, self.page + direction))
        self._render_page()

    def _render_page(self) -> None:
        start = self.page * _PAGE_SIZE
        indices = self.matches[start : start + _PAGE_SIZE]
        self.count.value = (
            f"Showing {start + 1 if indices else 0}–{start + len(indices)} "
            f"of {len(self.matches)} · {len(self.entries)} total"
        )
        self.previous.disabled = self.page == 0
        self.next.disabled = start + _PAGE_SIZE >= len(self.matches)
        self.cases.value = cases_page_html(self.report, [self.entries[index] for index in indices])

    def _export_json(self, change: Any = None) -> None:
        # INVARIANT: queued clicks cannot start concurrent or repeated exports of this Report.
        if self._exporting or self.snapshot.exists():
            return
        self._exporting = True
        self.export.disabled = True
        self.export.description = "Exporting…"
        self.export.icon = "spinner"
        self.notice.value = '<p role="status">Preparing download…</p>'
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write_export()
            return
        self._export_task = loop.create_task(self._export_async())

    async def _export_async(self) -> None:
        # WHY: keep the kernel event loop processing widget state and duplicate clicks.
        try:
            await asyncio.to_thread(self.report.export, self.snapshot)
        except (OSError, sqlite3.Error, ScreamingFaceError) as exc:
            self._export_failed(exc)
        else:
            self._export_ready()

    def _write_export(self) -> None:
        try:
            self.report.export(self.snapshot)
        except (OSError, sqlite3.Error, ScreamingFaceError) as exc:
            self._export_failed(exc)
        else:
            self._export_ready()

    def _export_failed(self, exc: Exception) -> None:
        self._exporting = False
        self.export.disabled = False
        self.export.description = "Retry export"
        self.export.icon = ""
        self.notice.value = f'<p role="alert">Export failed: {escape(str(exc))}</p>'

    def _export_ready(self) -> None:
        self.exports.value = self._snapshot_link()
        self.notice.value = '<p role="status">Export ready. Use the download link.</p>'
        self.export.description = "Export ready"
        self.export.icon = "check"
        self._exporting = False

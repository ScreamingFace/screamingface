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
from screamingface.accounting import _accounting_context
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
.sf-cases-box{border:1px solid var(--sf-line);margin-top:14px;width:100%}
.sf-cases-header{background:var(--sf-surface);padding:8px 12px;gap:4px;
 border-bottom:1px solid var(--sf-line)}
.sf-report-browser .sf-cases-title{border:0!important;background:transparent!important;
 color:var(--sf-ink-2)!important;text-align:left;box-shadow:none!important;
 font-weight:600;font-size:14px!important}
.sf-cases-header>.widget-label{margin:0 8px;font-size:12px}
.sf-cases-body.widget-html{margin:0;width:100%}
.sf-cases-body>.widget-html-content{width:100%}
.sf-cases-header .widget-button,.sf-cases-header .widget-box{flex-shrink:0}
.sf-report-browser .sf-browser-links a{display:inline-flex;align-items:center;
 justify-content:center;box-sizing:border-box;width:148px;min-height:28px;padding:2px 6px;
 margin:2px;border:1px solid var(--sf-line-2);background:var(--sf-bg);color:var(--sf-ink);
 font:inherit;text-decoration:none}
.sf-report-browser .sf-browser-links a:hover{background:var(--sf-surface)}
.sf-report-browser .sf-browser-links a:focus-visible{outline:2px solid var(--sf-accent)}
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
        self.matches: Sequence[int] = range(len(self.entries))
        self.page = 0
        self._requested_page = 0
        self._exporting = False
        self._export_task = None
        self._search_task = None
        self._paging = False
        self._page_task = None
        self.directory = Path("screamingface-reports") / uuid4().hex
        self.snapshot = self.directory / "report.json"
        self.notice = widgets.HTML()
        self._controls()
        self._assemble()
        self._render_page()

    def _controls(self) -> None:
        w = self.w
        self.search = w.Text(
            placeholder="Search cases… press Enter",
            continuous_update=False,
            layout=w.Layout(width="auto", min_width="140px", flex="1 1 180px"),
        )
        self.search.observe(self._search, names="value")
        self.previous = w.Button(description="Previous", icon="chevron-left")
        self.next = w.Button(description="Next", icon="chevron-right")
        self.count = w.Label()
        self.cases = w.HTML()
        self.previous.on_click(lambda _: self._move(-1))
        self.next.on_click(lambda _: self._move(1))

    def _assemble(self) -> None:
        w = self.w
        self._accounting_contexts = {
            id(owner): _accounting_context(owner) for owner in self.entries.owners
        }
        self.exports = w.HTML(value=self._snapshot_link())
        self.export = w.Button(description="Download")
        self.export.on_click(self._export_json)
        self.export_slot = w.VBox([self.export])
        self._case_box()

        self.widget = w.VBox(
            [
                w.HTML(
                    value=_BROWSER_STYLE
                    + report_html(
                        self.report,
                        cases=False,
                        download=False,
                        accounting_contexts=self._accounting_contexts,
                    )
                ),
                self.case_box,
            ]
        )
        for name in ("sf-ui", "sf-report-browser", *NO_MATH_CLASSES):
            self.widget.add_class(name)

    def _case_box(self) -> None:
        w = self.w
        self.case_title = w.Label(
            value="Case results",
            layout=w.Layout(width="auto", margin="0 8px 0 0"),
        )
        self.case_title.add_class("sf-cases-title")
        self.previous.layout.width = "96px"
        self.next.layout.width = "76px"
        self.pagination = w.HBox([self.previous, self.next])
        self.case_header = w.HBox(
            [self.case_title, self.search, self.count, self.pagination, self.export_slot],
            layout=w.Layout(flex_flow="row wrap", align_items="center"),
        )
        self.case_header.add_class("sf-cases-header")
        self.cases.add_class("sf-cases-body")
        self.case_box = w.VBox([self.case_header, self.notice, self.cases])
        self.case_box.add_class("sf-cases-box")

    def _snapshot_link(self) -> str:
        if not self.snapshot.exists():
            return ""
        return download_link(self.snapshot, "Download")

    def _matching_indices(self, query: str) -> list[int]:
        matches = []
        offset = 0
        for owner in self.entries.owners:
            # WHY: a candidate-name match needs only positions, never a full content scan.
            positions = (
                range(len(owner.cases))
                if query in owner.name.casefold()
                else owner.cases._matching_indices(query)
            )
            matches.extend(offset + index for index in positions)
            offset += len(owner.cases)
        return matches

    def _search(self, change: Any) -> None:
        if self._paging:
            return
        query = self.search.value.strip().casefold()
        self.notice.value = ""
        if not query:
            self.matches = range(len(self.entries))
            self.page = 0
            self._render_page()
            return
        self.search.disabled = True
        self.previous.disabled = self.next.disabled = True
        self.count.value = "Searching…"
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self._search_ready(self._matching_indices(query))
            except (OSError, sqlite3.Error, ScreamingFaceError) as exc:
                self._search_failed(exc)
        else:
            self._search_task = loop.create_task(self._search_async(query))

    async def _search_async(self, query: str) -> None:
        # WHY: scanning disk-backed cases must not block the notebook's widget loop.
        try:
            matches = await asyncio.to_thread(self._matching_indices, query)
        except (OSError, sqlite3.Error, ScreamingFaceError) as exc:
            self._search_failed(exc)
        else:
            self._search_ready(matches)

    def _search_ready(self, matches: Sequence[int]) -> None:
        self.matches = matches
        self.page = 0
        self.search.disabled = False
        self._render_page()

    def _search_failed(self, exc: Exception) -> None:
        self.search.disabled = False
        self._render_page()
        self.notice.value = f'<p role="alert">Search failed: {escape(str(exc))}</p>'

    def _move(self, direction: int) -> None:
        if self.search.disabled and not self._paging:
            return
        last = max(0, (len(self.matches) - 1) // _PAGE_SIZE)
        current = self._requested_page if self._paging else self.page
        target = min(last, max(0, current + direction))
        if target == current:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.page = target
            self._render_page()
            return
        self._requested_page = target
        # INVARIANT: navigation stays clickable; only the latest requested page is published.
        self.previous.disabled = target == 0
        self.next.disabled = target == last
        self.previous.icon, self.next.icon = "chevron-left", "chevron-right"
        selected = self.next if direction > 0 else self.previous
        selected.icon = "spinner"
        if not self._paging:
            self._paging = True
            self.search.disabled = True
            self.notice.value = ""
            self._page_task = loop.create_task(self._load_page())

    async def _load_page(self) -> None:
        # WHY: coalesce a click burst and discard stale renders without blocking widgets.
        try:
            await asyncio.sleep(0.075)
            while self._requested_page != self.page:
                target = self._requested_page
                html = await asyncio.to_thread(self._page_html, target)
                if target == self._requested_page:
                    self.page = target
                    self.cases.value = html
                    break
        except (OSError, sqlite3.Error, ScreamingFaceError) as exc:
            self._requested_page = self.page
            self.notice.value = f'<p role="alert">Could not load cases: {escape(str(exc))}</p>'
        finally:
            self._paging = False
            self.search.disabled = False
            self.previous.icon = "chevron-left"
            self.next.icon = "chevron-right"
            self._page_controls()

    def _page_html(self, page: int) -> str:
        start = page * _PAGE_SIZE
        indices = self.matches[start : start + _PAGE_SIZE]
        return cases_page_html(
            self.report,
            [self.entries[index] for index in indices],
            framed=False,
            accounting_contexts=self._accounting_contexts,
        )

    def _page_controls(self) -> None:
        start = self.page * _PAGE_SIZE
        length = len(self.matches[start : start + _PAGE_SIZE])
        self.count.value = f"{start + 1 if length else 0}–{start + length} of {len(self.matches)}"
        self.previous.disabled = self.page == 0
        self.next.disabled = start + _PAGE_SIZE >= len(self.matches)

    def _render_page(self) -> None:
        self._requested_page = self.page
        self.cases.value = self._page_html(self.page)
        self._page_controls()

    def _export_json(self, change: Any = None) -> None:
        # INVARIANT: queued clicks cannot start concurrent or repeated exports of this Report.
        if self._exporting or self.snapshot.exists():
            return
        self._exporting = True
        self.export.disabled = True
        self.export.description = "Preparing…"
        self.export.icon = "spinner"
        self.notice.value = ""
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
        self.export.description = "Download"
        self.export.icon = ""
        self.notice.value = f'<p role="alert">Download failed: {escape(str(exc))}</p>'

    def _export_ready(self) -> None:
        self.exports.value = self._snapshot_link()
        self.notice.value = ""
        self.export_slot.children = (self.exports,)
        self._exporting = False

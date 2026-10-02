"""Live notebook Case browsing; only the current page enters widget state."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload
from uuid import uuid4

from screamingface._results.accounting import saved_accounting_context
from screamingface._ui.case_navigation import CaseNavigation
from screamingface._ui.report_files import download_link
from screamingface._ui.report_view import (
    _card_html,
    _failures_html,
    _group_key,
    cases_page_html,
    report_overview_html,
)
from screamingface._ui.style import NO_MATH_CLASSES
from screamingface.errors import ScreamingFaceError

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult, Report

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
.sf-cases-body .sf-rail__item>span{pointer-events:none}
.sf-cases-header .widget-button,.sf-cases-header .widget-box{flex-shrink:0}
.sf-report-browser .sf-browser-links a{display:inline-flex;align-items:center;
 justify-content:center;box-sizing:border-box;width:90px;min-height:28px;padding:2px 6px;
 margin:2px;border:1px solid var(--sf-line-2);background:var(--sf-bg);color:var(--sf-ink);
 font:inherit;text-decoration:none}
.sf-report-browser .sf-browser-links a:hover{background:var(--sf-surface)}
.sf-report-browser .sf-browser-links a:focus-visible{outline:2px solid var(--sf-accent)}
.sf-report-browser .widget-button:disabled{opacity:.55;cursor:default}
.sf-report-browser .fa-spinner{animation:sf-export-spin 1s linear infinite}
.sf-linked-card{position:relative;width:100%;padding:0 14px;box-sizing:border-box}
.sf-linked-card>.widget-html{width:100%;margin:0}
.sf-linked-card .sf-report__name{visibility:hidden}
.sf-report-browser .sf-candidate-name{position:absolute;top:27px;left:27px;
 border:0!important;background:transparent!important;padding:0!important;margin:0;
 height:20px;line-height:20px;font-size:14px;font-weight:600;text-align:left}
.sf-report-browser .sf-candidate-name:hover{text-decoration:underline;
 color:var(--sf-accent)!important}
.sf-report-browser .sf-candidate-active{color:var(--sf-accent)!important}
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
        self.navigation = CaseNavigation(report.candidates)
        self._focus_id = None
        self._updating_go_to = False
        self.page = 0
        self._requested_page = 0
        self._exporting = False
        self._export_prepared = False
        self._export_task = None
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
        self.go_to = w.Text(
            placeholder="Go to case number",
            continuous_update=False,
            layout=w.Layout(width="auto", min_width="120px", flex="1 1 120px"),
        )
        self.go_to.observe(self._go_to_case, names="value")
        self.candidate = w.Dropdown(
            options=[
                ("All Candidates", -1),
                *((owner.name, index) for index, owner in enumerate(self.entries.owners)),
            ],
            value=-1,
            tooltip="Filter candidates",
            layout=w.Layout(width="190px"),
            style={"description_width": "initial"},
        )
        self.candidate.observe(self._select_candidate, names="value")
        self.previous = w.Button(description="Previous", icon="chevron-left")
        self.next = w.Button(description="Next", icon="chevron-right")
        self.count = w.Label()
        self.cases = w.HTML()
        from ipyevents import Event

        # WHY: CSS selection stays instant; widget events synchronize only case identity.
        self._case_events = Event(source=self.cases, watched_events=["click"])
        self._case_events.on_dom_event(self._select_case)
        self.previous.on_click(lambda _: self._move(-1))
        self.next.on_click(lambda _: self._move(1))

    def _assemble(self) -> None:
        w = self.w
        self._accounting_contexts = {
            id(owner): saved_accounting_context(owner) for owner in self.entries.owners
        }
        self.exports = w.HTML(value=self._snapshot_link())
        self.export = w.Button(description="Download", layout=w.Layout(width="90px"))
        self.export.on_click(self._export_json)
        self.export_slot = w.VBox([self.export])
        self._case_box()

        self.widget = w.VBox(
            [
                w.HTML(value=_BROWSER_STYLE + report_overview_html(self.report)),
                *self._candidate_cards(),
                w.HTML(value=_failures_html(self.report)),
                self.case_box,
            ]
        )
        for name in ("sf-ui", "sf-report-browser", *NO_MATH_CLASSES):
            self.widget.add_class(name)

    def _candidate_cards(self):
        cards = []
        self.candidate_buttons = []
        for index, owner in enumerate(self.entries.owners):
            button = self.w.Button(
                description=owner.name,
                tooltip=f"View {owner.name} cases",
                layout=self.w.Layout(width="auto"),
            )
            button.add_class("sf-candidate-name")
            button.on_click(lambda _, index=index: setattr(self.candidate, "value", index))
            self.candidate_buttons.append(button)
            card = self.w.Box(
                [
                    self.w.HTML(
                        value=_card_html(
                            owner,
                            self.report,
                            context=self._accounting_contexts[id(owner)],
                            linked=True,
                        )
                    ),
                    button,
                ]
            )
            card.add_class("sf-linked-card")
            cards.append(card)
        return cards

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
            [
                self.case_title,
                self.candidate,
                self.go_to,
                self.count,
                self.pagination,
                self.export_slot,
            ],
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

    def _go_to_case(self, change: Any) -> None:
        if self._paging or self._updating_go_to:
            return
        self.notice.value = ""
        try:
            target = self.navigation.locate(self.go_to.value) if self.go_to.value.strip() else 0
        except ValueError as exc:
            self.notice.value = f'<p role="alert">{escape(str(exc))}</p>'
        else:
            self._focus_id = (
                self.navigation.resolve(self.go_to.value) if self.go_to.value.strip() else None
            )
            self._request_page(target)

    def _select_case(self, event: dict) -> None:
        target = event.get("target", {}).get("id", "")
        prefix = f"sf-case-{_group_key(self.report)}-"
        if self._paging or not isinstance(target, str) or not target.startswith(prefix):
            return
        try:
            index = int(target.removeprefix(prefix).removesuffix("-row"))
            indices = self.navigation.indices(self.page)
            if index < 0:
                return
            self._focus_id = self.entries[indices[index]][1].case_id
        except (ValueError, IndexError):
            return
        if self.go_to.value.strip():
            self._updating_go_to = True
            self.go_to.value = str(self._focus_id)
            self._updating_go_to = False

    def _select_candidate(self, change: Any) -> None:
        focused = (
            self._focus_id if self._focus_id is not None else self.navigation.focused_id(self.page)
        )
        selected = self.candidate.value
        assert isinstance(selected, int)
        self.navigation.select(selected)
        try:
            self.page = self.navigation.locate_id(focused)
        except ValueError:
            self.page = 0
            self._focus_id = None
        self.notice.value = ""
        for index, button in enumerate(self.candidate_buttons):
            if index == self.candidate.value:
                button.add_class("sf-candidate-active")
            else:
                button.remove_class("sf-candidate-active")
        self._render_page()

    def _move(self, direction: int) -> None:
        last = len(self.navigation.pages) - 1
        current = self._requested_page if self._paging else self.page
        target = min(last, max(0, current + direction))
        if target == current:
            return
        self._focus_id = None
        self._request_page(target, direction)

    def _request_page(self, target: int, direction: int = 1) -> None:
        last = len(self.navigation.pages) - 1
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
            self.go_to.disabled = self.candidate.disabled = True
            for button in self.candidate_buttons:
                button.disabled = True
            self.notice.value = ""
            self._page_task = loop.create_task(self._load_page())

    async def _load_page(self) -> None:
        # WHY: coalesce a click burst and discard stale renders without blocking widgets.
        try:
            await asyncio.sleep(0.075)
            while True:
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
            self.go_to.disabled = self.candidate.disabled = False
            for button in self.candidate_buttons:
                button.disabled = False
            self.previous.icon = "chevron-left"
            self.next.icon = "chevron-right"
            self._page_controls()

    def _page_html(self, page: int) -> str:
        indices = self.navigation.indices(page)
        entries = [self.entries[index] for index in indices]
        selected = next(
            (index for index, (_, case) in enumerate(entries) if case.case_id == self._focus_id), 0
        )
        return cases_page_html(
            self.report,
            entries,
            framed=False,
            accounting_contexts=self._accounting_contexts,
            selected=selected,
            navigation_mode="all" if self.navigation.selected == -1 else "candidate",
        )

    def _page_controls(self) -> None:
        if self._focus_id is None:
            self._focus_id = self.navigation.focused_id(self.page)
        if self.go_to.value.strip() and not self.notice.value:
            self._updating_go_to = True
            self.go_to.value = str(self._focus_id)
            self._updating_go_to = False
        self.count.value = self.navigation.caption(self.page)
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page + 1 >= len(self.navigation.pages)

    def _render_page(self) -> None:
        self._requested_page = self.page
        self.cases.value = self._page_html(self.page)
        self._page_controls()

    def _export_json(self, change: Any = None) -> None:
        # INVARIANT: queued clicks cannot start concurrent or repeated exports of this Report.
        if self._exporting or self._export_prepared:
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
        self._export_prepared = True
        self.exports.value = self._snapshot_link()
        self.notice.value = ""
        self.export_slot.children = (self.exports,)
        self._exporting = False

"""Live notebook Case browsing; only a page and one detail enter widget state."""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload
from uuid import uuid4

from screamingface._ui.accounting_view import case_accounting
from screamingface._ui.report_files import download_link
from screamingface._ui.report_view import _case_state, bounded_pane, report_html
from screamingface._ui.style import NO_MATH_CLASSES

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult, Report

_PAGE_SIZE = 25
_TEXT_PAGE = 12000
_BROWSER_STYLE = """<style>
.sf-report-browser .widget-button,.sf-report-browser input,.sf-report-browser select{
 border-radius:0!important;border:1px solid var(--sf-line-2)!important;
 background:var(--sf-bg)!important;color:var(--sf-ink)!important;box-shadow:none!important}
.sf-report-browser .widget-button:hover{background:var(--sf-surface)!important}
.sf-report-browser .widget-button:focus-visible{outline:2px solid var(--sf-accent)}
.sf-report-browser .widget-label{color:var(--sf-ink-2)}
.sf-report-browser .sf-pane{display:block}
.sf-report-browser .widget-select select{font-family:ui-monospace,monospace;font-size:12px}
.sf-report-browser .sf-browser-links a{color:var(--sf-accent);margin-right:16px}
.sf-report-browser .sf-browser-count{font-family:ui-monospace,monospace;font-size:12px}
.sf-report-browser .sf-full-content{white-space:pre-wrap;overflow-wrap:anywhere;
 max-height:440px;overflow:auto;border:1px solid var(--sf-line);padding:12px}
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
        self._updating = False
        self._text = ""
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
        self.cases = w.Select(rows=10, layout=w.Layout(width="100%"))
        self.detail = w.HTML()
        self.previous.on_click(lambda _: self._move(-1))
        self.next.on_click(lambda _: self._move(1))
        self.cases.observe(self._select, names="value")

    def _assemble(self) -> None:
        w = self.w
        self.full_field = w.Dropdown(
            description="Full content", options=["Input", "Output", "Case JSON"]
        )
        self.text_page = w.BoundedIntText(description="Text page", min=1, max=1, value=1)
        self.text_count = w.Label()
        self.full = w.HTML()
        self.full_field.observe(self._load_text, names="value")
        self.text_page.observe(self._show_text, names="value")
        self.exports = w.HTML(value=self._snapshot_link())
        export = w.Button(description="Export full JSON")
        export.on_click(self._export_json)
        full_box = w.VBox(
            [self._row([self.full_field, self.text_page, self.text_count]), self.full]
        )
        details = w.Tab(children=[self.detail, full_box])
        details.set_title(0, "Case detail")
        details.set_title(1, "Full content")
        self.widget = w.VBox(
            [
                w.HTML(
                    value=_BROWSER_STYLE + report_html(self.report, cases=False, download=False)
                ),
                self.notice,
                self.exports,
                export,
                self._row([self.previous, self.count, self.next]),
                self.cases,
                details,
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
        self._updating = True
        self.cases.options = [(self._label(index), index) for index in indices]
        self.cases.value = indices[0] if indices else None
        self._updating = False
        self._select()

    def _label(self, index: int) -> str:
        owner, case = self.entries[index]
        preview = case.prompt_preview[:70].replace("\n", " ")
        return f"{str(case.case_id)[:40]} · {owner.name[:40]} · {_case_state(case)} · {preview}"

    def _select(self, change: Any = None) -> None:
        if self._updating:
            return
        if self.cases.value is None:
            self.detail.value = "<p>No cases available.</p>"
        else:
            owner, case = self.entries[self.cases.value]
            cost = case_accounting(owner, case_ids={case.case_id})[case.case_id]
            self.detail.value = bounded_pane(owner, case, cost)
        self._load_text()

    def _load_text(self, change: Any = None) -> None:
        self._text = ""
        if self.cases.value is not None:
            case = self.entries[self.cases.value][1]
            self._text = self._case_text(case)
        self.text_page.max = max(1, (len(self._text) + _TEXT_PAGE - 1) // _TEXT_PAGE)
        self.text_page.value = 1
        self._show_text()

    def _case_text(self, case: CaseResult) -> str:
        if self.full_field.value == "Input":
            return case.display_input if case.input is not None else "Input unavailable"
        if self.full_field.value == "Output":
            return case.output or ""
        return json.dumps(case.to_dict(), ensure_ascii=False, indent=2)

    def _show_text(self, change: Any = None) -> None:
        start = (self.text_page.value - 1) * _TEXT_PAGE
        self.full.value = (
            '<pre class="sf-full-content">'
            + escape(self._text[start : start + _TEXT_PAGE])
            + "</pre>"
        )
        self.text_count.value = f"of {self.text_page.max} · {len(self._text):,} characters"

    def _export_json(self, change: Any = None) -> None:
        try:
            self.report.export(self.snapshot)
        except OSError as exc:
            self.notice.value = f'<p role="alert">Export failed: {escape(str(exc))}</p>'
            return
        self.exports.value = self._snapshot_link()

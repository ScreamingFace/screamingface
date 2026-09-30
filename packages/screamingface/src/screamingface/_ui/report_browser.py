"""Live notebook Case browsing; only a page and one detail enter widget state."""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from screamingface._ui.accounting_view import case_accounting
from screamingface._ui.report_files import download_link
from screamingface._ui.report_view import _case_state, bounded_pane, report_html
from screamingface._ui.style import NO_MATH_CLASSES

if TYPE_CHECKING:
    from screamingface.case_result import CaseResult
    from screamingface.report import Report

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


def _category(case: CaseResult) -> str:
    metadata = case.metadata or {}
    return str(metadata.get("category", metadata.get("clause_category", "Unspecified")))


def _search_text(case: CaseResult, query: str) -> bool:
    # WHY: search covers every retained field, including late text and metadata.
    return query in json.dumps(case.to_dict(), ensure_ascii=False).casefold()


def _matches_status(case: CaseResult, status: str | None) -> bool:
    if status == "ungraded":
        return case.grade is None or case.grade.score is None
    if status == "failed":
        return case.status == "failed"
    return not status or _case_state(case) == status


class ReportBrowser:
    """Kernel-backed controls over the immutable Report, with a durable full snapshot."""

    def __init__(self, report: Report) -> None:
        import ipywidgets as widgets

        self.w = widgets
        self.report = report
        self.entries = [(owner, case) for owner in report.candidates for case in owner.cases]
        self.matches = list(range(len(self.entries)))
        self.page = 0
        self._updating = False
        self._text = ""
        self.directory = Path("screamingface-reports") / uuid4().hex
        self.snapshot = self.directory / "report.json"
        self.notice = widgets.HTML()
        self._persist()
        self._controls()
        self._assemble()
        self._filter()

    def _persist(self) -> None:
        # INVARIANT: save before display; rendering never embeds the full artifact.
        try:
            self.report.export(self.snapshot)
        except OSError as exc:
            self.notice.value = (
                f'<p role="alert">Could not save report: {escape(str(exc))}. '
                "Results remain in the Report; use report.export() to save them.</p>"
            )

    def _controls(self) -> None:
        w = self.w
        self.search = w.Text(placeholder="Search all cases", continuous_update=True)
        self.status = w.Dropdown(
            description="Outcome",
            options=[
                ("All", ""),
                ("Correct", "passed"),
                ("Incorrect", "incorrect"),
                ("Failed", "failed"),
                ("Ungraded", "ungraded"),
            ],
        )
        self.candidate = w.Dropdown(
            description="Candidate",
            options=[("All", "")]
            + [
                (f"{owner.name} · {index + 1}", owner.run_id)
                for index, owner in enumerate(self.report.candidates)
            ],
        )
        self.category = w.Dropdown(
            description="Category",
            options=["All"] + sorted({_category(case) for _, case in self.entries}),
        )
        if self.category.options == ("All", "Unspecified"):
            self.category.layout.display = "none"
        self.sort = w.Dropdown(
            description="Sort",
            options=[("Original order", ""), ("Score ↑", "score"), ("Score ↓", "-score")],
        )
        self.previous = w.Button(description="Previous", icon="chevron-left")
        self.next = w.Button(description="Next", icon="chevron-right")
        self.count = w.Label()
        self.cases = w.Select(rows=10, layout=w.Layout(width="100%"))
        self.detail = w.HTML()
        for control in (self.search, self.status, self.candidate, self.category, self.sort):
            control.observe(self._filter, names="value")
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
        all_csv = w.Button(description="Export all CSV")
        filtered_csv = w.Button(description="Export filtered CSV")
        all_csv.on_click(lambda _: self._export_csv(False))
        filtered_csv.on_click(lambda _: self._export_csv(True))
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
                self._row([all_csv, filtered_csv]),
                w.HTML(value=self._counts_html()),
                self._row([self.search, self.status]),
                self._row([self.candidate, self.category, self.sort]),
                self._row([self.previous, self.count, self.next]),
                self.cases,
                details,
            ]
        )
        for name in ("sf-ui", "sf-report-browser", *NO_MATH_CLASSES):
            self.widget.add_class(name)

    def _row(self, children: list[Any]) -> Any:
        return self.w.HBox(children, layout=self.w.Layout(flex_flow="row wrap"))

    def _counts_html(self) -> str:
        graded = sum(
            case.grade is not None and case.grade.score is not None for _, case in self.entries
        )
        failed = sum(case.status == "failed" for _, case in self.entries)
        return (
            f"<p><b>{graded:,} of {len(self.entries):,} case results graded</b> · "
            f"{failed:,} failed · {len(self.entries) - graded:,} ungraded. "
            "Summary scores above always cover the original evaluation.</p>"
        )

    def _snapshot_link(self) -> str:
        if not self.snapshot.exists():
            return ""
        return download_link(self.snapshot, "Download all results · JSON (lossless)")

    def _matches(self, index: int) -> bool:
        owner, case = self.entries[index]
        checks = (
            not self.candidate.value or owner.run_id == self.candidate.value,
            _matches_status(case, self.status.value),
            self.category.value == "All" or _category(case) == self.category.value,
        )
        query = self.search.value.strip().casefold()
        return all(checks) and (
            not query or query in owner.name.casefold() or _search_text(case, query)
        )

    def _filter(self, change: Any = None) -> None:
        self.matches = [index for index in range(len(self.entries)) if self._matches(index)]
        if self.sort.value:
            self.matches.sort(key=self._score_key)
        self.page = 0
        self._render_page()

    def _score_key(self, index: int) -> tuple[bool, float]:
        grade = self.entries[index][1].grade
        score = grade.score if grade else None
        value = score if score is not None else 0.0
        return score is None, -value if self.sort.value == "-score" else value

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
            self.detail.value = "<p>No matching cases. Clear the filters to browse all results.</p>"
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

    def _export_csv(self, filtered: bool) -> None:
        scope = "filtered" if filtered else "all"
        indices = self.matches if filtered else range(len(self.entries))
        path = self.directory / f"{scope}-{uuid4().hex[:8]}.csv"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["candidate", "run_id", "case_id", "outcome", "score", "case_json"])
                for index in indices:
                    writer.writerow(self._csv_row(index))
        except OSError as exc:
            self.notice.value = f'<p role="alert">Export failed: {escape(str(exc))}</p>'
            return
        self.exports.value = self._snapshot_link() + download_link(
            path, f"Download {scope} CSV · {len(indices):,} case results"
        )

    def _csv_row(self, index: int) -> list[object]:
        owner, case = self.entries[index]

        # WHY: spreadsheet formula prefixes in untrusted labels must remain plain text.
        def cell(value: object) -> str:
            text = str(value)
            return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text

        return [
            cell(owner.name),
            cell(owner.run_id),
            cell(case.case_id),
            _case_state(case),
            case.grade.score if case.grade else None,
            json.dumps(case.to_dict(), ensure_ascii=False),
        ]

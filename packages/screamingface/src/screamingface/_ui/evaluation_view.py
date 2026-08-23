"""Live Candidate table for a running Evaluation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from decimal import Decimal
from html import escape
from typing import Any

from screamingface._evaluation.model import Candidate
from screamingface._ui.evaluation_state import _CandidateProgress, _EvaluationProgress
from screamingface._ui.style import FUSION_GRADIENT, STYLE
from screamingface.events import Event
from screamingface.report import Report

_STYLE = (
    STYLE
    + """<style>
.sf-eval{border:0;padding:4px 0 14px;font-family:"IBM Plex Sans",system-ui,sans-serif}
.sf-eval__title-row{display:flex;align-items:baseline;justify-content:space-between;gap:16px}
.sf-eval__title{font-size:20px;font-weight:600;line-height:1.2;letter-spacing:-.01em}
.sf-eval__title-state{flex:0 0 auto;text-align:right;white-space:nowrap;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;color:var(--sf-ink-2);
  font-variant-numeric:tabular-nums}
.sf-eval__note{margin-top:10px;padding:7px 10px;border:1px solid var(--sf-line);
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;color:var(--sf-ink-2)}
.sf-eval__overall{margin-top:8px}
.sf-eval__overall-track{height:8px;background:var(--sf-line);overflow:hidden}
.sf-eval__overall-fill{display:block;height:100%;background-repeat:no-repeat;
  background-position:right center;transition:width .11s linear}
.sf-eval__table-wrap{margin-top:12px;border:1px solid var(--sf-line)}
.sf-eval__table{width:100%;table-layout:fixed;border-collapse:collapse;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px;
  font-variant-numeric:tabular-nums}
.sf-eval__col--candidate{width:27%}
.sf-eval__col--status{width:17%}
.sf-eval__col--cases{width:10%}
.sf-eval__col--score{width:17%}
.sf-eval__col--cost{width:14%}
.sf-eval__col--cache{width:15%}
.sf-eval__table caption{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.sf-eval__table th,.sf-eval__table td{padding:12px 16px;text-align:left;
  border-bottom:1px solid var(--sf-line);vertical-align:middle;overflow-wrap:anywhere}
.sf-eval__table th{position:sticky;top:0;z-index:2;background:var(--sf-surface);
  color:var(--sf-ink-2);font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.1em;
  border-bottom:1px solid var(--sf-line-2);
  white-space:nowrap}
.sf-eval__table tbody tr:hover{background:var(--sf-surface)}
.sf-eval__table tbody tr:last-child td{border-bottom:0}
.sf-eval__candidate{font-family:"IBM Plex Sans",system-ui,sans-serif;font-weight:500;
  color:var(--sf-ink)}
.sf-eval__status{display:inline-flex;align-items:center;gap:8px;color:var(--sf-ink-2);
  font-family:"IBM Plex Sans",system-ui,sans-serif;white-space:nowrap}
.sf-eval__status-sq{width:9px;height:9px;flex:0 0 auto;background:var(--sf-ink-3)}
.sf-eval__status--running .sf-eval__status-sq{background:var(--sf-accent)}
.sf-eval__status--finished .sf-eval__status-sq{background:var(--sf-success-solid)}
.sf-eval__status--run_failed .sf-eval__status-sq,.sf-eval__status--stopped .sf-eval__status-sq,
.sf-eval__status--timed_out .sf-eval__status-sq{background:var(--sf-danger-solid)}
.sf-eval__cases{color:var(--sf-ink);white-space:nowrap}
.sf-eval__unavailable{color:var(--sf-ink-2);white-space:nowrap}
.sf-eval__receipt{margin-top:7px;min-height:1.45em;
  font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11.5px;color:var(--sf-ink-2);font-variant-numeric:tabular-nums}
.sf-eval__receipt-success{color:var(--sf-success);font-weight:500}
.sf-eval__num{text-align:right}
.sf-eval__err{margin-top:10px;padding:8px 10px;border-left:2px solid var(--sf-blind);
  background:var(--sf-blind-bg);color:var(--sf-blind);font-family:"IBM Plex Mono",ui-monospace,
  monospace;font-size:12px;white-space:pre-wrap}
.sf-eval__announce{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
</style>"""
)


def evaluation_panel_html(
    progress: _EvaluationProgress,
    benchmark: str | None = None,
    elapsed: float | None = None,
    check_disclosure: str | None = None,
) -> str:
    title = escape(benchmark) if benchmark else "Evaluation"
    return (
        f"{_STYLE}<div class='sf-ui sf-eval' aria-label='ScreamingFace evaluation progress'>"
        "<div class='sf-eval__title-row'>"
        f"<div class='sf-eval__title'>{title}</div>"
        f"{_title_state_html(progress)}"
        "</div>"
        f"{_note_html(check_disclosure)}"
        f"{_overall_progress_html(progress)}"
        f"{_receipt_html(progress)}"
        f"{_candidate_table_html(progress, elapsed)}"
        f"{_error_html(progress)}"
        f"<div class='sf-eval__announce' aria-live='polite'>{escape(progress.announcement)}</div>"
        "</div>"
    )


def _overall_progress_html(progress: _EvaluationProgress) -> str:
    if progress.complete:
        return ""
    counts = _overall_counts(progress)
    if counts is None:
        return ""
    completed, total, percent_value = counts
    percent = f"{percent_value:.6f}".rstrip("0").rstrip(".")
    background_size = "100" if completed == 0 else f"{10000 / percent_value:.1f}"
    return (
        "<div class='sf-eval__overall'>"
        "<div class='sf-eval__overall-track' role='progressbar' "
        f"aria-label='Overall Case progress' aria-valuemin='0' aria-valuemax='{total}' "
        f"aria-valuenow='{completed}'>"
        f"<span class='sf-eval__overall-fill' style='width:{percent}%;"
        f"background-size:{background_size}% 100%;background-image:{FUSION_GRADIENT}'></span>"
        "</div></div>"
    )


def _overall_counts(progress: _EvaluationProgress) -> tuple[int, int, float] | None:
    totals = tuple(row.total_cases for row in progress.rows)
    if any(total is None for total in totals):
        return None
    total = sum(total for total in totals if total is not None)
    if total == 0:
        return None
    completed = sum(
        min(row.completed_cases, row.total_cases)
        for row in progress.rows
        if row.total_cases is not None
    )
    percent_value = completed / total * 100
    return completed, total, percent_value


def _title_state_html(progress: _EvaluationProgress) -> str:
    state = _overall_state(progress)
    if progress.duration_seconds is not None:
        state = f"{state} · {_duration(progress.duration_seconds)}"
    elif (counts := _overall_counts(progress)) is not None:
        rounded_percent = int(counts[2] + 0.5)
        state = f"{state} · {rounded_percent}%"
    return f"<div class='sf-eval__title-state'>{state}</div>"


def _overall_state(progress: _EvaluationProgress) -> str:
    if progress.complete:
        state = "complete"
    elif not progress.finished:
        state = "evaluating…"
    else:
        statuses = {row.status for row in progress.rows}
        state = next(
            (
                label
                for status, label in (
                    ("stopped", "stopped"),
                    ("timed_out", "timed out"),
                    ("run_failed", "failed"),
                )
                if status in statuses
            ),
            "ended",
        )
    return state


def _receipt_html(progress: _EvaluationProgress) -> str:
    if progress.fully_cached:
        unit = "model call" if progress.model_calls == 1 else "model calls"
        return (
            "<div class='sf-eval__receipt'>"
            f"{progress.model_calls:,} {unit} · "
            "<span class='sf-eval__receipt-success'>fully cached</span> · "
            "no tokens billed</div>"
        )
    parts: list[str] = []
    if progress.cost_usd is not None:
        parts.append(f"cost {_money(progress.cost_usd)}")
    if progress.model_calls:
        unit = "model call" if progress.model_calls == 1 else "model calls"
        parts.append(f"{progress.model_calls:,} {unit}")
    if progress.have_tokens:
        input_tokens = _compact(progress.input_tokens)
        output_tokens = _compact(progress.output_tokens)
        parts.append(f"{input_tokens} in / {output_tokens} out")
    if not parts:
        return "<div class='sf-eval__receipt' aria-hidden='true'></div>"
    return f"<div class='sf-eval__receipt'>{' · '.join(parts)}</div>"


def _candidate_table_html(progress: _EvaluationProgress, elapsed: float | None) -> str:
    headers = (
        ("Candidate", False),
        ("Status", False),
        ("Cases", True),
        ("Score", True),
        ("Cost", True),
        ("Cache hit", True),
    )
    head = "".join(
        f"<th scope='col'{" class='sf-eval__num'" if numeric else ''}>{header}</th>"
        for header, numeric in headers
    )
    body = "".join(_candidate_row_html(row, elapsed) for row in progress.rows)
    columns = "".join(
        f"<col class='sf-eval__col--{name}'>"
        for name in ("candidate", "status", "cases", "score", "cost", "cache")
    )
    return (
        "<div class='sf-eval__table-wrap'>"
        "<table class='sf-eval__table'>"
        "<caption>Candidate Evaluation progress</caption>"
        f"<colgroup>{columns}</colgroup>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _candidate_row_html(row: _CandidateProgress, elapsed: float | None) -> str:
    status = {
        "queued": "Queued",
        "running": "Running",
        "finished": "Finished",
        "run_failed": "Run failed",
        "stopped": "Stopped",
        "timed_out": "Timed out",
        "not_run": "Not run",
    }[row.status]
    details = [row.qualifier] if row.qualifier is not None else []
    if row.status == "running" and elapsed is not None:
        started = row.started_elapsed_seconds or 0.0
        details.append(_duration(max(0.0, elapsed - started)))
    elif row.duration_seconds is not None:
        details.append(_duration(row.duration_seconds))
    suffix = "".join(f" · {escape(detail)}" for detail in details)
    score = (
        "Not scored yet"
        if not row.score_available and row.status in {"queued", "running"}
        else "Not scored"
        if not row.score_available or row.score is None
        else f"{row.score:g}"
    )
    cost = "Not reported" if row.cost_usd is None else _money(row.cost_usd)
    cache = _cache_value(row)
    progress_html = _case_progress_html(row)
    return (
        "<tr>"
        f"<td><span class='sf-eval__candidate'>{escape(row.candidate.name)}</span></td>"
        f"<td><span class='sf-eval__status sf-eval__status--{row.status}'>"
        f"<span class='sf-eval__status-sq' aria-hidden='true'></span>{status}{suffix}</span></td>"
        f"<td class='sf-eval__num'>{progress_html}</td>"
        f"<td class='sf-eval__unavailable sf-eval__num'>{escape(score)}</td>"
        f"<td class='sf-eval__unavailable sf-eval__num'>{escape(cost)}</td>"
        f"<td class='sf-eval__unavailable sf-eval__num'>{escape(cache)}</td></tr>"
    )


def _case_progress_html(row: _CandidateProgress) -> str:
    if row.total_cases is None:
        unit = "case" if row.completed_cases == 1 else "cases"
        return f"<span class='sf-eval__unavailable'>{row.completed_cases} {unit} finished</span>"
    label = f"{row.completed_cases} / {row.total_cases}"
    return f"<span class='sf-eval__cases'>{label}</span>"


def _cache_value(row: _CandidateProgress) -> str:
    totals = row.cache_totals
    if totals is None:
        return "Not reported"
    hits, misses, bypasses = totals
    cacheable = hits + misses
    if cacheable:
        return f"{hits / cacheable:.1%}"
    return "Bypassed" if bypasses else "Not reported"


def _note_html(check_disclosure: str | None) -> str:
    if check_disclosure is None:
        return ""
    return f"<div class='sf-eval__note'>check surface · {escape(check_disclosure)}</div>"


def _error_html(progress: _EvaluationProgress) -> str:
    if progress.error is None:
        return ""
    return f"<div class='sf-eval__err' role='alert'>{escape(progress.error)}</div>"


def _compact(value: int) -> str:
    if value < 1_000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1_000:.1f}k"
    return f"{value / 1_000_000:.1f}M"


def _money(value: Decimal) -> str:
    if value != 0 and abs(value) < Decimal("0.01"):
        return f"${value:.4f}"
    return f"${value:,.2f}"


def _duration(seconds: float) -> str:
    whole_seconds = int(seconds)
    if whole_seconds < 60:
        return f"{whole_seconds}s"
    minutes, remainder = divmod(whole_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    hour_unit = "hr" if hours == 1 else "hrs"
    return f"{hours}{hour_unit} {minutes:02d}min"


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
        self._html: Any = widgets.HTML(value=self._render())
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
                self._html.value = self._render()
        self._dirty.set()

    def begin(self, candidate: Candidate) -> None:
        with self._lock:
            self._progress.begin(candidate)
            if not self._tick:
                self._html.value = self._render()
        self._dirty.set()

    def reconcile(self, report: Report) -> None:
        with self._lock:
            self._progress.reconcile(report)
            self._html.value = self._render()
        self._done.set()
        self._dirty.set()

    def abort(self, exc: BaseException) -> None:
        with self._lock:
            self._progress.abort(exc)
            self._html.value = self._render()
        self._done.set()
        self._dirty.set()

    def close(self) -> None:
        self._done.set()
        self._dirty.set()

    def _render(self) -> str:
        elapsed = None if self._progress.finished else self._clock() - self._started
        return evaluation_panel_html(
            self._progress, self._benchmark, elapsed, self._check_disclosure
        )

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
                    self._html.value = self._render()
            except Exception:
                break

    def _show(self) -> None:
        if self._shown:
            return
        from IPython.display import display

        display(self._html)
        self._shown = True


__all__: list[str] = []

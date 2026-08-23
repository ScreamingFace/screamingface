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
from screamingface._ui.style import STYLE
from screamingface.events import Event
from screamingface.report import Report

_STYLE = (
    STYLE
    + """<style>
.sf-eval{border:0;padding:4px 14px 14px;font-family:"IBM Plex Sans",system-ui,sans-serif}
.sf-eval__title{font-size:20px;font-weight:700;line-height:1.2;letter-spacing:-.01em}
.sf-eval__sub{font-size:13px;color:var(--sf-ink-2);margin-top:3px}
.sf-eval__note{margin-top:10px;padding:7px 10px;border:1px solid var(--sf-line);
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;color:var(--sf-ink-2)}
.sf-eval__table-wrap{margin-top:14px;overflow-x:auto;border:1px solid var(--sf-line);
  scrollbar-gutter:stable}
.sf-eval__table{width:100%;min-width:820px;border-collapse:collapse;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;
  font-variant-numeric:tabular-nums}
.sf-eval__table caption{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.sf-eval__table th,.sf-eval__table td{padding:10px 12px;text-align:left;
  border-bottom:1px solid var(--sf-line);vertical-align:middle;white-space:nowrap}
.sf-eval__table th{position:sticky;top:0;z-index:2;background:var(--sf-surface);
  color:var(--sf-ink-2);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.sf-eval__table tbody tr:last-child td{border-bottom:0}
.sf-eval__table th:first-child,.sf-eval__table td:first-child{position:sticky;left:0;z-index:1;
  background:var(--sf-bg);border-right:1px solid var(--sf-line)}
.sf-eval__table th:first-child{z-index:3;background:var(--sf-surface)}
.sf-eval__candidate{font-family:"IBM Plex Sans",system-ui,sans-serif;font-weight:600;
  color:var(--sf-ink)}
.sf-eval__candidate-model{display:block;margin-top:2px;font-size:11px;font-weight:400;
  color:var(--sf-ink-2);font-family:"IBM Plex Mono",ui-monospace,monospace}
.sf-eval__status{display:inline-flex;align-items:center;gap:7px;color:var(--sf-ink-2);
  font-family:"IBM Plex Sans",system-ui,sans-serif}
.sf-eval__status-sq{width:9px;height:9px;flex:0 0 auto;background:var(--sf-ink-3)}
.sf-eval__status--running .sf-eval__status-sq{background:var(--sf-accent)}
.sf-eval__status--finished .sf-eval__status-sq{background:var(--sf-success-solid)}
.sf-eval__status--run_failed .sf-eval__status-sq,.sf-eval__status--stopped .sf-eval__status-sq,
.sf-eval__status--timed_out .sf-eval__status-sq{background:var(--sf-blind)}
.sf-eval__activity{display:block;margin-top:2px;color:var(--sf-ink-2);font-size:11px}
.sf-eval__progress{display:flex;align-items:center;gap:9px;min-width:150px}
.sf-eval__progress progress{appearance:none;width:88px;height:6px;border:0;
  background:var(--sf-line)}
.sf-eval__progress progress::-webkit-progress-bar{background:var(--sf-line)}
.sf-eval__progress progress::-webkit-progress-value{background:var(--sf-accent)}
.sf-eval__progress progress::-moz-progress-bar{background:var(--sf-accent)}
.sf-eval__progress progress{transition:color .15s ease}
.sf-eval__unavailable{color:var(--sf-ink-2)}
.sf-eval__stats{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--sf-line);
  border-top:0}
.sf-eval__stat{padding:10px 12px;border-right:1px solid var(--sf-line);min-width:0}
.sf-eval__stat:last-child{border-right:0}
.sf-eval__stat-k{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-2)}
.sf-eval__stat-v{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:18px;
  margin-top:3px;font-variant-numeric:tabular-nums;color:var(--sf-ink)}
.sf-eval__cache{border:1px solid var(--sf-line);border-top:0;display:flex;flex-wrap:wrap;
  align-items:baseline;gap:6px 14px;padding:9px 12px}
.sf-eval__cache-k{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-2)}
.sf-eval__cache-v{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:18px;
  color:var(--sf-ink)}
.sf-eval__cache-of,.sf-eval__cache-why{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:11.5px;color:var(--sf-ink-2)}
.sf-eval__activity-log{margin-top:12px;border:1px solid var(--sf-line);padding:8px 10px;
  color:var(--sf-ink-2);font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px}
.sf-eval__activity-log summary{cursor:pointer;color:var(--sf-ink-2)}
.sf-eval__activity-row{padding:5px 0;border-top:1px solid var(--sf-line)}
.sf-eval__err{margin-top:10px;padding:8px 10px;border-left:2px solid var(--sf-blind);
  background:var(--sf-blind-bg);color:var(--sf-blind);font-family:"IBM Plex Mono",ui-monospace,
  monospace;font-size:12px;white-space:pre-wrap}
.sf-eval__announce{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(prefers-reduced-motion:reduce){.sf-eval__progress progress{transition:none}}
</style>"""
)


def evaluation_panel_html(
    progress: _EvaluationProgress,
    benchmark: str | None = None,
    elapsed: float | None = None,
    check_disclosure: str | None = None,
) -> str:
    title = "Evaluation complete" if progress.finished else "Evaluating"
    subtitle = f"Benchmark · {escape(benchmark)}" if benchmark else "Live run status"
    return (
        f"{_STYLE}<div class='sf-ui sf-eval' aria-label='ScreamingFace evaluation progress'>"
        f"<div class='sf-eval__title'>{title}</div>"
        f"<div class='sf-eval__sub'>{subtitle}</div>"
        f"{_note_html(check_disclosure)}"
        f"{_candidate_table_html(progress, elapsed)}"
        f"{_stats_html(progress)}"
        f"{_cache_html(progress)}"
        f"{_activity_html(progress)}"
        f"{_error_html(progress)}"
        f"<div class='sf-eval__announce' aria-live='polite'>{escape(progress.announcement)}</div>"
        "</div>"
    )


def _candidate_table_html(progress: _EvaluationProgress, elapsed: float | None) -> str:
    headers = ("Candidate", "Status", "Progress", "Score", "Cost", "Cache")
    head = "".join(f"<th scope='col'>{header}</th>" for header in headers)
    body = "".join(_candidate_row_html(row, elapsed) for row in progress.rows)
    return (
        "<div class='sf-eval__table-wrap' tabindex='0' "
        "aria-label='Scrollable Candidate progress table'>"
        "<table class='sf-eval__table'>"
        "<caption>Candidate Evaluation progress</caption>"
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
    qualifier = f" · {escape(row.qualifier)}" if row.qualifier is not None else ""
    activity_text = row.activity
    if row.status == "running" and elapsed is not None:
        started = row.started_elapsed_seconds or 0.0
        duration = _duration(max(0.0, elapsed - started))
        activity_text = f"{activity_text} · {duration}" if activity_text else duration
    activity = (
        f"<span class='sf-eval__activity'>{escape(activity_text)}</span>"
        if activity_text is not None
        else ""
    )
    models = ", ".join(row.candidate.models)
    score = (
        "Not scored yet"
        if not row.score_available
        else "Not scored"
        if row.score is None
        else f"{row.score:g}"
    )
    cost = "Not reported" if row.cost_usd is None else _money(row.cost_usd)
    cache = "Not reported" if row.cache_hit_rate is None else f"{row.cache_hit_rate:.1%}"
    progress_html = _case_progress_html(row)
    return (
        "<tr>"
        f"<td><span class='sf-eval__candidate'>{escape(row.candidate.name)}</span>"
        f"<span class='sf-eval__candidate-model'>{escape(models)}</span></td>"
        f"<td><span class='sf-eval__status sf-eval__status--{row.status}'>"
        f"<span class='sf-eval__status-sq' aria-hidden='true'></span>{status}{qualifier}</span>"
        f"{activity}</td>"
        f"<td>{progress_html}</td>"
        f"<td class='sf-eval__unavailable'>{escape(score)}</td>"
        f"<td class='sf-eval__unavailable'>{escape(cost)}</td>"
        f"<td class='sf-eval__unavailable'>{escape(cache)}</td></tr>"
    )


def _case_progress_html(row: _CandidateProgress) -> str:
    if row.total_cases is None:
        unit = "case" if row.completed_cases == 1 else "cases"
        return f"<span class='sf-eval__unavailable'>{row.completed_cases} {unit} finished</span>"
    label = f"{row.completed_cases} / {row.total_cases}"
    return (
        f"<span class='sf-eval__progress'><progress value='{row.completed_cases}' "
        f"max='{row.total_cases}' aria-label='{escape(row.candidate.name)} Case progress'>"
        f"</progress><span>{label}</span></span>"
    )


def _stats_html(progress: _EvaluationProgress) -> str:
    calls = "—" if progress.model_calls == 0 else f"{progress.model_calls:,}"
    if progress.failed_calls:
        calls = f"{calls} · {progress.failed_calls} failed"
    tokens = (
        f"{_compact(progress.input_tokens)} / {_compact(progress.output_tokens)}"
        if progress.have_tokens
        else "—"
    )
    cost = "—" if progress.cost_usd is None else _money(progress.cost_usd)
    cells = (("model calls", calls), ("tokens in / out", tokens), ("cost", cost))
    body = "".join(
        f"<div class='sf-eval__stat'><div class='sf-eval__stat-k'>{key}</div>"
        f"<div class='sf-eval__stat-v'>{value}</div></div>"
        for key, value in cells
    )
    return f"<div class='sf-eval__stats'>{body}</div>"


def _cache_html(progress: _EvaluationProgress) -> str:
    rate = progress.cache_hit_rate
    value = "—" if rate is None else f"{rate:.1%}"
    counts = progress.cache_totals
    if counts is None:
        detail = "no cache activity reported"
        why = ""
    else:
        hits, misses, bypasses = counts
        detail = f"{hits:,} hit · {misses:,} miss"
        reasons = " · ".join(
            f"{escape(reason)} {count:,}" for reason, count in progress.cache_bypass_breakdown
        )
        tail = f" — {reasons}" if reasons else ""
        why = (
            f"<span class='sf-eval__cache-why'>{bypasses:,} bypassed{tail}</span>"
            if bypasses
            else ""
        )
    return (
        "<div class='sf-eval__cache'><span class='sf-eval__cache-k'>cache</span>"
        f"<span class='sf-eval__cache-v'>{value}</span>"
        f"<span class='sf-eval__cache-of'>{detail}</span>{why}</div>"
    )


def _activity_html(progress: _EvaluationProgress) -> str:
    rows = "".join(
        f"<div class='sf-eval__activity-row'>{escape(row.candidate.name)} · "
        f"{escape(row.activity)}</div>"
        for row in progress.rows
        if row.activity is not None
    )
    return f"<details class='sf-eval__activity-log'><summary>Run activity</summary>{rows}</details>"


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
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


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

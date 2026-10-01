"""Case-scoped accounting blocks and script-free notebook view selectors."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING
from uuid import uuid4

from screamingface.accounting import (
    AccountingBreakdown,
    AccountingRow,
    AccountingSummary,
    _AccountingContext,
    _iter_rows,
    summarize,
)

if TYPE_CHECKING:
    from screamingface._report_primitives import CaseId
    from screamingface.case_result import CaseResult
    from screamingface.report import CandidateResult

STYLE = """<style>
.sf-case-views{margin-top:16px}
.sf-view-radio{position:absolute;opacity:0;width:1px;height:1px}
.sf-view-label{display:inline-block;padding:8px 0;border-bottom:2px solid transparent;
  color:var(--sf-ink-2);cursor:pointer;font-size:13px;margin:0 20px 12px 0}
.sf-view-radio:checked+.sf-view-label{color:var(--sf-ink);border-bottom-color:var(--sf-accent);font-weight:500}
.sf-view-radio:focus-visible+.sf-view-label{outline:2px solid var(--sf-accent);outline-offset:2px}
.sf-answer-view,.sf-cost-view{display:none}
.sf-view-answer:checked~.sf-answer-view,.sf-view-cost:checked~.sf-cost-view{display:block}
.sf-cost-view p,.sf-run-accounting-note{font-size:12px;color:var(--sf-ink-2)}
.sf-cost-block{padding:12px 0}
.sf-cost-block+.sf-cost-block{border-top:1px solid var(--sf-line)}
.sf-cost-block header{display:flex;align-items:baseline;justify-content:space-between;gap:16px}
.sf-cost-price{font:500 14px "IBM Plex Mono",ui-monospace,monospace;
  color:var(--sf-ink);white-space:nowrap}
.sf-cost-price small{font:400 11px "IBM Plex Sans",sans-serif;
  color:var(--sf-ink-2);margin-right:8px}
.sf-cost-block h4{font-size:14px;font-weight:600;margin:0 0 4px;color:var(--sf-ink)}
.sf-cost-model{font-size:12px;color:var(--sf-ink-2);overflow-wrap:anywhere}
.sf-report dl.sf-cost-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;margin:12px 0 0}
.sf-report .sf-cost-fields>div{display:flex;flex-direction:column;min-width:0}
.sf-report .sf-cost-fields dt{float:none;width:auto;
  font-size:11px;color:var(--sf-ink-2);font-weight:400}
.sf-report .sf-cost-fields dd+dt{margin-top:8px}
.sf-report .sf-cost-fields dd{font-size:13px;color:var(--sf-ink);margin:4px 0 0;
  font-family:"IBM Plex Mono",ui-monospace,monospace;overflow-wrap:anywhere}
</style>"""


def case_tabs(answer: str, cost: str) -> str:
    """Native radio semantics provide keyboard switching without sanitizable scripts."""
    # WHY: render instances, including the same Report displayed twice, must not share controls.
    key = f"sf-view-{uuid4().hex}"
    return (
        "<div class='sf-case-views' role='group' aria-label='Case view'>"
        f"<input class='sf-view-radio sf-view-answer' type='radio' name='{key}' "
        f"id='{key}-answer' checked><label class='sf-view-label' for='{key}-answer'>"
        "Answer &amp; grading</label>"
        f"<input class='sf-view-radio sf-view-cost' type='radio' name='{key}' "
        f"id='{key}-cost'><label class='sf-view-label' for='{key}-cost'>Cost &amp; usage</label>"
        f"<div class='sf-answer-view'>{answer}</div>"
        f"<div class='sf-cost-view' aria-label='Cost and usage for this case'>{cost}</div></div>"
    )


def run_accounting_note(
    candidate: CandidateResult, *, context: _AccountingContext | None = None
) -> str:
    """A remainder belongs to the run, never to an individual Case by inference."""
    view = candidate.accounting if context is None else context
    if not view.consistent:
        text = "Accounting breakdown unavailable: inconsistent records."
    elif view.unattributed_cost_usd == 0:
        return ""
    else:
        text = f"Unattributed run cost: {_money(view.unattributed_cost_usd)}."
    return f'<p class="sf-run-accounting-note">{escape(text)}</p>'


def case_accounting(
    candidate: CandidateResult,
    *,
    case_ids: set[CaseId] | None = None,
    context: _AccountingContext | None = None,
    cases: Sequence[CaseResult] | None = None,
) -> dict[CaseId, str]:
    """Group once per Candidate, retaining only the selected Case's actual owners."""
    view: AccountingBreakdown | _AccountingContext
    rows: Iterable[AccountingRow]
    if context is None:
        view = candidate.accounting
        rows = view.rows
    else:
        view = context
        rows = (
            _iter_rows(
                candidate,
                cases if cases is not None else candidate.cases,
                context.operation_models,
                context.judge_models,
            )
            if context.consistent
            else ()
        )
    # WHY: page identities are already known; finding them must not reread every prompt.
    selected = case_ids if case_ids is not None else {case.case_id for case in candidate.cases}
    groups: dict[CaseId, list[AccountingRow]] = {case_id: [] for case_id in selected}
    for row in rows:
        if row.case_id in groups:
            groups[row.case_id].append(row)
    return {
        case_id: (
            "".join(_activity(row) for row in rows)
            if view.consistent and rows
            else "<p>Accounting unavailable for this case. See the whole-run totals above.</p>"
        )
        for case_id, rows in groups.items()
    }


def _activity(row: AccountingRow) -> str:
    summary = summarize([row.accounting])
    stage = {
        "generation": "Answer generation",
        "synthesis": "Combine answers",
        "grading": "Judging",
    }
    groups = (
        (("Calls", _number(summary.calls)), ("Cache", _cache(summary))),
        (
            ("Input tokens", _number(summary.usage.input_tokens)),
            ("Output tokens", _number(summary.usage.output_tokens)),
        ),
        (("Provider time", _time(summary.provider_latency_ms)),),
    )
    values = "".join(
        "<div>"
        + "".join(f"<dt>{label}</dt><dd>{escape(value)}</dd>" for label, value in group)
        + "</div>"
        for group in groups
    )
    return (
        f'<section class="sf-cost-block"><header><h4>{escape(row.label)}</h4>'
        f'<span class="sf-cost-price"><small>Cost</small>{_money(summary.usage.cost_usd)}</span>'
        "</header>"
        f'<div class="sf-cost-model">{stage[row.stage]} · '
        f"{escape(row.model or 'Unknown model')}</div>"
        f'<dl class="sf-cost-fields">{values}</dl></section>'
    )


def _cache(summary: AccountingSummary) -> str:
    cache = summary.cache
    if cache is None:
        return "Unknown"
    counts = (
        (cache.hits, "hit", "hits"),
        (cache.misses, "miss", "misses"),
        (cache.bypasses, "bypass", "bypasses"),
        (cache.unknown, "unknown", "unknown"),
    )
    return (
        " · ".join(
            f"{count:,} {singular if count == 1 else plural}"
            for count, singular, plural in counts
            if count
        )
        or "No calls"
    )


def _number(value: int | None) -> str:
    return "Unknown" if value is None else f"{value:,}"


def _money(value: Decimal | None) -> str:
    if value is None:
        return "Unknown"
    # WHY: a real charge must never look like a free call after display rounding.
    if 0 < abs(value) < Decimal("0.0001"):
        return "$" + format(value, ",f").rstrip("0")
    return f"${value:,.4f}"


def _time(value: int | None) -> str:
    return "Unknown" if value is None else f"{value / 1000:,.3f}s"

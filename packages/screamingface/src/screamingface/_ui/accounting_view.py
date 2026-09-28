"""Case-scoped accounting blocks and script-free notebook view selectors."""

from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING
from uuid import uuid4

from screamingface.accounting import AccountingRow, AccountingSummary, summarize

if TYPE_CHECKING:
    from screamingface._report_primitives import CaseId
    from screamingface.report import CandidateResult

STYLE = """<style>
.sf-case-views{margin-top:16px}
.sf-view-radio{position:absolute;opacity:0;width:1px;height:1px}
.sf-view-label{display:inline-block;padding:8px 12px;border:1px solid var(--sf-line);
  color:var(--sf-ink-2);cursor:pointer;font-size:13px;margin-bottom:16px}
.sf-view-radio:checked+.sf-view-label{color:var(--sf-ink);border-bottom:2px solid var(--sf-accent);
  background:var(--sf-surface)}
.sf-view-radio:focus-visible+.sf-view-label{outline:2px solid var(--sf-accent);outline-offset:2px}
.sf-answer-view,.sf-cost-view{display:none}
.sf-view-answer:checked~.sf-answer-view,.sf-view-cost:checked~.sf-cost-view{display:block}
.sf-cost-view p,.sf-run-accounting-note{font-size:12px;color:var(--sf-ink-2)}
.sf-cost-block{border-top:1px solid var(--sf-line);padding:16px 0}
.sf-cost-block h4{font-size:14px;font-weight:600;margin:0 0 4px;color:var(--sf-ink)}
.sf-cost-model{font-size:12px;color:var(--sf-ink-2);overflow-wrap:anywhere}
.sf-report dl.sf-cost-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:16px;margin:16px 0 0}
.sf-report .sf-cost-fields>div{display:flex;flex-direction:column;min-width:0}
.sf-report .sf-cost-fields dt{float:none;width:auto;
  font-size:11px;color:var(--sf-ink-2);font-weight:400}
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


def run_accounting_note(candidate: CandidateResult) -> str:
    """A remainder belongs to the run, never to an individual Case by inference."""
    view = candidate.accounting
    if not view.consistent:
        text = "Accounting breakdown unavailable: inconsistent records."
    elif view.unattributed_cost_usd == 0:
        return ""
    else:
        text = f"Unattributed run cost: {_money(view.unattributed_cost_usd)}."
    return f'<p class="sf-run-accounting-note">{escape(text)}</p>'


def case_accounting(candidate: CandidateResult) -> dict[CaseId, str]:
    """Group once per Candidate, retaining only the selected Case's actual owners."""
    view = candidate.accounting
    groups: dict[CaseId, list[AccountingRow]] = {case.case_id: [] for case in candidate.cases}
    for row in view.rows:
        groups[row.case_id].append(row)
    note = (
        "<p>Recorded usage for this case only. Unknown means not reported. "
        "Provider time is summed across attempts, not wall time.</p>"
    )
    return {
        case_id: note
        + (
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
    fields = (
        ("Cost", _money(summary.usage.cost_usd)),
        ("Calls", _number(summary.calls)),
        ("Cache", _cache(summary)),
        ("Input tokens", _number(summary.usage.input_tokens)),
        ("Output tokens", _number(summary.usage.output_tokens)),
        ("Provider time", _time(summary.provider_latency_ms)),
    )
    values = "".join(
        f"<div><dt>{label}</dt><dd>{escape(value)}</dd></div>" for label, value in fields
    )
    return (
        f'<section class="sf-cost-block"><h4>{escape(row.label)}</h4>'
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
    return "Unknown" if value is None else f"${value:,.4f}"


def _time(value: int | None) -> str:
    return "Unknown" if value is None else f"{value / 1000:,.3f}s"

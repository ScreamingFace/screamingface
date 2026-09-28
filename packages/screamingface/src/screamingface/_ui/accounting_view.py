"""Benchmark-neutral completed accounting table; all data is derived from retained records."""

from __future__ import annotations

from decimal import Decimal
from html import escape
from typing import TYPE_CHECKING

from screamingface.accounting import AccountingRow, AccountingSummary, summarize

if TYPE_CHECKING:
    from screamingface.report import CandidateResult

STYLE = """<style>
.sf-accounting{margin-top:12px;border-top:1px solid var(--sf-line);padding-top:12px}
.sf-accounting h4{font-size:13px;font-weight:600;margin:0 0 8px;color:var(--sf-ink)}
.sf-accounting p{font-size:12px;color:var(--sf-ink-2);margin:8px 0}
.sf-accounting__scroll{overflow-x:auto}
.sf-accounting table{width:100%;border-collapse:collapse;font-size:12px;color:var(--sf-ink)}
.sf-accounting th,.sf-accounting td{padding:8px;border-bottom:1px solid var(--sf-line);
  text-align:left;vertical-align:top;background:var(--sf-bg)}
.sf-accounting th{font-weight:500;text-transform:uppercase;font-size:11px;letter-spacing:.08em}
.sf-accounting .sf-accounting__number{text-align:right;white-space:nowrap;
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.sf-accounting td:first-child{min-width:120px;overflow-wrap:anywhere}
.sf-accounting summary{cursor:pointer;padding:8px;color:var(--sf-ink-2)}
.sf-accounting__scroll:focus-visible,.sf-accounting summary:focus-visible{
  outline:2px solid var(--sf-accent);outline-offset:2px}
.sf-accounting details{border:1px solid var(--sf-line);margin-top:8px}
</style>"""


def accounting_html(candidate: CandidateResult) -> str:
    """Render one candidate's disjoint operation totals plus optional Case detail."""
    view = candidate.accounting
    if not view.consistent:
        return (
            '<p class="sf-report__warn">Accounting breakdown unavailable: inconsistent records.</p>'
        )
    groups: dict[tuple[str, str], list[AccountingRow]] = {}
    for row in view.rows:
        groups.setdefault((row.stage, row.operation_id), []).append(row)
    body = "".join(_group_row(rows) for rows in groups.values())
    remainder = _remainder_html(view.unattributed_cost_usd)
    cases = _case_sections(view.rows)
    return (
        '<section class="sf-accounting" aria-label="Operation accounting">'
        "<h4>Operation accounting</h4>"
        "<p>Retained observations only. Unknown means unavailable, not zero. "
        "Provider time sums upstream attempts; it is not wall time. "
        "Cache: hits / misses / bypasses / unknown. Tokens: input / output.</p>"
        f"{_table(body + remainder)}{cases}</section>"
    )


def _table(body: str) -> str:
    headers = ("Operation", "Stage", "Model", "Calls", "Cache", "Tokens", "Cost", "Provider time")
    head = "".join(
        f'<th scope="col" class="{"sf-accounting__number" if index >= 3 else ""}">{name}</th>'
        for index, name in enumerate(headers)
    )
    return (
        '<div class="sf-accounting__scroll" tabindex="0" role="region" '
        'aria-label="Scrollable operation accounting"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )


def _group_row(rows: list[AccountingRow]) -> str:
    summary = summarize([row.accounting for row in rows])
    models = tuple(dict.fromkeys(row.model or "Unknown" for row in rows))
    values = (
        rows[0].label,
        rows[0].stage.capitalize(),
        ", ".join(models),
        _number(summary.calls),
        _cache(summary),
        f"{_number(summary.usage.input_tokens)} / {_number(summary.usage.output_tokens)}",
        _money(summary.usage.cost_usd),
        _time(summary.provider_latency_ms),
    )
    cells = []
    for index, value in enumerate(values):
        title = _cell_title(index)
        css = ' class="sf-accounting__number"' if index >= 3 else ""
        cells.append(f"<td{css}{title}>{escape(value)}</td>")
    return "<tr>" + "".join(cells) + "</tr>"


def _cache(summary: AccountingSummary) -> str:
    cache = summary.cache
    if cache is None:
        return "Unknown"
    return f"{cache.hits} / {cache.misses} / {cache.bypasses} / {cache.unknown}"


def _cell_title(index: int) -> str:
    titles = {4: "Cache: hits / misses / bypasses / unknown", 5: "Input / output tokens"}
    return f' title="{titles[index]}"' if index in titles else ""


def _remainder_html(cost: Decimal | None) -> str:
    return (
        '<tr><td>Unattributed</td><td colspan="5">Cost outside retained priced operations</td>'
        f'<td class="sf-accounting__number">{_money(cost)}</td><td>Unknown</td></tr>'
    )


def _case_sections(rows: tuple[AccountingRow, ...]) -> str:
    cases: dict[int | str, list[AccountingRow]] = {}
    for row in rows:
        cases.setdefault(row.case_id, []).append(row)
    return "".join(_case_html(case_id, records) for case_id, records in cases.items())


def _case_html(case_id: int | str, rows: list[AccountingRow]) -> str:
    body = "".join(_group_row([row]) for row in rows)
    return (
        f"<details><summary>Accounting for Case {escape(str(case_id))}</summary>"
        f"{_table(body)}</details>"
    )


def _number(value: int | None) -> str:
    return "Unknown" if value is None else f"{value:,}"


def _money(value: Decimal | None) -> str:
    return "Unknown" if value is None else f"${value:,.4f}"


def _time(value: int | None) -> str:
    return "Unknown" if value is None else f"{value / 1000:,.3f}s"

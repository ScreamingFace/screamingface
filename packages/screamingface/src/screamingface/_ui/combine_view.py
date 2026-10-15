"""The Combine views of the report (E4b part 4): the Case pane section and the run summary.

INVARIANT: every text from data goes through html.escape; a float shows 4 significant digits and
its exact stored value as the title (ans:Q3); a missing value is an em dash with its reason.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screamingface.combine_evidence import CombineAnswerRow

_DASH = "—"
_TEXT_CELL = 80  # characters of a member value shown in one cell (P7)

# WHY one "<style>…</style>" constant: the house precedent (accounting_view.STYLE, joined into
# report_view._STYLE). WHY text-align on th AND td, and the tbody tr background: JupyterLab's
# rendered-HTML rules right-align table cells and paint zebra rows; the zebra rule has a higher
# specificity, so it needs !important (house precedent: report_browser.py:44). Same intent as
# .sf-eval__table (evaluation_view.py:41,47).
STYLE = """<style>
.sf-cmb{margin-top:6px;overflow-x:auto}
.sf-cmb__t{width:100%;border-collapse:collapse;margin-top:6px;font-size:12px;
  font-variant-numeric:tabular-nums}
.sf-cmb__t th{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;font-weight:600;
  text-align:left;color:var(--sf-ink-2);padding:4px 8px;border-bottom:1px solid var(--sf-line-2)}
.sf-cmb__t td{padding:4px 8px;text-align:left;border-bottom:1px solid var(--sf-line);
  color:var(--sf-ink);overflow-wrap:anywhere}
.sf-cmb__t tbody tr{background:transparent!important}
.sf-cmb__out td{color:var(--sf-ink-3)}
.sf-cmb__na,.sf-cmb__nn{color:var(--sf-ink-3)}
.sf-cmb__na,.sf-cmb__n{cursor:help}
.sf-cmb__h{font-size:13px;font-weight:600;margin-top:10px}
.sf-cmb__nn{font-size:11px}
</style>"""


def number_html(value: float | None, reason: str) -> str:
    """A float at 4 significant digits, the exact stored value as its title; None: a dash."""
    if value is None:
        return dash_html(reason)
    return (
        f"<span class='sf-cmb__n' title='{escape(repr(value))}'>"
        f"{escape(format(value, '.4g'))}</span>"
    )


def dash_html(reason: str) -> str:
    """The missing-value mark: an em dash whose title is the reason (ans:Q3)."""
    return f"<span class='sf-cmb__na' title='{escape(reason)}'>{_DASH}</span>"


def text_html(value: str | None, reason: str) -> str:
    """A member value: escaped, at most 80 characters then an ellipsis; None: a dash."""
    if value is None:
        return dash_html(reason)
    # WHY not report_view._short: report_view imports this module (an import cycle).
    shown = value if len(value) <= _TEXT_CELL else value[:_TEXT_CELL] + "…"
    return escape(shown)


def missing_reason(row: CombineAnswerRow, label: str) -> str:
    """Why a cell of this member row is empty (MR-1..MR-3, P6)."""
    if row.status == "fail":
        return f"member failed: {row.reason}"
    if row.status == "excluded":
        return f"left out by the rule: {row.reason}"
    return f"no {label} recorded"


__all__: list[str] = []

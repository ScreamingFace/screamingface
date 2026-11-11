"""Credit display: account total first, distinct allowances, factual failure labels."""

from __future__ import annotations

from datetime import UTC
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screamingface.credit import CreditAmount, CreditStatus

CREDIT_STYLE = """<style>
.sf-credits{margin:16px 12px 0;padding:16px 20px;border:1px solid var(--sf-line-2);
  background:var(--sf-bg);color:var(--sf-ink)}
.sf-credits__title{display:flex;align-items:center;justify-content:space-between;gap:16px;
  font-size:13px;font-weight:600;margin-bottom:16px}
.sf-credits__currency{font-size:12px;font-weight:400;color:var(--sf-ink-2)}
.sf-credits__grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:24px}
.sf-credits__grid--hosted{grid-template-columns:1fr}
.sf-credits__label{font-size:13px;color:var(--sf-ink-2)}
.sf-credits__value{font:500 18px/1.3 "IBM Plex Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums;margin:8px 0;overflow-wrap:anywhere}
.sf-credits__primary .sf-credits__value{font-size:30px}
.sf-credits__secondary{border-left:1px solid var(--sf-line);padding-left:24px}
.sf-credits__stamp,.sf-credits__note,.sf-credits__help{font-size:12px;color:var(--sf-ink-2);
  line-height:1.5;overflow-wrap:anywhere}
.sf-credits__help{border-top:1px solid var(--sf-line);padding-top:12px;margin-top:16px}
.sf-credits__controls{margin:0 12px 12px;padding:12px 20px;border:1px solid var(--sf-line-2);
  border-top:0;display:flex;gap:8px;flex-wrap:wrap;max-width:100%;box-sizing:border-box}
.sf-credits__controls .widget-text{max-width:100%}
@media(max-width:520px){.sf-credits{padding:16px}.sf-credits__grid{grid-template-columns:1fr;gap:16px}
  .sf-credits__secondary{border-left:0;border-top:1px solid var(--sf-line);padding:16px 0 0}
  .sf-credits__controls{padding:12px 16px}}
</style>"""


def _amount_html(label: str, amount: CreditAmount, *, primary: bool = False) -> str:
    value = "Unavailable"
    if amount.amount_usd is not None:
        value = f"${amount.amount_usd:,.2f}"
    elif amount.status == "unlimited":
        value = "No key limit"
    note = "Refresh failed · last known value" if amount.status == "stale" else ""
    if amount.reason == "management_key_required":
        note = "Add a management key in account settings to see this balance."
    elif amount.reason == "account_unverified":
        note = "Account association could not be verified."
    stamp = ""
    if amount.as_of:
        stamp = "Checked " + amount.as_of.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    css = "sf-credits__primary" if primary else "sf-credits__secondary"
    return (
        f"<div class='{css}'><div class='sf-credits__label'>{escape(label)}</div>"
        f"<div class='sf-credits__value'>{escape(value)}</div>"
        f"<div class='sf-credits__note'>{escape(note)}</div>"
        f"<div class='sf-credits__stamp'>{escape(stamp)}</div></div>"
    )


def credit_html(status: CreditStatus) -> str:
    name = "OpenRouter" if status.provider == "openrouter" else status.provider
    hosted = status.account.reason == "hosted_unavailable"
    if hosted:
        amounts = _amount_html("Hosted allowance", status.hosted, primary=True)
        help_text = "Remaining allowance on your platform key."
    else:
        amounts = _amount_html("Account balance", status.account, primary=True)
        amounts += _amount_html("Key allowance", status.key)
        help_text = "Key allowance is a spending cap, not additional credit."
    grid = "sf-credits__grid sf-credits__grid--hosted" if hosted else "sf-credits__grid"
    return (
        f"{CREDIT_STYLE}<section class='sf-credits' aria-label='Provider credits'>"
        f"<div class='sf-credits__title'><span>{escape(name)} credits</span>"
        "<span class='sf-credits__currency'>USD</span></div>"
        f"<div class='{grid}'>{amounts}</div>"
        f"<div class='sf-credits__help'>{help_text}</div></section>"
    )

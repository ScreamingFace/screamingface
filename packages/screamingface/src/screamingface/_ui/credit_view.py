"""Credit display: account total first, distinct allowances, factual failure labels."""

from __future__ import annotations

from datetime import UTC
from html import escape
from typing import TYPE_CHECKING

from screamingface._ui.style import NO_MATH, STYLE

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


#: FEATURE: OME-1935 — why an amount is unavailable, in short factual words. Shared by the
#: connection panel and the `sf.credits()` card so both always say the same thing.
_REASON_NOTES: dict[str, str] = {
    "not_connected": "Not connected",
    "credential_rejected": "Key rejected",
    "lookup_failed": "Lookup failed",
    "unsupported": "Not supported",
    "invalid_response": "Unreadable response",
    "management_key_required": "Add a management key in account settings to see this balance.",
    "account_unverified": "Account association could not be verified.",
}


def _amount_html(label: str, amount: CreditAmount, *, primary: bool = False) -> str:
    value = "Unavailable"
    if amount.amount_usd is not None:
        value = f"${amount.amount_usd:,.2f}"
    elif amount.status == "unlimited":
        value = "No key limit"
    note = "Refresh failed · last known value" if amount.status == "stale" else ""
    if amount.status == "unavailable":
        note = _REASON_NOTES.get(amount.reason or "", "")
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


def _nothing_known(status: CreditStatus) -> bool:
    """True when no amount is readable and nothing marks the caller as hosted."""

    return (
        status.account.reason != "hosted_unavailable"
        and status.account.status == "unavailable"
        and status.key.status == "unavailable"
    )


def credit_html(status: CreditStatus, *, hosted: bool | None = None) -> str:
    name = "OpenRouter" if status.provider == "openrouter" else status.provider
    title = (
        f"<div class='sf-credits__title'><span>{escape(name)} credits</span>"
        "<span class='sf-credits__currency'>USD</span></div>"
    )
    # WHY: a failed lookup loses the hosted marker, so a caller that does not know its
    # mode (the `sf.credits()` card) shows one neutral box instead of guessing. The panel
    # always passes `hosted`, so it never takes this path (OME-1935).
    if hosted is None and _nothing_known(status):
        reason = status.key if status.key.reason else status.account
        return (
            f"{CREDIT_STYLE}<section class='sf-credits' aria-label='Provider credits'>{title}"
            "<div class='sf-credits__grid sf-credits__grid--hosted'>"
            f"{_amount_html('Credits unavailable', reason, primary=True)}</div></section>"
        )
    # WHY: panels know their mode even when a failed lookup loses the hosted marker.
    if hosted is None:
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
        f"{CREDIT_STYLE}<section class='sf-credits' aria-label='Provider credits'>{title}"
        f"<div class='{grid}'>{amounts}</div>"
        f"<div class='sf-credits__help'>{help_text}</div></section>"
    )


def credit_card_html(status: CreditStatus) -> str:
    """The standalone `sf.credits()` card: the panel's credit section on its own themed root.

    INVARIANT: the root carries `sf-ui` (the `--sf-*` theme tokens, light and dark) and both
    no-maths classes (OME-1226), because every amount contains a `$` that MathJax would
    otherwise typeset.
    """

    return f"{STYLE}<div class='sf-ui {NO_MATH}'>{credit_html(status)}</div>"

---
ticket: OME-1935
stack: screamingface
status: done
started: 2026-11-17
finished: 2026-11-17
---

# credits-repr — give `sf.credits()` a rich notebook repr

## Intent

`sf.credits()`, `Client.credits()` and `AsyncClient.credits()` return a `CreditStatus`
that a notebook shows as a plain dataclass repr. Give it a static card in the same
visual language as the connection panel's credit section (E5 P3, `OME-893`), so a
researcher can read their balance and allowance at a glance. Filed by Irina,
follow-on to E5 P3.

## Decisions (owner, 2026-11-17)

- Static `_repr_html_`, not a live widget. The returned value is a snapshot; calling
  `sf.credits()` again refreshes it.
- When nothing is known (every amount unavailable, no hosted marker), show one neutral
  "Credits unavailable" box with the reason, not the BYOK two-box layout. Any known
  amount keeps the normal layout.
- Reason labels are short and factual ("Not connected", "Key rejected", "Lookup failed",
  "Not supported", "Unreadable response") and are shared with the connection panel.
- No snapshot hint on the card; the "Checked … UTC" stamp dates it.

## Planned changes

- `packages/screamingface/src/screamingface/credit.py`: `CreditStatus._repr_html_`.
- `packages/screamingface/src/screamingface/_ui/credit_view.py`: a standalone card
  renderer with the shared `sf-ui` theme root and the no-maths classes; reason
  labels for `not_connected`, `credential_rejected`, `lookup_failed` and the other
  unavailable reasons; the neutral unavailable layout.
- `packages/screamingface/tests/`: new tests for the standalone card.
- `packages/screamingface/CHANGELOG.md`: Unreleased entry.

## Test plan

- Write failing tests first. Each renders a structured `CreditStatus` and parses the
  HTML (no substring search over output):
  - BYOK: account balance primary, key allowance secondary, spending-cap note.
  - Hosted: exactly one hosted allowance, no account balance.
  - Stale value keeps its amount and its stale note; `unlimited` shows "No key limit".
  - Each unavailable reason shows its own label.
  - A failed lookup renders the single neutral unavailable box.
  - The root carries `sf-ui` and both no-maths classes, so `$` amounts are never typeset.
- Existing connection-panel credit tests stay green and unedited.

## Acceptance

- In a notebook, `sf.credits()` renders the card in light and dark themes.
- Every state named in the ticket (`available`, `stale`, `unavailable`, `unlimited`)
  and the `as_of` time are visible.
- The public surface snapshot is unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `credit.py` (`CreditStatus._repr_html_`),
  `_ui/credit_view.py` (shared reason labels, neutral box for an unknown mode,
  `credit_card_html`), `tests/test_credit_repr.py` (17 tests), `CHANGELOG.md`; plus this
  ledger, the spec, the plan and the mirror.
- **Commits:** the commit carrying this ledger (`Refs: OME-1935`).
- **Gates:** `run_gates.py screamingface` all green: append-only check, ruff check and
  format, pyright, full pytest with coverage ≥95%, the Node refresh test, notebook checks,
  `uv build`, distribution check. No prior test edited.
- **Visual check:** owner approved a static preview of six states in light and dark. Real
  JupyterLab 4: light at desktop width; dark at 390px with the columns stacked and no
  overflow. The root carries `sf-ui mathjax_ignore tex2jax_ignore`.
- **Deviations:** one new test was corrected while still RED-to-GREEN: it put both
  reasons on unavailable amounts, which the agreed rule renders as the neutral box; it now
  pairs each reason with a known key allowance. Saved notebook outputs reopened from disk
  are untrusted, so JupyterLab strips their `<style>`; that is Jupyter's rule for every
  ScreamingFace card, not specific to this one.

# Plan — rich notebook repr for `sf.credits()` (OME-1935)

Spec: `docs/spec/2026-11-17-credits-repr.md`. One SDLC unit, SDK only
(`packages/screamingface`), `sdlc-python` loop.

1. **RED.** Add `packages/screamingface/tests/test_credit_repr.py`. Build each
   `CreditStatus` directly and parse `_repr_html_()` with `html.parser`. Assert on the
   parsed elements (labels, values, classes), never by searching the HTML text:
   BYOK, hosted, stale, unlimited, each unavailable reason, failed lookup, theme and
   no-maths classes on the root.
2. **GREEN, renderer.** In `_ui/credit_view.py`:
   - Add a reason → label map, and use it in `_amount_html` for every unavailable reason.
   - Add the neutral unavailable layout for a failed lookup.
   - Add `credit_card_html(status)`, which wraps `credit_html` in the `sf-ui` root with
     `NO_MATH` and the shared theme style.
   - `credit_html` keeps its signature. The connection panel changes only by gaining
     the shared reason labels; add one panel test pinning a label there.
3. **GREEN, API.** `CreditStatus._repr_html_` returns `credit_card_html(self)`, with a
   local import from `_ui`.
4. **Gates.** Run the SDK gate from `.claude/sdlc.local.md`: lint, format, types,
   pytest with coverage ≥95%, notebook checks, build. The public surface snapshot and
   the existing credit tests must pass unedited.
5. **Visual check.** Render the card in Jupyter, desktop and mobile widths, light and
   dark, for BYOK, hosted and failed lookup. Owner looks before the PR.
6. **Close.** CHANGELOG Unreleased entry, ledger outcome, PR with `Refs: OME-1935`.

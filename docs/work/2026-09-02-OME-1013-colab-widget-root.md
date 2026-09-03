---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-09-02
finished: 2026-09-03
---

# OME-1013 — Refine the Colab diagnostic footer

## Intent

Fix the retained diagnostic toolbar rendering as an invisible root `VBox` in Google Colab, then
reduce it to a transparent recovery footer after the native traceback. Keep local persistence and
inspection explicit without duplicating terminal guidance or implying that saving downloads a file
from a hosted runtime.

## Planned changes

- `packages/screamingface/tests/test_diagnostic_notebook_view.py` — add a regression test for the
  Colab root-container layout contract and update the owner-approved notebook interaction contract.
- `packages/screamingface/tests/test_evaluation_diagnostics.py` — preserve terminal export guidance
  while proving notebook presentation does not duplicate it.
- `packages/screamingface/src/screamingface/_ui/diagnostic_view.py` — make the root visible and
  transparent, present `View details` and `Save JSON`, hide empty rows, and move runtime/%tb guidance
  into the expanded details.
- `packages/screamingface/src/screamingface/_diagnostics/evaluation.py` — attach textual export
  guidance only outside notebooks, where no rich recovery footer is available.
- Approved OME-1013 spec/plan wording and this ledger — record the refined presentation contract.

## Test plan

- RED: prove the root widget does not opt into a frontend-dependent width/layout mode that causes
  Colab to collapse it while its child widgets remain renderable.
- RED: prove the default footer is transparent and concise, calls its actions `View details` and
  `Save JSON`, and does not reserve space for hidden detail/status rows.
- RED: prove details reveal the exact receipt plus runtime-lifetime and `%tb` guidance, saving reports
  a local path, and notebook exceptions omit the duplicate terminal-only export note.
- GREEN: run the focused notebook diagnostic tests, then the full `screamingface` quality gates.
- Preserve the existing tests for native traceback fallback, explicit inspect/save behavior,
  accessibility, privacy, and SFDS styling.

## Acceptance

- Displaying `_display_notebook_diagnostic(sf.diagnostics.last())` produces a visible diagnostic
  toolbar in Colab once its widget manager is enabled.
- The default footer reads `Diagnostic <id>`, `View details`, and `Save JSON` without a contrasting
  card background, visible `local only`/`%tb` copy, or empty vertical rows.
- Details contain the exact receipt JSON, kernel-lifetime disclosure, and `%tb` guidance.
- Terminal exceptions retain exact export guidance; notebooks show it once through the rich footer.
- The public `DiagnosticReceipt.export()` API remains unchanged.
- Existing Jupyter/IPython traceback and notebook diagnostic tests remain green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** updated the approved spec and plan, the diagnostic staging boundary, notebook
  footer adapter, focused notebook tests, and this ledger. The public receipt/export API is
  unchanged.
- **Commits:** this iteration's `fix(screamingface): refine notebook diagnostic footer` commit.
- **Gates:** after rebasing onto current `origin/main`, focused diagnostics plus protocol integration
  91 passed; complete package suite 1,376 passed and 17 skipped at 95.02% coverage; Ruff lint and
  format, Pyright (0 errors), deterministic generated-notebook validation, wheel/sdist build, and
  distribution validation green.
- **Deviations:** the ordinary gate wrapper and generated-notebook check remain blocked by the
  pre-existing user-modified `examples/00_quickstart.ipynb` (`leaderboard` is undefined and the
  generated notebook is stale). The clean generated-notebook check passed while those user-owned
  artifacts were safely stashed; both were restored unchanged and remain excluded from this
  iteration. The owner approved the prior-test wording changes on 2026-09-03; they replace
  the superseded Preview/Export/local-only presentation contract with View details/Save JSON and
  notebook-only rich guidance. Live Colab verification confirmed that removing root shrink-wrap
  makes the widget visible. The rebase conflict retained both `OME-967` trace rendering and
  terminal-only OME-1013 diagnostic notes; the refined copy and transparent styling remain for
  owner visual check from the pushed branch.

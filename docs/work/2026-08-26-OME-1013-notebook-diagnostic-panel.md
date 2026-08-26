---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1013 — Render local diagnostics in notebooks

## Intent

Present a retained local diagnostic receipt as an SFDS notebook panel when an exception escapes a
ScreamingFace Evaluation. Preserve the exact Python exception and keep ordinary terminal behavior,
while giving Jupyter and Colab users explicit Preview and Export actions without a notebook-global
exception handler.

## Planned changes

- Amend the approved OME-1013 spec and plan with the owner-approved per-exception presentation seam.
- Add one private notebook presentation adapter under `packages/screamingface/src/screamingface/_ui/`.
- Attach that adapter only after a diagnostic receipt has been retained.
- Add append-only behavior tests for typed and raw exceptions, fallback behavior, privacy-safe
  preview, explicit export, accessibility, and SFDS light/dark styling.
- Update the ScreamingFace changelog for the notebook presentation behavior.
- Remove unsupported tooltips from root `VBox` containers after a real JupyterLab frontend
  reproduction showed that its widget manager dereferences a nonexistent `description` field.

## Test plan

- RED: an Evaluation failure attaches a renderer to the original exception without replacing it.
- RED: rendering publishes one branded panel with concise error evidence and diagnostic identity.
- RED: Preview reveals the byte-identical receipt JSON only after an explicit click.
- RED: Export writes only after an explicit click and reports success or failure locally.
- RED: missing/broken IPython or ipywidgets falls back to the pre-existing traceback renderer.
- RED: unrelated exceptions and successful/partial Evaluations are unaffected.
- Run the full `screamingface` gate lane after focused tests pass.
- RED: root `VBox` containers do not publish a tooltip trait, while supported control/table
  tooltips and the panel's HTML accessibility name remain intact.

## Acceptance

- Jupyter and Colab render a square, accessible SFDS app-register diagnostic panel for retained
  Evaluation failures.
- The same original exception object is re-raised; `%tb` remains available for its full traceback.
- No global IPython exception handler is installed.
- Preview and Export are explicit local actions; no send or automatic filesystem write exists.
- Plain Python and terminal behavior remain unchanged, and presentation failure is fail-open.

## Outcome

- **Actual files:** amended the approved OME-1013 spec and plan; added the private
  `_ui/diagnostic_view.py` notebook adapter; attached it at the existing Evaluation diagnostic
  boundary; added append-only notebook renderer, action, fallback, accessibility and SFDS tests;
  updated the package changelog; and removed unsupported root-`VBox` tooltips from both diagnostic
  and Evaluation widgets after a live JupyterLab reproduction identified the shared frontend crash.
- **Commits:** `feat(screamingface): render notebook diagnostics`; and
  `fix(screamingface): avoid notebook container tooltip crash` (this follow-up).
- **Gates:** Ruff lint and formatting, Pyright (0 errors), complete package pytest suite (1,237
  passed, 17 skipped, 95.04% coverage), focused widget suites (57 passed), wheel/sdist build and
  distribution validation all passed. The new adapter has 100% focused statement coverage.
- **Deviations:** the official gate wrapper's Ruff phase also inspected an unrelated, owner-edited
  `examples/00_quickstart.ipynb` and stopped on that notebook's pre-existing undefined
  `leaderboard` name. The owner file was preserved and excluded from this commit; the equivalent
  source/test/type/build/distribution gates were run directly. A headless Chrome reproduction
  confirmed the original `VBoxView` creation failure; the owner notebook rerun after a kernel
  restart remains the final visual confirmation of the corrected model.
- **Review:** the renderer is attached only to the retained exception instance, preserves the same
  exception and traceback, never installs a global IPython hook, performs no network or automatic
  filesystem action, and falls back to the previous traceback renderer if optional notebook
  presentation fails. Removing the root tooltip is the minimum compatible fix: supported button
  and table tooltips remain, while accessibility naming stays in the panel HTML and live regions.
  The intake contract, consent and Send action remain isolated to OME-1014.

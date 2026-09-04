---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-09-03
finished: 2026-09-04
---

# OME-1013 — Preserve notebook recovery when widgets fail

## Intent

Keep the privacy-safe local receipt as the default evidence contract while making the notebook
fallback useful when optional widget rendering fails: preserve the native traceback, log the
presentation failure without receipt content, and show the diagnostic id plus explicit export
command exactly once per rendering attempt.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/diagnostic_view.py`
- `packages/screamingface/src/screamingface/_diagnostics/evaluation.py`
- `packages/screamingface/src/screamingface/diagnostic.py`
- `packages/screamingface/tests/test_diagnostic_notebook_view.py`

## Test plan

- RED: a failed widget display retains every native traceback line and adds the diagnostic id and
  exact export command.
- RED: repeated traceback rendering neither retries the broken widget nor duplicates recovery text.
- RED: presentation failure logging contains no receipt JSON.
- GREEN: successful widget rendering remains additive and unchanged.
- QUALITY: run the complete ScreamingFace gate runner.

## Acceptance

- A notebook without working `ipywidgets` still tells the user how to retrieve and export the
  already-retained diagnostic.
- The original exception and traceback remain intact and `%tb` remains useful.
- The fallback logs the presentation failure without logging diagnostic content.
- Full tracebacks remain local and are never added to the diagnostic receipt or report payload.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** shared the private export-guidance formatter from
  `packages/screamingface/src/screamingface/diagnostic.py`; made
  `packages/screamingface/src/screamingface/_ui/diagnostic_view.py` retain the native traceback,
  log a failed widget once without receipt content, avoid retrying it, and append recovery
  guidance; repointed `packages/screamingface/src/screamingface/_diagnostics/evaluation.py`; added
  regression coverage in `packages/screamingface/tests/test_diagnostic_notebook_view.py`; and
  recorded this ledger.
- **Commits:** this iteration's `fix(screamingface): preserve diagnostic fallback recovery`
  commit.
- **Gates:** RED confirmed the missing recovery text and repeated widget attempt; 22 notebook-view
  tests passed; 80 focused diagnostic tests passed; Ruff and Pyright passed; the complete
  `python3 .claude/scripts/run_gates.py screamingface --skip-append-only` suite was green in a
  byte-for-byte-verified clean worktree (Ruff lint/format, Pyright, full pytest with at least 95%
  coverage, notebook validation, build, and distribution validation).
- **Deviations:** the owner-approved behavior necessarily amended one existing fallback test, so
  the append-only check was skipped after it correctly identified that prior assertion change.
  The feature worktree's first complete run then stopped on the user's uncommitted quickstart
  notebook (`leaderboard` was undefined); clean-worktree validation preserved that notebook and
  the exported diagnostic JSON untouched. Full exception tracebacks remain local by design:
  authenticated internal reporting does not make absolute paths, source lines, exception
  messages, prompts, or secrets safe to upload by default.

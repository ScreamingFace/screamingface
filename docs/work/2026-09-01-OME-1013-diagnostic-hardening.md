---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-09-01
finished: 2026-09-01
---

# OME-1013 — Harden diagnostic evidence and notebook presentation

## Intent

Correct the review findings without redesigning the diagnostic feature: preserve IPython's native
traceback while adding the local receipt toolbar, stop publishing the private stream topic as a
public run id, simplify receipt construction and recipe projection around typed allow-listed
evidence, and use the SFDS danger role for failures.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/diagnostic_view.py`
- `packages/screamingface/src/screamingface/_diagnostics/evaluation.py`
- `packages/screamingface/src/screamingface/_diagnostics/model.py`
- focused diagnostic tests under `packages/screamingface/tests/`
- OME-1013 spec, plan, task/ledger bookkeeping when required by the corrected contract

## Test plan

- RED: an attached notebook renderer returns the native traceback lines on first and repeated
  rendering while displaying the receipt toolbar only once; adapter failure retains the prior
  renderer's lines.
- RED: event stream topics never enter a receipt as public `run_id`, while observable `trace_id`
  remains attached to the correct execution.
- RED: recipe evidence remains sufficient for preflight failures without a diagnostic switch over
  every concrete recipe subtype.
- RED: receipt construction rejects non-allow-listed top-level sections and unsafe error fields.
- RED: failure presentation uses the semantic SFDS danger token.
- Run focused tests, the full package suite, and `run_gates.py screamingface`.

## Acceptance

- Native exception rendering and `%tb` remain intact; the widget is additive and local.
- The internal stream topic is absent from the public receipt schema.
- Safe structured error, validated configuration, topology and report/export capabilities remain;
  prompts, responses, raw messages and other forbidden content remain absent.
- Diagnostic capture does not require edits for each new concrete recipe subtype.
- All ScreamingFace gates pass at or above 95% coverage.

## Outcome

- **Actual files:** corrected the spec/plan and original capture ledger; added this hardening ledger;
  updated the diagnostic receipt/evaluation/notebook modules and their focused behavior suites; and
  clarified that the two earlier `done` ledgers describe completed iterations, not ticket closure.
- **Commits:** this iteration's `fix(screamingface): harden client diagnostics` commit.
- **Gates:** `run_gates.py screamingface --skip-append-only` ALL GATES GREEN — Ruff lint and
  formatting, Pyright (0 errors), the complete pytest suite with ≥95% coverage, deterministic
  notebook validation, wheel/sdist build, and distribution validation. Focused diagnostic,
  capture and fail-open suites: 62 passed.
- **Deviations:** append-only comparison skipped only for the owner-approved contract corrections
  listed below. The pre-existing modified quickstart notebook and untracked exported diagnostic
  were temporarily stashed for gates because that notebook currently has an unrelated undefined
  `leaderboard` reference; both user-owned files were restored unchanged immediately afterward.

## Owner-approved prior-test amendments

The append-only guard stopped on three tests that encoded the review findings the owner explicitly
approved fixing on 2026-09-01:

- `test_diagnostic_notebook_view.py` now requires native traceback lines on successful and repeated
  rendering instead of requiring `[]`, and requires the semantic danger token.
- `test_evaluation_diagnostics.py` removes the internal stream topic from expected public receipt
  evidence and limits pre-compilation candidate evidence to name/kind.
- `test_diagnostics.py` constructs the typed receipt evidence aggregate and replaces the unsafe
  arbitrary `error.message` fixture with an allow-listed hint; a new test rejects `message`.

The assertions are stronger and directly cover the corrected privacy and exception-preservation
invariants. The final gate run may use `--skip-append-only` for only these approved amendments.

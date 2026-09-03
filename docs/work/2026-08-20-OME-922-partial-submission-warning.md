---
ticket: OME-922
stack: screamingface
status: in_progress
started: 2026-08-20
finished:
---

# OME-922 — Warn that partial-submission scores are not directly comparable

## Intent

Prevent a user from mistaking a limited or incompletely graded benchmark submission for a
score directly comparable with a full run. The Client warns at the submission seam but
preserves the existing advisory-only behavior and sends valid partial scores unchanged.

## Planned changes

- `packages/screamingface/tests/test_leaderboards.py` — append sync/async warning coverage.
- `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` — emit the warning
  from the shared submission builder.
- Add the required task, spec, plan, and work records for `OME-922`.

## Test plan

- RED: limited run warns while still POSTing.
- RED: full-sized but incompletely graded run warns while still POSTing.
- Boundary: a complete full run emits no warning.
- Parity: asynchronous submission behaves identically.
- Regression: payload and existing validation remain unchanged.

## Acceptance

- Both limited and incompletely graded valid submissions show the exact ticket warning.
- Full submissions remain silent.
- Warnings never block the POST or change its payload.
- All `screamingface` gates pass.

## Outcome

- **Actual files:** task/spec/plan/work records and the SDK README; the Scoreboard adapter plus
  focused submission-notice policy; shared environment and notice values; standalone notebook
  notice presentation; Candidate Result serialization; and focused notice, public-workflow,
  Report, and environment tests. The abandoned score-field/card CSS/global-palette approach is
  removed from the final diff.
- **Commits:** the original implementation/policy/presentation series through `44f3d31e`, plus
  `c6f3b9a2 fix(screamingface): make partial notices follow documented workflows`.
- **Gates:** every reviewer reproduction first failed at its public seam, then passed. The final
  public-workflow module has 14 tests. A clean temporary merge with current `origin/main`
  collected 1,006 tests and passed the complete official stack: Ruff check/format, Pyright,
  1,005 pytest passes with one skip and the 95% coverage floor, deterministic notebook check,
  build, and distribution verification.
- **Deviations:** a fresh worktree needs the declared `uv sync --extra notebook` before Pyright
  can resolve IPython/ipywidgets. The integrated append-only check was skipped because current
  main's already-landed PR #607 changes `test_runtime_cli.py` relative to this older PR head; the
  final OME-922 diff restores `test_leaderboards.py` exactly to main, adds one focused test file,
  and only appends tests elsewhere. Four locally executed notebooks remain user-owned unstaged
  changes and were not regenerated, staged, or overwritten.

## Brand presentation follow-up

The first implementation correctly warned but Jupyter rendered the `UserWarning` as a
large red, path-heavy block above a successful green receipt. Reopen this task to move the
advisory into the notebook score card, while retaining a Python warning in headless code.
Use the canonical persimmon warning tokens and square status treatment from
`OpenMined/screamingface-brand` commit `7ea35a1`. The four locally executed example
notebooks are user-owned working-tree changes and must remain untouched.

### Follow-up outcome

- Notebook submissions now carry a `Partial submission` status notice inside the published
  score card and do not emit a duplicate Python warning; headless sync and async callers
  retain the warning.
- The notice uses the canonical persimmon light/dark tokens, solid status square, square
  edges, and no decorative effects from brand commit `7ea35a1`.
- RED was confirmed by two missing notebook-carrier failures. The complete leaderboard
  module passes 52 tests.
- The official gate suite is fully green from a clean worktree: append-only, Ruff check and
  format, Pyright, full pytest with the 95% coverage floor, notebook check, build, and
  distribution check. The first clean-worktree attempt required the repository's declared
  `notebook` extra before Pyright could resolve IPython and ipywidgets.

## Policy correction follow-up

Review established that the Scoreboard does not currently exclude partial submissions from
ranking. The notice now states the behavior that exists: a partial score may appear on the
public leaderboard, but because it is based on fewer benchmark Cases it is not directly
comparable with a full-run score. Full-coverage-only ranking remains separate Scoreboard policy
scope.

## Review correction follow-up

Review found that the headless warning skips past the user's submission frame. Review also
surfaced an ambiguity between the Report-rendering non-goal and the intentional shared
persimmon warning-token migration; the owner confirmed that every warning surface should use
the brand-accurate palette.

### Planned changes

- Append a regression proving a headless warning is attributed to the caller.
- Correct the warning stack level without changing submission or response behavior.
- Clarify that the shared Report warning-palette correction is intentional and preserve it.
- Correct semantic comment anchors and bring this ledger's outcome up to date.

### Test plan

- RED: the warning-origin regression observes the current synthetic `<sys>` location.
- GREEN: the same regression points to the caller after the stack-level correction.
- Regression: submission payload, notebook carrier, shared Report tokens, sync/async behavior,
  and all existing tests remain correct.
- Run the complete official `screamingface` gate suite from a clean worktree.

### Review correction outcome

- The documented `sf.leaderboards.submit()` facade now skips every SDK frame rather than relying
  on one fixed `stacklevel`; three submissions on three user lines produce three independently
  attributed `sf.EvaluationWarning` values with exact copy.
- Headless advisories run before the POST, so warnings-as-errors cannot persist a score and then
  hide its id. Sync and async behavior are covered independently.
- Notebook submissions explicitly publish one branded display event after success, including
  assignment, lists, papermill, and nbconvert. The returned score remains unchanged, final
  expressions do not repeat the notice, failed POSTs display nothing, and a broken display
  publisher falls back to stderr without hiding an already persisted id.
- Exported Candidate Results retain the full Benchmark Case count while the Report root retains
  the selected count, so the documented saved-result loader still identifies a limited run.
- Colab and Databricks shells are recognised through their ipykernel base class.
- Persimmon is scoped to the new submission notice; existing Report warnings keep their distinct
  amber palette. Severity is visible in the class/data contract and warning notices use
  `role="alert"`.
- The weak test block was replaced by a focused public-workflow module. Exact strings are compared
  literally, notice existence is asserted from captured display output, palette tests are
  independent of behavior tests, and warning filters are scoped to `sf.EvaluationWarning`.
- The task mirror and ledger remain `in_progress` together until review and merge.

## Second review pass (2026-08-21) — planned

Filip's `CHANGES_REQUESTED` items are all resolved by the work above. A follow-up read of the
merged branch found four residual defects and one piece of diff noise. Same ticket, same branch,
same unit.

### Owner decisions taken during this pass

- **`report.v1` is replaced in place** — the candidate block's `case_count` changes meaning; the
  schema version is NOT bumped and no consumer reads the old shape.
- **No legacy code anywhere.** No dual-shape loaders and no back-compat branches. Clarified by the
  owner mid-pass: this means *legacy* fallbacks only. Defensive error handling stays — the
  `try/except` around notebook display was removed on a first reading of the instruction and then
  restored, together with its test, once the owner clarified the scope.

### Planned changes

- `_scoreboard/submission_notice.py` — two changes: emit the warning in the notebook branch too
  (inside `warnings.catch_warnings(record=True)`, so `-W error` aborts before the POST and
  `-W ignore` genuinely suppresses); replace the rounded `coverage < 1.0` test with an exact
  ungraded-Case count. The display `try/except` is unchanged from the first pass.
- `_notices.py` — the advisory no longer asserts publication, because it is emitted before the POST.
- `_scoreboard/leaderboards.py` — revert a behaviour-neutral `score = _score_value(...)` hoist.
- `report.py` — comment only: name both sides of the root/candidate `case_count` split.
- `tests/test_partial_submission_notice.py`, `tests/test_notices.py` — see below.

### Test plan

- RED: notebook + `error` filter raises `sf.EvaluationWarning` with **zero** POSTs; notebook +
  `ignore` posts and displays nothing; notebook + `default` displays exactly one notice; a
  candidate whose `coverage` rounds to `1.0` but holds one ungraded Case is still partial.
- GREEN: the above pass and every prior test still passes.
- Mutation check: force `prepare_submission_notice` to return `None` and confirm the notebook and
  headless tests fail.

### Prior-test changes — rule 5 exception, owner-approved

This pass **modifies and deletes** existing assertions, so `run_gates.py` runs with
`--skip-append-only`. Both changes are forced by the behaviour change, not fitted to it:

- `_run_notebook_cell` sets `simplefilter("error", ...)`; under the new uniform policy that now
  aborts, so the helper takes the filter as a parameter. This is the only prior-test change that
  survives the pass.

### Deliberately out of scope

- **Colab dark theme** — `notice_view.py` reaches its dark palette only through
  `prefers-color-scheme` and the JupyterLab/VS Code hooks; Colab sets none of them and its theme is
  independent of the OS preference, so a dark-theme Colab user on a light OS may get the light box.
  **Resolved: the owner confirmed it renders correctly in a real Colab session (2026-08-21).**
- `_STYLE` re-emitted per notice (~1.5 KB into every saved output cell), and the two parallel
  warning presentation systems (`sf-report__warn` amber vs `sf-notice` persimmon, each with its own
  theme-detection CSS) → follow-up tickets. Keeping them separate is what kept the review's #6 fixed.

### Second review pass — outcome

- **Actual files:** as planned — `_scoreboard/submission_notice.py` (rewritten),
  `_scoreboard/leaderboards.py`, `_notices.py`, `report.py` (comment only),
  `tests/test_partial_submission_notice.py`. `tests/test_notices.py` needed **no** change: its
  message test builds its own `ClientNotice` and its palette test asserts only colours, so
  neither was coupled to the advisory copy.
- **Gates:** ruff check ✓ · ruff format ✓ · pyright ✓ · pytest --cov (95% floor) ✓ ·
  check_notebooks ✓ · uv build ✓ · check_distribution ✓ — **ALL GREEN**, with
  `--skip-append-only` for the rule 5 exception recorded above.
- **Full suite:** 989 passed, 1 skipped.
- **Mutation-verified.** Forcing `prepare_submission_notice` to return `None` fails **13 of 17**
  tests in the module. The 4 survivors are all legitimately no-op assertions — full submission
  headless, full submission in a notebook, failed POST displays nothing, and the `ignore` filter
  suppressing the notice. Contrast the pre-review state, where a survivor was a test named for
  proving the notice exists.
- **Gate ran on a pristine tree.** In the working worktree `check_notebooks.py` reports
  `00_quickstart.ipynb` and `06_draco.ipynb` stale. That is the owner's four locally executed
  notebooks, whose stored **outputs** carry the old advisory text; the authored cells and the
  deterministic builder contain none of this copy. Verified by running the checker at pristine
  `HEAD` (exit 0) and then re-running the complete suite on a detached worktree carrying only
  this pass's five source files. The notebooks were not regenerated, staged, or modified.

### Deviations from the plan

1. **`_run_notebook_cell`'s new parameter needed a `Literal` type, not `str`.** pyright rejected
   `str` against `warnings.simplefilter`'s `_ActionKind`. Typed as
   `Literal["default", "error", "ignore"]`; caught by the gate, not by the test run.
2. **`tests/test_notices.py` was left untouched** — the plan expected a copy update there, but
   neither of its tests was coupled to `PARTIAL_SUBMISSION_NOTICE.body`.
3. **A `_warn()` helper was extracted.** The warning is now emitted from two places (headless, and
   inside the recording context), so the call and its `skip_file_prefixes` rationale live once.

### Owner-verify — closed

- **Colab dark theme: confirmed good by the owner in a real Colab session (2026-08-21).** This was
  the one item this pass could not verify locally, since Colab sets neither the JupyterLab nor the
  VS Code theme hooks and its theme is independent of the OS preference. No code change needed.

### Correction (2026-08-21, later)

The owner's "no fallback code" instruction was applied too broadly on first reading: the defensive
`try/except` in `display_submission_notice` was removed along with the legacy back-compat
fallbacks. The owner clarified that only *legacy* fallbacks were in scope. The `try/except` and
`test_notebook_display_failure_cannot_hide_an_already_saved_score` are both restored, so the
invariant it protects holds again — a display failure after a successful POST degrades to stderr
and still returns the persisted score id. The `report.v1` in-place replacement stands: a
dual-shape loader would have been a genuine legacy fallback.

### Report styles — verified untouched

Filip's item 6 (the global persimmon migration crushing the warning/error hue gap) and the
duplicated `.sf-report__warn` rules were both fixed by withdrawing them from the diff, before this
pass. Re-verified against `origin/main` at the end of this pass: `_ui/style.py` and
`_ui/report_view.py` are byte-identical to main, neither appears in the PR, and the Report's amber
`--sf-warning-solid:#efbd41` is intact in both light and dark. The new notice ships its own
`--sf-notice-*` tokens scoped to its own element, so nothing overrides Report surfaces.

The residual is duplication, not override: two warning presentation systems now carry their own
theme-detection CSS. That is what keeps item 6 fixed, and it is the follow-up noted above.

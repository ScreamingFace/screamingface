---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-09
finished: 2026-10-09
---

# OME-1527-pr1-importer-refuses-task-metrics — point the importer's non-mean refusal at the right ticket and pin it

Work order #1 of OME-1527 (R2). PR 1 of 20.

## Intent

The ticket's R2 said a Task's own `metrics=[...]` only got a review TODO, so an imported
Benchmark would publish the plain mean silently. Building the refusal showed that this is not
true at the pinned inspect (0.3.263): when inspect builds the Task it replaces each scorer's
whole-run metric list with the Task's `metrics=[...]` (`resolve_scorer_metrics`; per-Case
marking is untouched), so the importer's existing scorer-level
headline check (OME-1268, 0ba6587f1) already sees Task-level metrics and refuses a non-mean
headline. What was left: the check's message pointed at "declare a reducer (OME-1268)", which
never existed, and a Task-level extra metric after a plain-mean headline (worldsense's
`ws_accuracy`) got both a "not reproduced" note and a review TODO asking for the same thing.

Owner decision 2026-10-09 (minimal, after two stops): no new refusal and no flag. Fix the
pointer, drop the duplicate TODO, and pin today's behaviour with the published Benchmarks' own
declarations.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`: the refusal message
  says Task-level metrics reach the check and that whole-run metrics other than the mean are
  coming with OME-1527 (R1); the row renderer skips a Task-level metric's TODO when that metric
  already has its "not reproduced" note.
- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_metrics.py`: the module
  docstring's same dead "until the row declares a reducer" pointer.
- `apps/screamingface-engine/tests/unit/inspect/test_importer_refuses_task_metrics.py` (new).
- `docs/tasks/2026-10-08-OME-1527-hand-built-benchmarks-to-local-tasks.md` (new mirror).

## Test plan

- xstest (`refusal_rate`), coconot (`compliance_rate`) and bbeh (`grouped` +
  `harmonic_mean_across_tasks`), built from the pinned inspect_evals' own metric functions with
  a source-text check, are refused through the import child's fact reader; one stand-in eval
  proves the same through the real child process.
- The refusal names OME-1527 (R1) and Task-level metrics, never OME-1268 or a reducer.
- race_h, mgsm_en and squad (plain mean + clustered stderr) import with nothing dropped.
- worldsense imports with one "not reproduced" note per extra metric, no duplicate TODO, and
  keeps the stderr TODO (not duplicated anywhere).

## Acceptance

- The refusal message points at a ticket that will deliver what it promises.
- No row says the same deviation twice.
- No published row or revision changes.
- Free inspect unit lane green; extra-less pyright clean on touched files.

## Outcome

- **Actual files:** as planned, plus this ledger.
- **Commits:** one commit on branch `OME-1527-pr1-importer-refuses-task-metrics`,
  `fix(screamingface-engine): point the importer's non-mean refusal at the right ticket and pin it`.
- **Gates:** the new file 11 passed (on main source 9 passed, 2 failed: the pointer and the
  duplicate TODO, as intended); the whole inspect lane `uv run --extra inspect pytest -n auto
  tests/unit/inspect` 1315 passed; ruff check + format clean; pyright in an extra-less env on
  the touched files 0 errors.
- **Deviations:**
  - The briefed refusal was not built. The ticket's premise does not hold at inspect 0.3.263:
    the existing headline check already refuses a non-mean Task-level headline. An option-C
    flag was built and then removed, because it ran after the import child had already
    refused. The owner chose the minimal fix.
  - xstest_safe, xstest_unsafe, coconot_original, coconot_contrast and bbeh have not been
    re-importable since 0ba6587f1 (2026-10-07); they were imported before the headline check
    landed. None of their published rows or revisions change here. worldsense still imports.
  - Constraint carried to OME-1527 PR #2 (R1): give those five a per-row choice, honour the
    eval's metric or keep the mean under a Named Deviation, with the mean kept for the
    published rows so their revisions do not move.
- **Owner-verify:** nothing to press; no paid run, no deploy.

---
ticket: OME-1856
stack: screamingface-engine
status: done
started: 2026-11-09
finished: 2026-11-09
---

# attempts-mean-fold — fold Attempts by their mean when the Task declares inspect's pass@1

## Intent

OME-1458 gave a Benchmark N Attempts per Case with one fold: a Check is met if any Attempt met
it. Its D2 parked "mean over Attempts" until a Benchmark needed it. ZeroBench needs it: inspect_evals
asks each question five times and reports pass@1 as the mean of the five marks (inspect's
`pass_at(1)` over 5 epochs is c/5); the live board scores its current rows the same way, while
the paper's Table 2 and the release-era rows are one greedy sample. Today the importer refuses that Task by name, so the
Benchmark was imported at k=1 (OME-1855), a single-sample number the card has to explain. This
unit lets the Engine and its importer accept inspect's `pass_at(1)` as a second fold rule, the
mean over Attempts, so a later import of ZeroBench runs exactly as inspect_evals does. Spec:
`docs/spec/2026-11-09-attempts-mean-fold.md` (an amendment to OME-1458's D2 and D4).

## Planned changes

- `docs/spec/2026-11-09-attempts-mean-fold.md` — the amendment; one line on OME-1458's D2 row.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/attempt_fold.py`
  — `fold_case_attempts(results, fold=)` with the `mean` rule beside `any`.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/benchmark_aggregation.py`
  — `attempt_fold` field, passed to the fold.
- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_metrics.py` —
  `MEAN_OVER_ATTEMPTS_REDUCER` (`pass_at_1`) and `attempts_reducers()`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py` — `task_attempts`
  returns `TaskAttempts` (attempts, epoch_reducer, dropped_reducers); the pass@1 acceptance.
- `apps/screamingface-engine/src/screamingface_engine_inspect/import_replay.py` — the new facts.
- `apps/screamingface-engine/src/screamingface_engine_inspect/task_replay_rows.py` — the mean
  row's comment, the dropped reducers, the "mean over N Attempts" wording TODO.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py` — validation admits
  `pass_at_1`, the reducer factory builds it, assembly passes the fold rule.
- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py` — `attempt_fold`
  threaded into the aggregation.
- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py` — docstrings only.
- `apps/screamingface-engine/docs/adding-an-imported-benchmark.md` — the epochs paragraph.
- Tests: `tests/unit/inspect/test_importer_refuses_epochs.py` (prior-test change, approved),
  `tests/unit/inspect/test_whole_run_metric.py` (one parametrize row, approved),
  `tests/unit/inspect/test_attempts_mean_fold.py` (new), appended tests in
  `tests/unit/test_attempt_fold.py` and `tests/unit/inspect/test_imported_attempts.py`.
- `.claude/test-change-approvals/OME-1856.json`, `docs/tasks/2026-11-09-OME-1856-attempts-mean-fold.md`.

## Test plan

- Importer: `Epochs(5, ["pass_at_1", "pass_at_5", "5_of_5_reliability"])` imports as
  `attempts=5, epoch_reducer="pass_at_1"` with the two other names recorded as dropped;
  `Epochs(5, ["pass_at_1"])` imports; `Epochs(5, "mean")` and `Epochs(5, ["pass_at_1", "mean"])`
  still refused naming `mean`; `Epochs(2, ["max", "pass_at_1"])` refused naming `pass_at_1`
  (two headlines); a custom reducer borrowing the `pass_at` name at k=1 refused; `Epochs(2, "max")`
  unchanged.
- Fold: one Check, 5 Attempts, c right → c/5 for c = 0, 2, 5; a partial-credit Attempt counts
  as not fully right (inspect's rule); a failed Attempt leaves the mean over the graded rest;
  `met_by_attempts` recorded; the `any` rule byte-identical (prior tests untouched).
- Engine + tally: a row with `attempts=5, epoch_reducer="pass_at_1"` and a whole-run metric
  assembles with inspect's `pass_at(1)`, and the tally's agreement check holds on 0/1 marks and
  on partial-credit marks; `pass_at_1` on a row with no whole-run metric is admitted (the fold
  reads it); `max` on such a row stays refused.
- Rows: the generated row carries `attempts=5`, `epoch_reducer="pass_at_1"`, the mean comment and
  the dropped names; its revision differs from the any-of-5 row's; a one-Attempt row is unchanged.

## Acceptance

- The importer's acceptance rule is the one in the spec, and every refusal listed there still
  fires by name.
- The Engine's Case score under the mean rule equals inspect's `pass_at(1)` over the same
  Attempt Scores, pinned by the tally agreement test on 0/1 and partial marks.
- No row without Attempts and no any-of-N row changes: `test_published_revisions.py` and the
  existing fold tests untouched and green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus a shared `_aligned_checks` helper in `attempt_fold.py` (the two fold rules align Checks the same way) and `_refuse_unfoldable_reducers` / `_attempts_lines` helpers split out for ruff's complexity caps. `test_imported_attempts.py` was not appended: the row tests live in the new `test_attempts_mean_fold.py`. The SDK is untouched (the catalogue entry carries no fold rule, so its "any of N Attempts" phrase cannot be conditional yet; a known limitation on the ticket).
- **Commits:** 9881795cf feat(screamingface-engine): fold Attempts by their mean when the Task declares inspect's pass@1 · (this commit) the records: ledger, mirror, test-change approval.
- **Gates:** with the inspect extra, `tests/unit/test_attempt_fold.py tests/unit/inspect/test_attempts_mean_fold.py tests/unit/inspect/test_importer_refuses_epochs.py tests/unit/inspect/test_whole_run_metric.py tests/unit/inspect/test_imported_attempts.py tests/unit/inspect/test_task_replay_rows.py tests/unit/inspect/test_importer_whole_run_choice.py tests/unit/inspect/test_local_task_arc_agi_2.py` 178 passed; the whole `tests/unit/inspect/` lane 2954 passed; extra-less `test_attempt_fold.py` + the inspect files (skipped) + `test_span_export_wiring.py` + `test_cli.py` 43 passed, 3 skipped; ruff check, ruff format and pyright clean on the 13 touched Python files. Mutant check: a plain average in the fold fails `test_a_partial_attempt_counts_as_not_right_for_the_fold_and_the_reducer_alike` by the tally's own agreement error (reduce 0.4, fold 0.6). Pre-push `run_gates.py screamingface-engine` at push.
- **Deviations:** (1) the mean counts full marks only (inspect's `pass_at(1, value=1.0)`), not a plain average of Attempt scores: a plain average disagrees with inspect on partial marks and the dispatch asked for agreement on partial marks, so inspect's rule wins (spec D15). (2) The worktree folder keeps the slug `attempts-mean-fold` while the branch is `OME-1856-attempts-mean-fold`: moving the worktree breaks its venv mid-run. (3) No SDK wording change: it needs a wire field the catalogue does not carry; recorded as a known limitation rather than a one-line edit that would guess.
- **Owner-verify:** review the draft PR; the five-sample ZeroBench import is a later unit under OME-1299.
- **Addendum (2026-11-09, from the ZeroBench re-import):** a mean row with no whole-run metric
  pinned no reducer, so its revision could keep still while its number changed. `_attempts_pins`
  now pins `epoch_reducer` when the row honours no metric; beside a metric it stays in
  `_whole_run_metric_pins`, so ARC-AGI-2's revision does not move. Pinned by
  `test_the_mean_rule_rides_the_attempts_pins_on_a_row_with_no_whole_run_metric`.

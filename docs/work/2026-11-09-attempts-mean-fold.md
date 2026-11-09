---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress
started: 2026-11-09
finished:
---

# attempts-mean-fold — fold Attempts by their mean when the Task declares inspect's pass@1

## Intent

OME-1458 gave a Benchmark N Attempts per Case with one fold: a Check is met if any Attempt met
it. Its D2 parked "mean over Attempts" until a Benchmark needed it. ZeroBench needs it: inspect_evals
asks each question five times and publishes pass@1 as the mean of the five marks (inspect's
`pass_at(1)` over 5 epochs is c/5). Today the importer refuses that Task by name, so the
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
- `.claude/test-change-approvals/OME-N.json`, `docs/tasks/2026-11-09-OME-N-attempts-mean-fold.md`.

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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

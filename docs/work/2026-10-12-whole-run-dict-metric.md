---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-12
finished: 2026-10-12
---

# whole-run-dict-metric — publish a whole-run metric's extra numbers beside its headline

## Intent

OME-1527, owner decision 2026-10-12, stacked on the contracteval local-Task swap (#1355). That
swap dropped contracteval's precision, recall, F2, the four confusion counts, the decline and
false-decline ("laziness") rates and the Jaccard mean over clause rows, because the tally
refused a whole-run metric returning a dict. Those numbers only exist for the whole run (no
Case has a precision), so they belong in the run's `metrics`, never as Named Scores (per-Case
columns). This unit lets a row name which key of its metric's dict is the Headline Score; the
other keys join the run's `metrics`, under the hand-built Benchmark's key names.

## Planned changes

- `benchmarks.py`: `BenchmarkSpec.whole_run_headline: str | None = None`; assembly refuses it
  without `whole_run_metric` (or blank); pinned into the revision only when set.
- `single_shot.py`: `ImportedBenchmark.whole_run_headline`, threaded into `_whole_run_tally`;
  Stage 3 splits a dict into the headline and run metrics, refusing a dict with no declared key,
  a missing key, a non-finite or non-number extra, a key the tally already publishes, and a
  number on a row that declares a key.
- `importer.py` / `task_replay_rows.py`: `--whole-run-headline KEY`, refused without
  `--whole-run-metric honour`; written on the row beside the metric reference.
- `local_tasks/contracteval/contracteval.py`: the metric returns the hand-built keys; the row
  names `f1` as its headline. README numbers section; notebook 13's "Reading the metrics" cell
  restored.

## Test plan

- Tally: a dict with a declared key publishes the headline and the rest as run metrics (P != R
  worked example); seven refusals by the metric's name; float metrics unchanged (existing tests).
- Assembly: the key without a metric refused; the key is Benchmark identity.
- Importer: the flag lands on the row; the key without honour refused before any replay.
- contracteval: every restored number equals the hand-built `_confusion_matrix_score` value on
  the same eight canned replies (and the all-declined run), pinned as literals.

## Acceptance

- Only rows that declare a headline key change; contracteval's revision moves once vs #1355.
- contracteval's Report carries the hand-built Benchmark's metric keys again, with its values.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `test_published_revisions.py` (contracteval literal
  `04cde6eac3938ddf` → `890889e5b2863be4`) and the approvals manifest (branch renamed, two
  approved blobs updated, inherited entries kept).
- **Commits:** feat(screamingface-engine): publish a whole-run metric's extra numbers beside
  its headline
- **Gates:** relevant files only: 162 passed (`test_whole_run_metric.py`,
  `test_local_task_contracteval.py`, `test_published_revisions.py`, `test_importer_command.py`,
  `test_import_replay.py`, `test_benchmark_declaration.py`, `test_importer_whole_run_choice.py`);
  SDK `test_example_notebooks.py` 13 passed and `check_notebooks.py` clean; ruff check + format
  clean; pyright 0 errors on touched files, extra-less and with the inspect extra. Manual
  append-only check: only the 9 contracteval deletions inherited from #1355. Full gate runs in
  the pre-push hook + CI.
- **Deviations:** the metric leaves out the hand-built `scored_cases` key, because the tally
  publishes it itself (same value) and a shared key is refused rather than overwritten. The
  run also carries the tally's `correct`, which the hand-built Benchmark did not publish.
- **Owner-verify:** the paid contracteval run shows the restored numbers (precision, recall,
  F2, the four counts, laziness, Jaccard mean) beside the paper's.

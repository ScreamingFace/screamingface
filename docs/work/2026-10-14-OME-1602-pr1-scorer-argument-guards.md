---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-15
---

# OME-1602-pr1-scorer-argument-guards: the importer refuses scorer arguments and extra-scorer metrics it can't copy faithfully

## Intent

The importer copies an inspect_evals eval into an Imported Benchmark. A probe of every remaining
single-turn text package (OME-1602) found shapes the importer accepts and then grades wrongly.
This unit is the first of three guard PRs (PR 1 of 7) and covers the two that live in how the
row copies the eval's scorers. It adds no Benchmark and changes no existing row.

- F1: inspect logs a function argument as its name and an object as a dict, and the row wrote
  that logged value back as if it were the real one. drop's `f1(answer_fn=extract_answer)`
  became the string `"extract_answer"` and crashed on Case 1. A non-literal value was also
  silently left out of the row.
- F5: only the headline scorer's whole-run metric was checked, so an extra scorer with its own
  formula (stereoset's `stereotype_score`) was published as a mean under its Named Score column.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/import_replay.py`: the import
  child records each scorer's real arguments while the Task is built.
- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`: `_resolve_scorer`
  refuses an argument whose real value isn't what inspect logged; `_check_kept_scorers` refuses
  an extra scorer whose whole-run metric is not a mean.
- `apps/screamingface-engine/tests/unit/inspect/test_importer_named_scores.py`: one test per
  shape, plus the faithful cases that must still import.
- `docs/tasks/2026-10-14-OME-1602-remaining-single-turn-imports.md`: the ticket mirror rides
  this PR.

## Test plan

- A function argument and an object argument are refused, naming the argument.
- A tuple argument still imports (it equals the list inspect logs).
- The import child installs the argument recorder.
- An extra scorer with its own whole-run metric is refused, naming scorer and metric.

## Acceptance

- drop is refused at import (F1), stereoset is refused at import (F5).
- No existing Task-replay row starts refusing, and every row's facts are unchanged.
- The named test files, ruff, and pyright (with and without the inspect extra) are green.

## Outcome

- **Actual files:** as planned (`import_replay.py`, `importer.py`, `test_importer_named_scores.py`,
  the mirror, this ledger).
- **Commits:** `13d404b0c` refuse scorer arguments inspect logs by name; `376851589` refuse an
  extra scorer with its own whole-run metric; plus the docs commit.
- **Gates:** `test_importer_named_scores.py`, `test_import_replay.py`, `test_task_replay_rows.py`:
  96 passed. ruff check and format, pyright, and extra-less pyright on the touched files: clean.
- **Blast radius:** in-process probe over all 65 Task-replay rows and 65 BenchmarkSpec rows:
  0 refusals, facts identical to their rows (gdpval-text's Task couldn't be built locally,
  `pdfplumber` missing; its scorer facts checked separately, clean). The guards fire on drop
  (F1) and stereoset (F5).
- **Deviations:** the work was first built as one five-guard branch, reviewed, then split into
  three stacked PRs at the owner's call (2026-10-15) because the guards need different review.
  The F5 test's one-Sample Task helper and its `exact` import live in this PR's test block
  rather than in the F2 section where they first appeared.
- **Owner verify:** none; nothing paid, no Benchmark changes.

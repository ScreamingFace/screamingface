---
ticket: OME-1757
stack: screamingface-engine
status: done
started: 2026-10-28
finished: 2026-10-29
---

# warn-on-bundled-dataset-licences — the importer warns when a dataset bundles other datasets

## Intent

The importer proposes a Benchmark's licence line from the one Hugging Face dataset card. Some
datasets bundle many source datasets under their own terms: MathVista's card says cc-by-sa-4.0
(a cleared licence) while 195 of its 1,000 testmini Cases come from NonCommercial sources, and
MMMU reads 30 subject configs so no card is read at all. The importer should say "aggregate
dataset — check each source's licence by hand before writing the licence line" when a dataset
looks like a bundle. It warns only: it never blocks and never changes the proposed value or any
existing row.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/task_replay_rows.py`:
  `CardLicense` gains `aggregate_signal`; `card_license_of` sets it from two shapes the importer
  already reads (no new network call): 3 or more configs of one Hub repo among the Case Sources,
  or a `source` column in the card's `dataset_info.features` (nested structs included). The
  declaration's licence note carries the warning; the signal passes the comment injection guard.
- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`: the command passes
  the signal to the rows and prints `WARNING: aggregate dataset — …` on stderr.
- `apps/screamingface-engine/tests/unit/inspect/test_aggregate_dataset_warning.py` (new).

## Test plan

- MathVista-shaped card (licence cc-by-sa-4.0, `metadata.source` struct field) → signal set,
  value still cc-by-sa-4.0. Multi-config card with `source` in one config → signal set.
- 30 MMMU-shaped Case Sources → signal set, no card read, value TODO.
- Two configs of one repo (air_bench shape) → no signal; a split named `source` → no signal.
- commonsense_qa-shaped plain card → no signal, no warning in rows or stderr.
- Rendered row: warning above `license=`, value unchanged; a signal with a line break refused.
- Command: stderr warning plus the note in `prepare.py` for a bundle; none for a plain dataset.

## Acceptance

- Each signal, the review note, the stderr line and the injection guard fail a test when removed.
- No existing test changes; no existing row changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the `docs/tasks/` mirror.
- **Commits:** feat(screamingface-engine): warn when an imported dataset bundles other datasets.
- **Gates:** relevant tests only, inspect extra: `test_aggregate_dataset_warning.py` (11),
  `test_task_replay_rows.py` + `test_importer_command.py` (58), and the six tests that import
  `task_replay_rows` (106 passed). Mutation checks, each reverted in place: dropping the source
  column signal (3 fail), the config signal (1), threshold 3 → 2 (1), the review note (2), the
  stderr line (1), the CLI wiring (1), the guard (1). ruff check, ruff format, pyright clean on
  the touched files.
- **Deviations:** review round (2026-10-29), after the PR opened:
  - Owner-level call made by the main session: a detected bundle now writes the licence as TODO
    (the card's value kept in `card_says` for the note), even when the card's licence is
    cleared. A warning comment alone could be deleted with CI green; a TODO value is refused by
    `test_task_replay_declarations_carry_an_owner_license_decision` until a human writes the
    line. The import itself still succeeds. This replaces the plan's "never changes the value".
  - Two more signals: the card's own `source_datasets` naming more than one dataset, and the
    column match is now case-insensitive over `source` and `source_dataset` (never a bare
    `dataset`).
  - Live check done 2026-10-29: `HfApi().dataset_info("AI4Math/MathVista", revision=2b6ad694…)`
    returns licence cc-by-sa-4.0, `source_datasets: ['original']` and a `metadata` struct
    holding `source`; the importer's licence reader returns TODO with card_says cc-by-sa-4.0
    for it, mit with no signal for commonsense_qa, and TODO with the 30-config signal for MMMU.
  - Review-round gates: `test_aggregate_dataset_warning.py` + `test_task_replay_rows.py` +
    `test_importer_command.py` 72 passed; the six importing tests 106 passed; seven more
    mutation checks each fail at least one test. ruff, ruff format, pyright clean.
- **Owner-verify:** on the next real import of a Hugging Face Benchmark, confirm a bundle
  (MathVista) lands as `license="TODO"` with the warning and a plain dataset keeps its licence.

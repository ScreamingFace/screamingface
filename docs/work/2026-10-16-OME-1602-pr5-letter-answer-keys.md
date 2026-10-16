---
ticket: OME-1602
stack: screamingface-engine
status: in_progress
started: 2026-10-16
finished:
---

# OME-1602-pr5-letter-answer-keys: multi-letter answer keys (F6) and the Benchmarks they unblock

## Intent

PR 5 of 7 for OME-1602. Case Preparation refuses a multiple-choice Case whose answer key names
several options: a list of letters (truthfulqa, stereoset, cyse4 malware_analysis) or one
comma-joined string (chembench's "A,D"). The importer also never writes `multiple_correct`, so
an eval that lets the Candidate pick several letters would be graded as if it picked one. This
unit accepts such keys on a row that opts in, carries `multiple_correct` from the eval's
`multiple_choice` solver onto the row, and imports the Benchmarks it unblocks.
cyse4_threat_intelligence waits for its PDF mirror (an HF dataset under the ScreamingFace org,
owner decision 2026-10-16).

## Planned changes

- `prepare.py`: `TaskReplayCasesSpec.letter_list_key`; `_validated_answer_key` accepts a list
  of option letters, or one comma-joined string of them, beside choices when it is set.
- `importer.py`, `import_replay.py`, `task_replay_rows.py`: `--letter-list-key` flows to the
  declaration; the child reads `multiple_correct` from the `multiple_choice` solver and the
  row writer writes it.
- Rows: truthfulqa (mc1), chembench, stereoset, cyse4_malware_analysis.
- Tests: `test_list_target.py` (appended), the import-replay and row-writer tests, the
  expected-value tables.

## Test plan

- A default row still refuses a list beside choices; an opted-in row accepts a list of valid,
  distinct letters and a comma-joined string of them, and refuses a letter past the last
  option, a duplicate, a blank entry, or a key that is not letters.
- The scorer gets back the key inspect would have given it.
- `multiple_correct=True` on the solver reaches the row; a bare `multiple_choice()` writes none.

## Acceptance

- The new Benchmarks assemble; 0 existing rows change.
- The named test files, ruff, and both pyright passes are green.

## Outcome

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
- **Owner verify:**

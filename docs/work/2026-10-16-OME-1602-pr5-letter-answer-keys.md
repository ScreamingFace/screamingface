---
ticket: OME-1602
stack: screamingface-engine
status: done
started: 2026-10-16
finished: 2026-10-16
---

# OME-1602-pr5-letter-answer-keys: multi-letter answer keys (F6) and the Benchmarks they unblock

## Intent

PR 5 of 6 for OME-1602. Case Preparation refuses a multiple-choice Case whose answer key names
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

- **Actual files:** as planned, plus `--drop-scorer` (stereoset's bias scorer, an owner
  decision), `test_letter_list_key_imports.py` (new: each row graded on its real hook), and
  chembench's stand-in metadata in `replayed_cases_helpers.py`.
- **Commits:** the mechanism; the lone-Named-Score fix; the four rows; typing; the review fixes.
- **Gates:** the inspect unit lane plus the row-reading tests outside it: 2347 passed with the
  inspect extra; ruff check and format, and pyright on the touched files: clean. All 81 rows
  assemble; every existing row's revision is unchanged (checked by the review).
- **Deviations:**
  - A Task with two scorers and one dropped was written with a lone Named Score, which the
    grader reads as a dict scorer, so every Case failed. Grading stereoset end to end found it.
    One kept scorer now writes no Named Scores; two PR 2 tests that pinned the old shape were
    changed (owner-approved, 2026-10-16).
  - Review fixes: `multiple_correct` now pins into the revision (only cyse4 sets it); a moved
    headline is flagged even with one scorer left; `--drop-scorer` refuses a scorer already
    dropped as judged; chembench's description says letters must be comma-joined exactly.
  - chembench and stereoset carry no upstream case count: eval.yaml's 2,786 and 4,299 do not
    describe the pinned data (2,785; 2,123 records, 8 dropped by the eval as id collisions).
  - cyse4_threat_intelligence is deferred: its 26 report PDFs need a mirror, an HF dataset
    under the ScreamingFace org (owner decision, 2026-10-16). The bundle is prepared: all 26
    PDFs match upstream's pinned sha256.
- **Owner verify:** create the ScreamingFace HF dataset and upload the 26-PDF bundle; then
  threat_intelligence lands as its own follow-up. Nothing paid in this unit.

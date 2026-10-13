---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-13
finished: 2026-10-13
---

# rich-draft-feedback — send an allowed Benchmark's partial score and checker words as Draft Feedback

## Intent

OME-1527 Work order #12 (R9). On the plugin lane, the Corrective Loop's mid-run check sends
the Case score as `satisfaction` (0 or 1 under IFEval's strict headline) and one fixed sentence.
The hand-built IFEval route sends the fraction of instructions met and the checker's own words
for each failed instruction. Without those, IFEval's loop can't rank drafts or tell the
Candidate what to fix once it moves to a local Task (row 15). This unit lets a row that the
owner allowed send what its scorer wrote for the Candidate, and nothing else of the Score.

## Planned changes

- `single_shot.py`: `DRAFT_FEEDBACK_METADATA_KEY` (`"draft_feedback"`), a 2,000-character
  bound, the `scorer_draft_feedback` factory flag (refused without `with_check_surface`; a
  conditional revision pin), and `_scorer_draft_feedback`, which reads that one key off the
  headline Check and refuses any envelope it can't vouch for.
- `benchmarks.py`: the `BenchmarkSpec.scorer_draft_feedback` field, passed through.
- No row sets it: ifeval's row arrives with row 15, after row 13 (R10).

## Test plan

- `tests/unit/inspect/test_scorer_draft_feedback.py` (new), on gsm8k's row with a leaky
  stand-in scorer (the key "42" in its explanation, an extra metadata key, and an extra
  envelope field): the record carries exactly the scorer's satisfaction and words, in the
  hand-built record's shape, with no "42"; a pass gets no words; a row without the flag keeps
  the fixed sentence; nine malformed envelopes are refused without quoting the scorer; the flag
  moves the revision and is refused without the offer.
- `tests/unit/test_draft_feedback_offer_is_owner_opt_in.py`: one appended test, rows asking
  for the scorer's words ⊆ the owner allow-list.

## Acceptance

- A row without the flag sends byte-identical Draft Feedback; no published revision moves.
- With the flag, only `Score.metadata["draft_feedback"]`'s two values reach the Candidate.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** see the PR.
- **Gates:** relevant files only: `test_scorer_draft_feedback.py`,
  `test_inspect_gsm8k_benchmark.py` (the plugin lane's check-surface tests),
  `test_inspect_single_shot.py`, `test_published_revisions.py`,
  `test_inspect_imported_benchmarks.py`, `test_draft_feedback_offer_is_owner_opt_in.py`: 411
  passed with the inspect extra; extra-less, the allow-list and revision tests pass and the new
  file skips. Two mutations (accept an extra envelope field; ignore the row flag) each turned
  one test red. ruff + format clean; extra-less pyright 0 errors on the touched sources.
  Append-only check by hand (OME-1575): passes, the allow-list test is a pure append, so the
  OME-1527 manifest needs no entry for this branch.
- **Deviations:** the lane reads the envelope off the headline Check's evidence (where the
  scorer adapter already copies JSON-safe `Score.metadata`) instead of adding a field to the
  shared `CaseGradeOutcome`, so shared grading is untouched. The envelope also appears in the
  published Report's evidence, like every other JSON-safe metadata key.
- **Owner-verify:** (1) trust review: the PR's Trust boundaries table; the owner decides that
  a Benchmark's scorer words are safe by adding it to the allow-list and setting the row flag,
  after reading that scorer (row 15 for IFEval). (2) Row 15 replays ifeval's Corrective Loop
  golden (0.9184) unchanged; that run checks the words match the hand-built route's bytes.

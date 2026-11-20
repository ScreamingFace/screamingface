---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done
started: 2026-11-20
finished: 2026-11-20
---

# medxpert-card-first-letter-rule — state MedXpertQA's real first-letter rule on its page

## Intent

The MedXpertQA page says the grader "takes the last bracketed letter, then the last option
letter". That describes `grading.extract_letter`, which is not on the scoring path. Scoring
runs `answering.extract_choice_letter` (the official harness's `answer_cleansing`) on the
turn-2 reply: the FIRST capital option letter standing alone wins. A user's run lost about 11
points because a prose commit ("A humeral shaft...") committed the article "A" (475 of 2,450
Cases). Rewrite the answer-format sentence to the real rule and warn recipe authors to make
the commit reply the letter alone. Description only: the revision is not built from it, so no
grading and no published revision moves.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/medxpert/definition.py` —
  `ANSWER_FORMAT` text and its FEATURE comment.
- `apps/screamingface-engine/tests/unit/test_medxpert_answer_format_scoring_path.py` (new) —
  grades every reply the sentence quotes through the scoring path.
- `docs/tasks/2026-11-20-OME-N-medxpert-card-first-letter-rule.md` (mirror, at PR-open).

## Test plan

- RED: the page quotes a prose-first reply ("A humeral shaft fracture, so D") and the scoring
  path commits A for it — fails today (not quoted).
- Every reply the sentence says counts as D is committed as D by `extract_choice_letter` with
  the real trigger; "not sure" commits nothing.
- The revision and fingerprint do not move (existing `test_benchmark_fingerprints.py`).
- Prior `test_medxpert_answer_format.py` stays unmodified and green.

## Acceptance

- The page states the first-letter rule and the prose trap, with the authoring advice.
- Every quoted reply grades as the sentence says through the real scoring parser.
- `REVISION` and `FINGERPRINT` unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `medxpert/definition.py` (`ANSWER_FORMAT` + its comment) and
  the new `tests/unit/test_medxpert_answer_format_scoring_path.py`; mirror added at PR-open.
- **Commits:** `fix(screamingface-engine): state MedXpertQA's real first-letter rule on its page`
- **Gates:** RED 3 failed / 13 passed (the prose trap unquoted, no authoring advice, "last"
  still present) → GREEN: 50 passed, 1 skipped across the new file,
  `test_medxpert_answer_format.py`, `test_medxpert_definition.py`, `test_medxpert_answering.py`
  and `inspect/test_benchmark_fingerprints.py` (skipped without the inspect extra; with it, the
  medxpert fingerprint test passes, so `FINGERPRINT` and `REVISION` are unchanged). ruff check,
  ruff format and pyright clean on both touched files.
- **Deviations:** the prior `test_medxpert_answer_format.py` still grades the quoted replies
  through `grading.grade`, which is not the scoring path. Left unmodified (append-only rule);
  every reply it quotes also grades the same way through the scoring parser, which the new
  file pins.

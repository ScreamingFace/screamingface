---
ticket: OME-1149
stack: screamingface-engine
status: in_progress
started: 2026-09-12
---

# OME-1149 — Fold MedXpertQA's grading orchestration onto the shared scored path

## Intent

MedXpertQA predates the scored spine and hand-rolls ~380 lines of orchestration
(per-case loop, failure ladder, result assembly) around `spine.RowReader`. Its own
docstring named the trigger: "a second non-rubric board" — ifeval's fold (OME-1101)
supplied it, plus the scorer parameter that removes MedX's stated objection. After this
fold a fixed-answer benchmark writes one check function plus its exam formula.

## Design

- **`aggregate.py` shrinks in place** (the acceptance names the file): keeps the answer
  match, accuracy formula, failure wording, and the OME-1037/official-harness
  invariants; orchestration comes from `ScoredPath`. Public functions (`aggregate`,
  `load_answer`, `selected_cases`) keep their signatures — the whole medxpert unit
  suite runs UNTOUCHED.
- **Two small spine seams** (each RED-tested first in `test_spine_scored.py`):
  1. `missing_material_code` on `ScoredPath` — the material-missing rung's published
     code becomes board-named (MedX: `missing_answer_asset`; rubric boards pass
     `missing_rubric_asset`, byte-identical; ifeval names `missing_instruction_spec`
     for its unreachable rung).
  2. `case_metadata` parameter on `aggregate()` — per-case public metadata (MedX's
     three slice tags from the private answer record) merged into scored AND failed
     results, so failed cases keep their slice tags. Boards that omit it are
     byte-identical.
- Row decode hoists the attempt into the spine's candidate-field shape (reasoning
  riding metadata); `selected_cases` delegates to `spine.read_selected_cases`
  (messages already byte-identical).
- Stale `spine.CaseGrader` docstring reference rewritten against the real seam.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/scored.py` —
  the two seams above.
- `.../benchmarks/gdpval/grade.py`, `healthbench/grade.py`, `ifeval/grade.py` — pass
  the explicit `missing_material_code` (no output change).
- `.../benchmarks/medxpert/aggregate.py` — orchestration deleted; hook + scorer +
  wording remain.
- `tests/unit/test_spine_scored.py` — RED tests for both seams (append-only).

## Test plan

- RED: spine — `case_metadata` reaches scored, ladder-failed, and missing-row results;
  `missing_material_code` publishes the board's code with its message.
- Existing `test_medxpert_aggregate.py` (17 tests) passes byte-for-byte UNTOUCHED —
  it pins: 0.0-unanswered-in-denominator, the two-refusal split (graded text refusal
  vs `provider_refusal`), slices + reasoning on scored and failed cases, the
  answer-key-never-leaks invariant, and every ladder rung.
- No medxpert golden exists (only draco-3pass / healthbench-worst30 / ifeval /
  gdpval-text are recorded), so the unit suite is the net; the existing four golden
  replays guard the shared-path changes.

## Acceptance

- `medxpert/aggregate.py` keeps only benchmark-specific logic; no rubric-flavored code
  in any MCQ result; no `CaseGrader` reference.
- Full engine gates green; 4 existing golden replays green.
- Diff well under ~500 lines.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

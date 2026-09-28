---
ticket: OME-1101
stack: screamingface-engine
status: done
started: 2026-09-11
finished: 2026-09-12
---

# OME-1101 — Fold ifeval onto the shared spine, keeping its deterministic grading as its hook

## Intent

IFEval is the only deterministic-grading board, and its `aggregate.py` (442 lines) is a
third hand-rolled shape of the marking room the spine already provides to gdpval and
healthbench. Folding it proves the spine is not rubric-shaped and gives the `deterministic`
kind a real consumer (MedXpertQA copy target; `OME-1149` dedupe depends on it).

## Design decisions (owner-approved 2026-09-11)

- **Collected-error failure output stays byte-identical.** The freshly recorded ifeval
  golden pins case 1069 as `stage: grading, code: model_token_cap` — ifeval's own
  collected-row wording. `ScoredPath` gains ONE optional board-owned hook for the
  no-usable-row outcome; ifeval supplies its current wording, rubric boards keep the
  spine default. This also leaves the `OME-981` candidate-vs-grading boundary decision
  open, per that ticket's explicit coordination note.
- **Metric vocabulary becomes the scorer parameter.** `ScoredPath.aggregate` takes a
  `scorer` (whole `CandidateScore` builder) instead of `mean`; rubric boards bind
  `exam_scorer(mean)` at their call sites (byte-identical output), ifeval passes its
  published accuracy formulas.
- **Spec-aware record validation moves into the board's `decode_case_evaluation`
  closure** (RowReader seam), so every malformed-envelope abort keeps today's
  abort-the-run semantics and "position N" messages; `grade_case` becomes pure
  record→grade and cannot fail.
- **Selection stays ifeval-owned** (cases.json file-order prefix + spec-presence abort),
  matching gdpval keeping its exam-registry `case_ids`.
- `vendor/`, `grading.py`, the rendered expression, and `definition.py`'s declaration
  (`failure_policy=coverage_declare`) are untouched.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/scored.py` —
  `scorer` parameter; optional `missing-row/collected-error` board hook.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/gdpval/grade.py`,
  `healthbench/grade.py` — bind `exam_scorer(mean)` at the call site (no output change).
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/ifeval/grade.py` — NEW
  hook module: failure messages, selection/spec loaders, deterministic `grade_case`,
  ifeval scorer, `aggregate()` wrapper, `ScoredPath` binding.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/ifeval/case_evaluation.py`
  — spec-aware graded-record validation (absorbed from `aggregate.py`).
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/ifeval/aggregate.py` —
  DELETED.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/ifeval/runtime.py` —
  import the new module.
- Tests: repoint `test_ifeval_aggregate*.py`, `test_ifeval_unscored_results.py`,
  `test_ifeval_official_identity.py`, `test_ifeval_golden_parity.py`,
  `test_benchmark_outcome_conformance.py` imports to the production path (assertions
  unchanged); new spine tests for the scorer parameter and the board hook.

## Test plan

- RED: new `test_spine_scored` cases — custom scorer receives the assembled CaseResults;
  board missing-row hook overrides the default; default unchanged when hook absent.
- Existing ifeval unit suites keep passing UNMODIFIED in their assertions (imports only
  repointed) — they pin: collected row → stage grading + diagnostic code + row_index,
  graded refusal scored, malformed envelope aborts with "position N", official-key case
  mapping, accuracy formulas.
- e2e: ifeval replay against the committed golden (score 0.9184, case 1069 pin) — free,
  snapshot-driven.

## Acceptance

- `benchmarks/ifeval/aggregate.py` gone; hook module ~150 lines plus `grading.py`.
- ifeval e2e replay green against the existing golden (no re-bless).
- gdpval + healthbench goldens replay green (byte-identical output).
- Diff under ~500 lines.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/test_benchmark_declaration.py` (ifeval
  moved from the aggregate-module loop to the ScoredPath loop — the fold itself),
  `test_spine_case_grader.py` and `test_spine_scored.py` helpers (`mean` →
  `scorer=exam_scorer(mean)`, the approved seam change).
- **Commits:** `cdeec4f2` fold + `138f0bbf` identified-error-row pinning test, squash-merged as `9f3d46a2` (PR #913).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN
  (ruff check/format, pyright, layering, pytest 2712 passed / 6 skipped, cov ≥80%).
  e2e replay: 4 boards green (ifeval 0.9184 incl. the case-1069 failure pin,
  gdpval-text, healthbench-worst30, draco-3pass); 2 pre-existing no-fixture skips.
- **Deviations:**
  - `--skip-append-only` used once: the owner-approved scorer seam forces three
    mechanical prior-test edits (two helper signatures, one mechanism-check loop
    move); every behavioral assertion is unchanged and all 80 pre-fold ifeval
    tests pass with assertions untouched.
  - `ifeval/grade.py` is 400 lines against the ticket's ~150 estimate: the spec
    loaders, selection, and scorer moved verbatim from the deleted 442-line
    `aggregate.py`, and house Feynman-docstring density accounts for the rest.
    Net engine-source diff is negative.
  - The spine gained one optional `missing_row_result` hook (owner-approved
    2026-09-11) so ifeval's golden-pinned collected-row wording stays
    byte-identical and the `OME-981` failure-boundary decision stays open.

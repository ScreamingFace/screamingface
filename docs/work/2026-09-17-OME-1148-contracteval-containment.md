---
ticket: OME-1148
stack: screamingface-engine, screamingface
status: in_progress
started: 2026-09-17
finished:
---

# OME-1148 — ContractEval as a judge-free clause-containment board (rebuild on the new spine)

## Intent

Register the CUAD test split (4,182 rows over 102 commercial contracts × 41 clause categories)
as an Engine-owned board reproducing the ContractEval protocol (arXiv 2508.03080). The Candidate
receives a full contract plus one clause-category question and must quote the answering
sentences VERBATIM, or the literal `"No related clause."` Grading is deterministic string
containment — zero judge tokens.

This is a **rebuild**, not a fresh onboarding. A complete implementation was written on
2026-09-09 (8 commits, both stacks green, live-verified), but PR #865 was closed unmerged and
`main` has since moved 191 commits under an onboarding-infra overhaul. The work is preserved at
tag `OME-1148-v1-pre-overhaul` (`b39c5da2`) and on `origin/OME-1148-contracteval`.

## Why the rebuild is not a rewrite

The overhaul replaced `spine.CaseGrader` with a `grade_case` seam (`spine/scored.py`). The spine
now owns the marking room — roll call, row filing, the failure ladder, result assembly, and the
exam reduction. A board contributes `grade_case`, its failure wording, and its scorer.

Two consequences, both verified against `main` before starting:

1. **The expensive part survives.** `grading.py` is pure protocol: the containment verdict,
   abstention detection, and Jaccard, each mirroring the reference by file and line. It was
   differential-tested against the reference's transcribed functions over 2,970 (output, gold)
   pairs on 400 real CUAD rows with **zero** mismatches. None of that depends on the spine.
2. **My prior objection to the spine is resolved.** I recorded (2026-09-13, reviewing the
   inspect-import architecture) that the spine had no aggregation seam, so this board's
   confusion-matrix score had nowhere to go. `ScoredPath.aggregate()` now takes
   `scorer: Callable[[Sequence[CaseResult]], CandidateScore]` — fully general;
   `exam_scorer(mean)` is only the rubric convenience. The existing
   `_confusion_matrix_score` binds directly.

## Established facts carried forward (unchanged by the overhaul)

Spec: `docs/spec/2026-09-17-OME-1148-contracteval-containment.md` (F-1…F-10, D-1…D-8 intact).
The protocol, the dataset pin, the measurements and the deviations are properties of
ContractEval and CUAD, not of our infrastructure. Re-verified on this branch:

- **Not importable.** ContractEval is absent from inspect_evals (171 evals). `ContractBench`
  there is software/API contracts — presigned URLs, OAuth tokens, HMAC webhooks — a name
  collision, nothing more. So this board stays hand-authored; the import path does not apply.

## Planned changes

Modelled on `medxpert/` — the closest analogue (deterministic, non-rubric, private answer key),
whose reducer went 373 → 245 lines through this same migration.

- `benchmarks/contracteval/` — `pins.py` `prompts.py` `grading.py` `prepare.py`
  `case_evaluation.py` `definition.py` `runtime.py` `aggregate.py` `__init__.py`
- `benchmarks/builtins.py` — registration
- `tests/unit/test_contracteval_*.py`
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `_BENCHMARKS` + asset manifest
- `packages/screamingface/scripts/build_notebooks.py` + the generated notebook

## Test plan

Port the 68 tests from the tag first — they are the regression net for the migration, and any
that fail identify exactly where the new seam differs from the old assumption. Then add tests
for whatever the new `ScoredPath` wiring introduces.

## Acceptance

- `sf.evaluate(model, benchmark="contracteval")` runs end to end, reporting F1/F2, Jaccard and
  laziness matching the paper's definitions.
- The dataset is pinned reproducibly without the dead script loader.
- Both stacks' gates green; a live run grades real cases.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

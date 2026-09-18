# OME-1148 — ContractEval rebuild plan (on the post-overhaul spine)

**Ticket:** [OME-1148](https://linear.app/openmined/issue/OME-1148/onboard-contracteval-as-a-judge-free-clause-extraction-benchmark)
· **Spec:** `docs/spec/2026-09-17-OME-1148-contracteval-containment.md`
· **Ledger:** `docs/work/2026-09-17-OME-1148-contracteval-containment.md`
· **Prior work:** tag `OME-1148-v1-pre-overhaul` (`b39c5da2`) · **Date:** 2026-09-17

A full implementation exists at the tag. This plan is a **migration order**, not a build order:
each task ports a layer from the tag and states what the overhaul forces to change. Porting in
dependency order means every task ends with its own tests passing, so a break localises to the
layer that moved.

## Global constraints

- **Port tests first, then code.** The 68 tests at the tag are the regression net for this
  migration. A ported test that fails is the signal that the seam changed — investigate, never
  weaken. New behaviour still gets RED-first tests.
- **Never edit** `benchmarks/aggregation.py` or `benchmarks/contract.py` — owned elsewhere.
- **No `exam_scorer(mean)`** — this board's reduction is a confusion matrix (spec §4).
- **`missing_material_code="missing_answer_asset"`** — the spine defaults to
  `missing_rubric_asset`; publishing a rubric code on a board with no rubric contradicts its
  own message (the OME-1149 note in `ScoredPath`).
- ruff limits: `PLR0911` max 3 returns · `PLR0912` max 7 branches · `C901` complexity 8 · line 100.
- Gates green per stack before each commit: `uv run .claude/scripts/run_gates.py <stack>`.

## Task 1 — the pure core, ported unchanged

`pins.py`, `prompts.py`, `grading.py` + `test_contracteval_grading.py` (20 tests).

These depend on nothing the overhaul touched. **The expectation is a byte-identical port with
all 20 tests green on first run.** If anything fails, the finding is about `main`, not about
ContractEval, and is worth reporting before continuing.

Re-run the differential test against the reference (2,970 pairs over 400 real CUAD rows) as a
one-off in the scratchpad to confirm the port preserved protocol fidelity.

## Task 2 — assets

`prepare.py` + `test_contracteval_prepare.py` (14 tests).

Check against `main`'s current prepare conventions before porting — `medxpert/prepare.py` is the
reference. Keep the `main()` entry point: the SDK bakes by spawning
`python -m …contracteval.prepare --out <dir>`, and its absence fails with
`prepared output is missing [...]`, which names the symptom and hides the cause. Two tests pin it.

## Task 3 — the migration proper

`case_evaluation.py`, `aggregate.py`, `definition.py`, `runtime.py`, `builtins.py` +
`test_contracteval_{case_evaluation,aggregate}.py`.

This is the only task with real design work. `aggregate.py` loses its ladder, its result
assembly and its failure plumbing to the spine (~414 lines → a `ScoredPath` instance plus
`_grade_case` plus the scorer). What must survive the shrink, because each was a bug found the
hard way:

- the verdict-field validation in the envelope (a record missing `correct` read as `False` is a
  silent false negative, not a missing score);
- the polarity cross-check between the baked key and the check record (`polarity_mismatch`);
- the F1/F2 zero guard (the reference raises `ZeroDivisionError` for an always-abstaining model);
- laziness divided by *selected* positives, not the reference's hardcoded `1244`.

Confirm where each now belongs: the spine may already own some of the failure ladder, in which
case the board's copy is deleted rather than ported — but only after checking, never assumed.

## Task 4 — SDK and notebook

`cli.py` (`_BENCHMARKS` + asset manifest — both unchanged on `main`, so this is a clean port),
`build_notebooks.py`, regenerated notebook. Ships `PARAMS = {"max_tokens": 4096}` with **no**
`temperature`: `openai/gpt-5.5` answers 404 for any value and `claude-opus-4.8` answers 400.

## Task 5 — bake, pilot, close

`screamingface prepare contracteval` (expect 4,182 cases / 1,244 positive / 2,938 negative — the
1,244 is the constant the reference hardcodes, so a mismatch means the pin drifted), then a live
`limit=8` run, then ledger Outcome and the close comment.

## Deliberately deferred

- The D9 landing-label split — one ticket, following GDPval and MedXpertQA.
- Renaming the Linear issue off "span-extraction" (owner action; the doc files are already
  renamed to `-containment`, which is what the code calls it: `method="containment"`).

## Execution record (filled during implementation)

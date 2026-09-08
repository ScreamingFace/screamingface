---
ticket: OME-1148
stack: screamingface-engine, screamingface
status: in_progress
started: 2026-09-09
finished:
---

# OME-1148 — Onboard ContractEval as a deterministic span-extraction benchmark

## Intent

Register the CUAD test split as an Engine-owned board reproducing the ContractEval protocol
(arXiv 2508.03080). The Candidate receives a full commercial contract plus one clause-category
question and must return the answering sentences VERBATIM, or the literal `"No related clause."`
Grading is entirely deterministic — span F1/F2, Jaccard, and the "laziness" false-abstain rate —
so this is the cheapest per-row board we carry: zero judge tokens.

It is also the first board with a span-overlap grader. The Engine has exactly three grading
methods today (`rubric` ×4 boards, `exact_match` ×2, `deterministic` ×1) and no span, F1, or
Jaccard code anywhere. MedXpertQA proved the non-rubric path — `spine.RowReader` without
`spine.CaseGrader` — and this board follows it.

Neutral board, as MedXpertQA was: the "laziness" metric is the same false-abstain lever as the
HealthBench refusal finding and may favour panels, but we report it because the paper does, not
to win.

## Prior art

- Paper: https://arxiv.org/abs/2508.03080 · https://aclanthology.org/2025.nllp-1.19/
- Reference harness: https://github.com/olivialiu121/ContractEval — **verified to exist, MIT**,
  carries `Evaluation.py` (F1/F2 · Jaccard · laziness). Mirror into `.refs/` per the
  protocol-alignment rule; do NOT reinvent the metric definitions.
- Dataset: https://huggingface.co/datasets/theatticusproject/cuad-qa (CUAD, CC BY 4.0)
- Prior costing/screening: `LiveTruth_leaderboard_work/docs/cost-workings-2026-07-21/e12-contracteval/`
  and `docs/new-benchmarks.md` in that repo.

## Open questions — ALL RESOLVED in the spec (2026-09-09)

Spec: `docs/spec/2026-09-09-OME-1148-contracteval-span-extraction.md`

1. **Dataset loading — SOLVED.** CUAD's HF `main` is script-loader only, but the auto-converted
   `refs/convert/parquet` branch exists at `d9c4ee0250ae2eb97bdb5b50773ab14ea62d0631`. Loaded
   successfully on `datasets 5.0.1`; 4,182 rows returned. We pin that revision.
2. **Row count — EXPLAINED.** HF test = 4,182 (102 contracts × 41 questions, verified). The
   paper's 4,128 is its own evaluated-output count, not a different key: the reference harness's
   hardcoded laziness denominator (1244) equals the FULL split's positive-row count exactly.
3. **Long context — measured.** min 645 · median 25,657 · max 300,768 chars. Explicit pinned
   truncation rule with a per-case `truncated` flag (D-7).
4. **Answer key — READ, and the July screening note was WRONG.** ContractEval is **not** a
   span-overlap benchmark. The per-row verdict is strict verbatim containment of *every* gold
   span (`all(substr in output)`), else abstain detection on negatives. F1/F2 are computed from a
   **dataset-level confusion matrix**, not per case. Jaccard is a secondary, positive-rows-only
   mean and is absent from the reference's headline results.

Net effect: **smaller** than the ticket assumed — no span-overlap grader is needed. The per-case
verdict is a boolean like MedXpertQA's; the novelty is confined to `aggregate.py`, which must
build a confusion matrix instead of averaging case scores.

## Planned changes

Plan: `docs/plan/2026-09-09-OME-1148-contracteval-span-extraction.md` — five tasks, of which
1-4 have landed. Files as built:

- `benchmarks/contracteval/` — `__init__ pins prompts grading prepare case_evaluation definition
  runtime aggregate` (no `answering.py`; see Deviations)
- `benchmarks/builtins.py` — registration
- `tests/unit/test_contracteval_{grading,prepare,case_evaluation,aggregate}.py` — 53 tests
- `tests/unit/test_benchmark_declaration.py` — one row added to the policy table
- `packages/screamingface/src/screamingface/_runtime/cli.py` — `_BENCHMARKS` + asset manifest
- `packages/screamingface/scripts/build_notebooks.py` + `examples/12_contracteval.ipynb`

## Test plan

To be filled from the spec. The grading module is pure and must be pinned hardest: F1/F2 and
Jaccard against worked examples taken from `Evaluation.py`, the abstain path both ways (correct
abstain vs laziness), multi-span golds, and the empty-prediction verdict.

## Acceptance

- `sf.evaluate(model, benchmark="contracteval")` runs end to end and reports F1/F2, Jaccard and
  laziness matching the paper's definitions.
- The dataset is pinned reproducibly without the dead script loader; row count reconciled
  against the paper's 4,128.
- Over-long contracts have a documented, tested handling rule rather than an implicit truncation.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

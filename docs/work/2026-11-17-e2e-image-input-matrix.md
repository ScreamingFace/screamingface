---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: python
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# e2e-image-input-matrix — workbench notebook that validates image and PDF input per model

## Intent

Prove the OME-1529 image-input feature against real models: a workbench notebook runs a
model × media × path matrix on the `local` target with known-answer pictures, and passes only
when every capable model reads the picture and every blind model is refused before a paid call.
Spec: `docs/spec/2026-11-17-e2e-image-input-matrix.md`.

## Planned changes

- Spec + plan: `docs/plan/2026-11-17-e2e-image-input-matrix.md` (tasks 1–6).

## Test plan

- Defined in the plan.

## Acceptance

- Spec §3 holds on one recorded paid local run; evidence bundle and `matrix.json` attached.

## Task 4 — gold Cases calibration (2026-11-17, paid, local on a Mac)

- **Stack:** the workbench `local` target (`workbench.targets.local_stack`: `screamingface up`
  on :9105/:9106/:9108 + an inspect Engine on a free port), assets root in the session
  scratchpad (ifeval copied from `~/.screamingface/benchmark-assets`, FigQA prepared fresh:
  181 Cases, digest `616aeb49…`, equal to the pin). Key via the `workbench-ui` launcher's
  resolver, never printed. Everything torn down after the run.
- **Served picture Benchmarks:** the Engine lists all eleven (FigQA, TableQA, MMMU mc/open,
  MathVista, HLE, HLE-Diamond, LABBench2 FigQA2/TableQA2 img, ZeroBench, MaCBench). Dropped as
  Linux-sealed (picture notebook `SEALED_ON_LINUX`): MMMU mc, MMMU open, MathVista, ZeroBench.
- **PDF Cases on any served Benchmark: no.** The inspect importer keeps only png/jpeg/gif/webp
  (`picture_input._media_type`); the candidate-input envelope admits PDF, but no Benchmark
  produces one. The PDF column is url4-only (spec §3.4).
- **`labbench2_figqa2_img`: not run.** Its dataset (EdisonScientific/labbench2) is gated and no
  `HF_TOKEN` is available here, so its Cases cannot be prepared. Gold Cases come from FigQA only.
- **Run:** `inspect-lab_bench_figqa`, Cases 1–10, `max_tokens` 4096, one evaluate per model.

  | Model | Score | Correct Cases | Spend (usage.cost_usd) | Trace |
  |---|---|---|---|---|
  | `google/gemini-3-flash-preview` | 0.7 | 1 2 4 6 7 8 9 | $0.0161105 | `cccebbf787ede4a486bd364f47ced91a` |
  | `openai/gpt-5-nano` | 0.4 | 1 2 7 10 | $0.00821811 | `aec1f586c91c8690006c72664a8fa905` |

  Both correct: 1, 2, 7. Kept **1 (gold B)** and **2 (gold F)**; gold read from the scorer's
  MET verdict on each CaseResult and cross-checked against the prepared `targets/<id>.json`.
- **Measured spend:** $0.0161105 + $0.00821811 = **$0.02432861** (budget $2).
- **Files:** `tests/e2e/workbench/fixtures/image_input/gold_cases.json`,
  `tests/e2e/workbench/test_gold_cases.py`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

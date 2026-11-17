---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: python
status: planned   # planned | in_progress | done | blocked
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

- Spec (this step), then a plan in `docs/plan/`.

## Test plan

- Defined in the plan.

## Acceptance

- Spec §3 holds on one recorded paid local run; evidence bundle and `matrix.json` attached.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

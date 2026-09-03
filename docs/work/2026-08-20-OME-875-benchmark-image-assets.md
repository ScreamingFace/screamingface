---
ticket: OME-875
stack: screamingface-engine
status: in_progress
started: 2026-08-20
finished:
---

# OME-875 — Bake all registered Benchmark assets into the image

## Intent

Make benchmark discovery and image preparation describe the same deployable world. The prior image
advertised IFEval and HealthBench but prepared DRACO only, causing valid evaluations to fail at
preflight.

## Planned changes

- Add the deployment/registration/bundle seam described in the approved spec.
- Normalize existing complete-bundle preparers and add one built-in orchestration CLI.
- Point Docker at that CLI.
- Add tests proving shared HealthBench preparation and registration coverage.
- Apply draft-review corrections for exact-one cardinality and family-owned bundle IDs.

## Test plan

- Focused deployment, preparation, protocol, and local-install tests.
- Ruff, format, Pyright, and layering checks.
- Exact stack gate runner with coverage floor.
- Draft PR deployable-image build and second two-axis review.

## Acceptance

- All registered Benchmark assets exist in the built image.
- Registration cannot omit an asset bundle.
- Shared HealthBench assets prepare once.
- CI and second review are green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `benchmarks/{deployment,prepare,builtins}.py`; the DRACO, IFEval, and
  HealthBench family definitions/preparers; `Dockerfile.benchmark`;
  `test_benchmark_deployment.py`; and the four OME-875 records.
- **Commits:** `33e13f22` — initial draft implementation; the review-fix commit carries this
  completed code and record.
- **Gates:** initial local suite 1897 passed, 6 skipped; initial draft-PR image builds passed;
  official `run_gates.py screamingface-engine --skip-append-only` — ALL GATES GREEN.
- **Deviations:** worktree and SDLC records were corrected after the initial draft review. This
  ledger records that ordering explicitly rather than presenting a retrospective plan as prior.
  The append-only guard was skipped with explicit owner approval because the agreed review fix
  changes the synthetic deployment test introduced in the initial commit from zero/many asset
  cardinality to exactly one; no test inherited from before OME-875 was weakened.

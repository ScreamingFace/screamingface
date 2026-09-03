---
ticket: OME-1013
stack: screamingface
status: done
started: 2026-09-03
finished: 2026-09-03
---

# OME-1013 — Harden receipt validation and traceback retention

## Intent

Close the final privacy and diagnostic-quality findings on the local receipt implementation:
reject unexpected evidence fields at the receipt construction boundary, structurally exclude the
internal event `run_id`, and retain the innermost failure frames when a traceback exceeds its bound.

## Planned changes

- `packages/screamingface/tests/test_diagnostics.py`
- `packages/screamingface/tests/test_diagnostic_capture.py`
- `packages/screamingface/src/screamingface/_diagnostics/model.py`
- `packages/screamingface/src/screamingface/_diagnostics/capture.py`

## Test plan

- RED: receipt construction rejects unexpected keys in client, context, execution, and breadcrumb
  evidence rather than freezing them into the public document.
- RED: receipt construction rejects `run_id` wherever nested evidence could carry it.
- RED: a traceback deeper than 32 frames keeps the innermost failure frame and remains ordered.
- GREEN: all existing diagnostic tests remain unchanged and pass.
- QUALITY: run the complete ScreamingFace gate runner.

## Acceptance

- The construction boundary accepts the current allow-listed receipt shapes and rejects widened
  field sets without silently sanitizing them.
- The private event stream topic cannot enter a receipt under the `run_id` field.
- Deep tracebacks retain at most 32 frames, including the frame where the exception originated.
- All ScreamingFace quality gates pass before commit.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `packages/screamingface/src/screamingface/_diagnostics/model.py`,
  `packages/screamingface/src/screamingface/_diagnostics/capture.py`,
  `packages/screamingface/tests/test_diagnostics.py`,
  `packages/screamingface/tests/test_diagnostic_capture.py`, and this ledger.
- **Commits:** this commit — `fix(screamingface): close diagnostic privacy gaps`.
- **Gates:** RED confirmed 8 intended failures; 79 focused diagnostic tests passed; complete
  `python3 .claude/scripts/run_gates.py screamingface` green (append-only check, Ruff lint/format,
  Pyright, full pytest with at least 95% coverage, notebook validation, build, and distribution
  validation).
- **Deviations:** the first full-gate attempt in the feature worktree stopped on the user's
  uncommitted quickstart notebook (`leaderboard` was undefined). The exact source/test patch was
  hash-verified and gated in a clean detached worktree so the notebook and exported JSON remained
  untouched. Parameter values remain governed by their existing generation-policy and Engine
  preflight validation rather than duplicating model schemas inside diagnostics.

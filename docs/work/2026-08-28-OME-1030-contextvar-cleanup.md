---
ticket: OME-1030
stack: screamingface-engine
status: done
started: 2026-08-28
finished: 2026-08-28
---

# OME-1030 — Make accounting capture cleanup task-safe

## Intent

Prevent an abandoned or failed streamed evaluation from raising a secondary `ContextVar` token error when its iterator is closed from a different asyncio task, while preserving run-wide accounting capture and leaving the original evaluation failure unchanged.

## Planned changes

- Add a cross-task iterator-close regression test in `apps/screamingface-engine/tests/unit/test_operation_capture_executor.py`.
- Refine `apps/screamingface-engine/src/screamingface_engine/runner/operation_capture.py` so accounting scopes are owned and unwound by one task.

## Test plan

- Reproduce the current `Token ... was created in a different Context` failure by advancing the decorated iterator in one task and closing it in another.
- Assert early close still closes the inner iterator and leaves no request-accounting or grading-registry scope active.
- Run the focused unit file, then the complete ScreamingFace Engine quality gate.

## Acceptance

- Cross-task close never masks the original evaluation/provider failure with a `ContextVar` cleanup exception.
- Accounting capture remains available throughout a normal streamed run and is fully unwound afterward.
- Existing normal-drain, concurrency, early-close, and cancellation behavior remains green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `runner/operation_capture.py`; reusable-state support in
  `operation_calls.py` and `grading_accounting.py`; cross-task regression in
  `test_operation_capture_executor.py`; this ledger.
- **Commits:** this commit — `fix(screamingface-engine): make accounting cleanup task-safe`.
- **Gates:** focused test was RED with both production `ContextVar` token errors, then
  `test_operation_capture_executor.py`, grading-accounting and request-boundary tests passed
  (17 total); `run_gates.py screamingface-engine --skip-append-only` → ALL GATES GREEN.
- **Deviations:** the planned lifecycle refinement required the two capture context managers to
  accept their existing state objects. This keeps the state run-wide while binding and resetting
  each token within one task; no exception suppression or additional execution task was added.

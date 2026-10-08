---
ticket: OME-1451
stack: screamingface
status: done
started: 2026-10-02
finished: 2026-10-02
---

# Unidentified run root — prevent indefinite SDK waits after termination

## Intent

Raise a clear ExecutionError when the SDK cannot identify the completed run's root,
instead of waiting indefinitely while heartbeats keep its connection alive.

## Planned changes

- `packages/screamingface/src/screamingface/_engine/contract.py`: root-identification guard.
- `packages/screamingface/tests/test_cache_hit_contract.py`: recorded-stream regression.
- `packages/screamingface/tests/test_engine_contract.py`: termination statuses and replay.
- `packages/screamingface/tests/test_candidate_root_lifecycle.py`: owner-approved early-child expectations.
- Spec, plan, task mirror, and this ledger under `docs/`.

## Test plan

Replay the real fixture with matching and mismatched URL4s. Verify all four termination
statuses reject an unidentified root, sequence gaps still request replay, and existing
child lifecycle tests pass. Run the SDK's lint, format, type, test/coverage, notebook,
build, and distribution gates.

## Acceptance

The mismatched stream raises the specified ExecutionError; matching streams produce their
normal outcomes. Existing child termination and replay behavior remains covered.

## Outcome

- **Actual files:** planned files.
- **Commits:** `fix(client): reject termination without an identified run root` (this branch).
- **Gates:** regression was red (5 failed, 51 passed), then green (56 passed).
  After the approved contract update, 60 focused tests passed. The full SDK gate runner
  reported ALL GATES GREEN: lint, format, types, full tests with the 95% coverage floor,
  notebook checks, build, and distribution checks. Pre-commit hooks also passed.
- **Deviations:** records and worktree created after the initial offline reproduction;
  the existing issue supplies the approved scope. No new issue or epic was needed.
  The owner explicitly approved updating the early-child test contract on 2026-10-02.
  The append-only check is waived only for that approved change; all SDK quality gates run.

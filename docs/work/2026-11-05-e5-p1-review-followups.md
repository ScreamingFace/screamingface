---
ticket: OME-1827
stack: screamingface-engine
status: in_progress
started: 2026-11-05
finished:
---

# e5-p1-review-followups — the E5 P1 review points that belong to no open PR

## Intent

Sergio's comment on #1627 (2026-11-04) raised points after it merged. Two belong to no open PR
of the stack: the layering gate sees only direct imports, so the worker could load the database
stack one hop away through `adapters.factory`; and the E1 ledger and the `OME-1797` mirror were
left stale. This unit adds a real-import guard and closes E1's records.

## Planned changes

- `apps/screamingface-engine/tests/unit/test_worker_loads_no_database.py` (new): imports the
  worker's modules, the child it launches and `adapters.factory` in a fresh process, and asserts
  no `tortoise`, `asyncpg`, `aiosqlite` or `screamingface_engine.runs` module is loaded.
- `docs/work/2026-10-30-e5-p1-e1-run-types-state.md`: finish date, the review commit, the merge.
- `docs/tasks/2026-10-30-OME-1797-e5-p1-e1-run-types-state.md`: closed.
- Deferred from the #1648 review (point 8): answer FastAPI's request-validation 422 as an RFC
  9457 Problem (`application/problem+json`) on every Engine route, not FastAPI's `detail[]`.
  App-wide, so not in the `/runs` PR; lands here once the Engine stack is on `main`.

## Test plan

- The guard passes on `main` and on the stack's head (#1648).
- A probe that loads a stand-in `tortoise` package is caught, so the guard cannot pass vacuously.

## Acceptance

- Both tests green in CI.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** `test(engine): catch the worker loading the database stack one import away`.
- **Gates:** targeted: the new tests pass on `main` and on #1648's head; ruff and pyright clean.
  CI runs the full gates.
- **Deviations:** the self-check uses a stand-in `tortoise` package, because `main` has no
  database stack installed yet (it arrives with #1634).

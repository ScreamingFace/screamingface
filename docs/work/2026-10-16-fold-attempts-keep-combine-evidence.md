---
ticket: OME-1633
stack: screamingface-engine
status: done
started: 2026-10-16
finished: 2026-10-16
---

# fold-attempts-keep-combine-evidence — keep a Fusion's combine evidence when folding Attempts

## Intent

ARC-AGI-2 asks each grid twice. The Engine folds the two Attempts into one Case and re-checks
it. The re-check read the Case back from a field-name dump, so a judge Fusion's combine
evidence (wire key `schema`) arrived as `schema_id` and was refused: every judged Case failed
as `benchmark_unavailable`, after its answers were paid for.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/attempt_fold.py`: dump by alias in `_validated`.
- `apps/screamingface-engine/tests/unit/test_attempt_fold.py`: one regression test.

## Test plan

- RED: fold two Attempts whose operation carries judge combine evidence; it raised the prod `extra_forbidden` error on `combine.schema_id`.

## Acceptance

- The fold returns both Attempts with their combine evidence intact; existing fold tests still pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the `docs/tasks` mirror.
- **Commits:** 4a5ce85a0 — fix(screamingface-engine): keep a Fusion's combine evidence when folding Attempts
- **Gates:** `tests/unit/test_attempt_fold.py` + `tests/unit/test_case_attempts_protocol.py` 22 passed; ruff check/format and pyright clean on both touched files.
- **Deviations:** none. Owner verify: re-run ARC-AGI-2 stage 3 (judge twins) at LIMIT=2 after deploy.

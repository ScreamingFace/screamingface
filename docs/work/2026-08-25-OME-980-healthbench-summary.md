---
ticket: OME-980
stack: screamingface-engine
status: done
started: 2026-08-25
finished: 2026-08-25
---

# OME-980 — HealthBench preparation success summary

## Intent

Repair the post-preparation HealthBench CLI crash while preserving the honest
`declared_worst30_cases` audit field and every benchmark/runtime contract.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/healthbench/prepare.py`
- `apps/screamingface-engine/tests/unit/test_healthbench_prepare.py`
- This unit's task, spec, plan, and work records.

## Test plan

- RED: the family CLI receives the current summary mapping and raises the stale-key `KeyError`.
- GREEN: it returns zero and reports the professional and declared worst-30 counts.
- Run the complete `screamingface-engine` gate suite.

## Acceptance

- Successful HealthBench preparation no longer crashes while rendering its summary.
- The current summary key is pinned by a regression test.
- No asset, selection, or runtime benchmark behavior changes.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the HealthBench family preparer's CLI lookup, its focused unit test, and this
  unit's task/spec/plan/work records.
- **Commits:** `fix(screamingface-engine): repair HealthBench preparation summary`
  (`Refs: OME-980`).
- **Gates:** focused HealthBench prepare suite — 8 passed; official
  `run_gates.py screamingface-engine` — append-only, Ruff check/format, Pyright, layering, and full
  pytest/coverage all green.
- **Deviations:** none.

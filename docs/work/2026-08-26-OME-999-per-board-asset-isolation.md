---
ticket: OME-999
stack: screamingface-engine
status: in_progress
started: 2026-08-26
finished:
---

# OME-999 — Running one benchmark no longer requires every other benchmark's assets

## Intent

A dev who prepared only GDPval's assets cannot evaluate `gdpval-text`: world creation
installs every registered board, and DRACO's `install()` reads its assets EAGERLY
(`_protocol_assets(root)` at `draco/runtime.py:43`), so any run for any board demands
DRACO's `cases.json`. The lazy-install invariant is already documented in HealthBench's
install docstring and honored by IFEval, HealthBench, and GDPval — DRACO is the one
violator. Make DRACO lazy and pin the invariant registry-wide so no future board can
regress it.

## Planned changes

- `src/screamingface_engine/benchmarks/draco/runtime.py` — `install()` registers lazy
  providers: a memoized `_lazy_protocol_assets(root)` accessor shared by the cases data
  route and the aggregate handler; `available_case_count` becomes the static `CASE_COUNT`
  (the eager load validated equality anyway). Failures never cached.
- `tests/unit/test_benchmark_asset_isolation.py` — NEW: (1) installing every builtin board
  (`BUILTIN_DEPLOYMENT.benchmarks.install`) into a world over an EMPTY assets root
  succeeds; (2) resolving DRACO's cases route without its assets fails with DRACO's own
  named error; (3) DRACO reads its assets once per board across repeated resolutions.

## Test plan

- RED: registry-wide empty-root install currently raises via DRACO → test 1 fails.
- RED: with install fixed, route resolution must fail lazily with the same
  `benchmark_unavailable` message the eager path produced → test 2.
- Memo behavior: repeated cases-route resolutions read `cases.json` once → test 3.
- All existing DRACO tests stay green and unmodified — they write fixtures BEFORE
  resolving routes, so laziness is invisible to them.

## Acceptance

- `prepare gdpval` alone suffices to evaluate `gdpval-text` locally (no DRACO assets).
- Running DRACO without assets fails at DRACO's own route with its existing message.
- Both gate suites green; no prior test altered.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `benchmarks/draco/runtime.py` (lazy `_lazy_protocol_assets`
  accessor + `_cases` provider, `available_case_count=CASE_COUNT`, `_aggregate` takes the
  accessor), new `tests/unit/test_benchmark_asset_isolation.py` (3 tests), PLUS one deviation:
  two prior tests in `tests/unit/test_draco_case_evaluation_route.py` rewrote from
  install-time-atomic to resolution-time-named failures.
- **Commits:** one commit on `OME-999-per-board-assets` (sha in git log).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — ruff, format, pyright,
  layering, pytest 2,047 passing w/ coverage — ALL GREEN. The skip flag covers exactly the
  owner-approved rewrite of the two atomic-install tests; a WHY comment above them records
  the approval and the reasoning.
- **Deviations:** the two prior DRACO tests pinned the eager contract and were mutually
  exclusive with the lazy invariant — surfaced, owner approved the rewrite in plain words
  ("this is a good design … rewrite those tests"). Failure protection moved, not removed:
  a DRACO run's first touch is its cases route, so broken assets still fail before model
  spend, with the same named errors, on every resolution.

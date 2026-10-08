---
ticket: OME-1522
stack: screamingface
status: done   # planned | in_progress | done | blocked
started: 2026-10-08
finished: 2026-10-08
---

# paid-smoke-named-benchmarks — let the owner run the paid smoke on just the Benchmarks they name

## Intent

The paid smoke button picks Benchmarks only by kind (`scope`: all / imported / hand-built), so
smoking one new Benchmark pays for its whole kind — MuSiQue (#1292, origin `screamingface`)
only runs under `hand-built`, which also runs DRACO, HealthBench and GDPval with pro-tier
Judges. This unit adds an optional `benchmarks` field (comma-separated Benchmark ids): when
filled, the press runs exactly those and ignores `scope`; a name the live Engine does not list
fails the press before any paid call, printing the valid ids; empty keeps today's behaviour.
The ticket (OME-1522) is the spec; its Architecture / Failure-modes sections are the plan.

## Planned changes

- `packages/screamingface/tests/paid/_scope.py`: `NAMED_ENV`, `parse_named` (blank and stray
  commas mean unset; duplicates collapse), `pick_shelf(..., named=)` — named ids win over
  scope; unknown names become one problem line listing the valid ids.
- `packages/screamingface/tests/paid/test_scope.py`: append free tests (no prior test changed).
- `packages/screamingface/tests/paid/test_imported_board_smoke.py`: read the env var, pass it
  to `pick_shelf`, the start line says which Benchmarks were named and that scope was ignored.
- `.github/workflows/screamingface-paid-benchmark-smoke.yml`: optional free-text `benchmarks`
  input → `SCREAMINGFACE_PAID_BENCHMARKS`.
- `packages/screamingface/justfile`: `test-paid-benchmarks scope="all" benchmarks=""` → same env.

## Test plan

- RED first, free (no spend), in `test_scope.py`:
  - names win over scope: `named=["draco"]` under `imported` picks `[draco]`;
  - named picks keep the Engine's listing order and run once when named twice (F3);
  - an unknown name is a problem line naming it and listing the valid ids (F1);
  - blank / commas-and-spaces mean unset, so `scope` decides as today (F2);
  - a named press does not report an empty kind (the kind check belongs to `scope`).
- The paid press itself is the owner's (never run by the agent).

## Acceptance

- `benchmarks: musique` runs exactly one Benchmark and the start line says so (owner press).
- `benchmarks: musqiue` fails before any paid call and prints the valid ids.
- An empty field gives the same Benchmarks as today for each `scope` (prior tests unchanged).
- `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `.claude/test-change-approvals/OME-1522.json` (owner
  approval pinning the edits to the two prior paid-lane files, `_scope.py` and
  `test_imported_board_smoke.py`; no prior assertion changed).
- **Commits:** `feat(screamingface): let the paid smoke run only the Benchmarks the owner names`
- **Gates:** `run_gates.py screamingface` ALL GATES GREEN (append-only with the approval, ruff,
  pyright, pytest + coverage ≥95, notebooks, build, distribution). Free lane:
  `SCREAMINGFACE_TEST_PAID=1 pytest tests/paid tests/test_paid_lane_isolation.py` 52 passed,
  1 skipped (the paid test, no key).
- **Review follow-up (same day):** the scope error now hints `test-paid-benchmarks all <ids>`
  (just arguments are positional, so one argument lands in `scope`); `pick_from_env` moves the
  env reads + start-line wording into `_scope.py` so a free test pins the hookup the paid test
  uses. Free lane 57 passed, 1 skipped.
- **Deviations:** an unknown name still returns the known picks beside the problem line; the
  caller fails on the problem before any spend, so nothing runs either way.
- **Owner-verify:** press the button with `benchmarks: musique` (expect 1 Benchmark, start
  line `named musique (scope all ignored)`), then with `benchmarks: musqiue` (expect a failure
  before any paid call listing the valid ids).

---
ticket: OME-1273
stack: screamingface-engine
status: in_progress
started: 2026-10-01
finished:
---

# ome-1273-first-task-replay-benchmarks — import agieval, medqa and mgsm_en by Task replay

## Intent

PR 4 of the OME-1273 stack (stacked on #1191): import the first ten Task-replay Benchmarks:
eight agieval tasks, medqa and mgsm_en. Each lands with its sealed declaration, its catalogue
row, the owner's licence decision (decided 2026-10-01) and a grading test that runs with
outbound network blocked (spec R17).

## Planned changes

- `apps/screamingface-engine/tests/unit/inspect/test_inspect_imported_benchmarks.py` — the
  catalogue contract covers Task-replay declarations (Task 4.0; owner granted
  `--skip-append-only` for that one commit).
- `apps/screamingface-engine/src/screamingface_engine_inspect/upstream_templates.py` (new) —
  agieval's run-time choice template as a constant, pinned by a test against agieval's solver.
- `import_replay.py`, `importer.py` — `--choice-template module:attr`: the import child
  renders with a template constant only after checking it equals the template the Task holds.
- `prepare.py`, `benchmarks.py` — the ten generated rows, prose and licences filled.
- Tests: `test_upstream_templates.py`, `test_inspect_agieval_benchmarks.py`,
  `test_inspect_medqa_benchmark.py`, `test_inspect_mgsm_benchmark.py` (new).

## Test plan

- The template override refuses a constant that differs from the Task's template.
- Each agieval key's template constant equals what `agieval_solver` builds (no network).
- Each Benchmark: the declaration is sealed and names its task; a correct answer grades 1.0
  and a wrong one 0.0 through the real url4 routes, with `no_network`.

## Acceptance

- Ten Benchmarks in `TASK_REPLAY_CASES` + `BENCHMARKS`, each digest agreed by two replays.
- R7's licence gate green (no `TODO` licence left).
- Gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

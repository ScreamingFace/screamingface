---
ticket: OME-1273
stack: screamingface-engine
status: done
started: 2026-09-30
finished: 2026-09-30
---

# ome-1273-task-replay-image — prepare Task-replay Benchmarks and check their Case Digest

## Intent

PR 2 of OME-1273's stack (spec `docs/spec/2026-09-30-OME-1273-task-replay-import.md`, plan
`docs/plan/2026-09-30-OME-1273-task-replay-image-side.md`). At image build, a Task-replay
Imported Benchmark's Cases come from calling the eval's own task function in a child process
with empty caches (never inspect's `eval()`), and they are served only when their Case count and
Case Digest match the pinned values; otherwise the Benchmark goes SKIPPED with the reason. The
PR image job runs strict and fails on any changed Cases. Covers spec R5, R9, R10, R11, R12.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`: shared Case writer
  (`case_records`, `_write_cases`), `PreparedCase`, `case_digest`, `TaskReplayCasesSpec`,
  `TASK_REPLAY_CASES`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/task_replay.py` (new): child-process
  replay, `prepare_replayed_cases`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/benchmarks.py`: assemble either
  declaration type; `_task_replay_pins`.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/deployment.py`: `CHANGED_CASES_KEY`.
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/prepare.py`: strict mode.
- `apps/screamingface-engine/Dockerfile.benchmark`, `.github/workflows/screamingface-engine-tests.yml`:
  the strict switch (CI edit owner-approved 2026-09-30).
- Tests: `tests/unit/inspect/test_case_digest.py`, `test_task_replay.py`,
  `test_task_replay_assembly.py` (new); `tests/unit/test_benchmark_deployment.py` (appended).

## Test plan

- Case Digest pinned to a literal; moves on any written field or order change; UTF-8 on disk.
- Replay returns the task's Cases; passes task args; deterministic; a raising task, a stalled
  task (timeout) and a chatty task (stdout) are handled; the child gets its own empty caches.
- Matching digest writes Cases; changed digest, changed count and failed fetch write SKIPPED
  with the reason and no Cases.
- Assembly: pins carry task, args and digest; a key in both registries is refused; published
  revisions unchanged.
- Strict CLI lists every changed bundle and exits 1; non-strict exits 0; only the PR image job
  sets the switch; the Dockerfile forwards it.

## Acceptance

- All plan tasks green; the engine gates green; `test_published_benchmark_revision_is_byte_identical`
  unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned: `prepare.py`, `task_replay.py` (new), `benchmarks.py`,
  `deployment.py`, `benchmarks/prepare.py`, `Dockerfile.benchmark`,
  `.github/workflows/screamingface-engine-tests.yml`, and the four test files.
- **Commits:** `52359b34` shared Case writer + Case Digest; `50c68d9e` Task-replay Case
  Preparation in a child process with the digest check; `89fd3a1c` assembly and revision pins;
  `ed6883a9` strict mode for the PR image job; plus this ledger.
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only, ruff, format, pyright,
  layering, pytest with coverage ≥ 80). Unit suite 4,637 passed, 0 failed, 6 skipped.
  `test_published_benchmark_revision_is_byte_identical` unchanged.
- **Deviations:** plan Tasks 2 and 3 landed as one commit (their tests share one file).
  `test_benchmark_row_scorer_resolves_and_constructs[frontierscience]` fails when
  `test_inspect_imported_benchmarks.py` runs alone, identically on main `364f68b8`; it passes in
  the full suite (the gateway Judge provider is registered by another test's import). Not
  touched here.

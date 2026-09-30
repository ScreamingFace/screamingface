---
ticket: OME-1273
stack: screamingface-engine
status: in_progress
started: 2026-09-30
finished:
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

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

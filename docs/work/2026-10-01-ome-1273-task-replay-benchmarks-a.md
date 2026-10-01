---
ticket: OME-1273
stack: screamingface-engine
status: in_progress
started: 2026-10-01
finished:
---

# ome-1273-task-replay-benchmarks-a — import the six plain packages by Task replay

## Intent

PR 5a of the OME-1273 stack (stacked on #1194): import bbq, piqa, cybermetric (4 tasks),
worldsense, sad (5 tasks) and sevenllm's two multiple-choice tasks by Task replay, each with
the owner's license decision (2026-10-01) and a no-network grading test (spec R17).

## Planned changes

- `prepare.py`, `benchmarks.py` — the generated rows, prose, tiers and licenses filled.
- `test_inspect_task_replay_benchmarks.py` — the new keys join the grading tests.
- `test_inspect_imported_benchmarks.py`, `test_benchmark_declaration.py` — the new keys join
  the family and policy tables (owner-granted `--skip-append-only`, as on PR 4).

## Test plan

- Each Benchmark: sealed, licensed, registered; a right answer grades 1.0 and a wrong one 0.0
  under `no_network`; MCQ rows carry no check surface.

## Acceptance

- Every key in `TASK_REPLAY_CASES` with two agreeing replays; R7's license gate green; gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

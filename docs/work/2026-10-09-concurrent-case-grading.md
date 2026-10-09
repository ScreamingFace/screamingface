---
ticket: OME-1527
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-09
finished: 2026-10-09
---

# concurrent-case-grading — grade Cases concurrently in the final aggregate

## Intent

Work order #4 of OME-1527 (requirement R4). The shared marking room
(`BenchmarkAggregation.aggregate_async`) grades Cases one after another, so a judged
Benchmark on the plugin lane makes every judge call serially at the end of the run
(gdpval-text as a local Task: about 4,500). Grade Cases with a bounded number in flight,
each Case's judge calls still booked to that Case, output and progress order unchanged,
failure ladder unchanged. `iter_case_results` (the OME-932 incremental consumer) stays
serial: its contract is "a Case is graded only after the previous one was consumed".

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/shared_grading/benchmark_aggregation.py`
  — `CASE_GRADING_CONCURRENCY` constant; `aggregate_async` grades through a bounded,
  in-order task window instead of consuming `iter_case_results`.
- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py` — (added
  during GREEN, see Deviations) a judged Benchmark's aggregation opts in.
- `apps/screamingface-engine/tests/unit/test_concurrent_case_grading.py` (new) — overlap
  bound, output + progress order, failure parity with the serial path, raise parity.
- `apps/screamingface-engine/tests/unit/inspect/test_concurrent_judge_booking.py` (new) —
  each Case's judge call books to its own Case through the real scorer adapter + judge
  provider under concurrency.

## Test plan

- Overlap: a fake async hook records peak in-flight Cases; peak > 1 and ≤ the bound.
- Order: later Cases finish first; payload Cases and progress publishes keep selected order.
- Failure parity: a Case whose hook reports a failure code (and an error row) yields the
  same CaseResult as the serial `iter_case_results` path.
- Raise parity: the first raising Case in selected order is the exception that leaves the
  aggregate, and no sibling grading task is left running.
- Booking: two Cases judged at the same time each register their judge request to their
  own Case in the grading-accounting registry.

## Acceptance

- New tests green; the existing aggregation, incremental, progress, accounting and
  plugin-lane grading tests green unmodified; extra-less pyright clean on touched files.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** the three planned files plus `single_shot.py` (one constructor
  argument). `BenchmarkAggregation` gains `case_grading_concurrency` (default 1 = the
  old serial path through `iter_case_results`, unchanged); `_concurrent_case_results`
  marks up to that many Cases at once and yields in roll-call order; the plugin lane
  sets `CASE_GRADING_CONCURRENCY` (4) only when the row declares a judge.
- **Commits:** `perf(screamingface-engine): grade Cases concurrently in the aggregate`
  (single commit on `OME-1527-pr4-concurrent-case-grading`).
- **Gates:** free unit suite with the `inspect` extra: 6020 passed, 6 skipped; extra-less
  `tests/unit`: 4642 passed, 47 skipped; inspect lane alone: 1306 passed; extra-less ruff
  check + format + pyright on the four touched files: clean; layering check OK. The full
  `run_gates.py` runner was not run (unit brief: targeted free tests only); the pre-commit
  hook runs the Engine gate.
- **Deviations:**
  - Concurrency is opt-in, not universal. Making every aggregate concurrent broke the
    prior test `test_shared_aggregate_publishes_before_second_async_grade` (it pins serial
    marking for the shared path: Case 1 published before Case 2's grade starts). The
    hand-built Benchmarks' hooks only read judge work already in the row, so concurrency
    buys them nothing; they keep the exact serial path and no prior test changed.
  - Size: ~110 source lines + ~350 test lines, over the ~150 target; the booking test
    drives the real scorer adapter and judge provider, which needs its own harness.
  - Mutation-checked: replacing the task-local grading scope with a module global makes
    the booking test fail (Case 1's judge call booked to Case 2).
- **Owner-verify:** the speedup is shown as overlap in free tests, never timed. The first
  paid run of a judged Benchmark after merge (HLE or FRAMES from OME-1457, or a migrated
  rubric Benchmark) is where wall-clock and gateway queueing at 4 Cases in flight get
  seen; no paid run is owed by this PR alone.

---
ticket: OME-1833   # filed under OME-1314
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-05
finished:
---

# case-result-store — store each Case's result as it finishes, stream it into the aggregate

## Intent

MMLU-Pro (12,032 Cases) is killed with `memory_budget_exceeded`. Every Case's ~12.5 KB
`case-execution` row is held in url4's per-Case `gather` until the end (~13-20 MiB per 1k
Cases), then all rows are JSON-joined into one ~150 MB aggregate context and decoded at once
(local repro: per-Case phase 127 -> 366 MiB, aggregate peak 2,963 MiB RSS). Memory fix 2
(Kevin's proposal, approved by Sergey and Kevin 2026-11-05): the case-execution route parks
each Case's envelope in a run-scoped store and returns a ~100 B reference; the aggregate
streams envelopes back one Case at a time. Engine-side only; url4 stays generic.

Spec: `docs/spec/2026-11-05-case-result-store.md`. Plan: `docs/plan/2026-11-05-case-result-store.md`.

## Planned changes

- NEW `apps/screamingface-engine/src/screamingface_engine/benchmarks/case_result_store.py`
- `benchmarks/graded_answer.py` — route parks + returns a reference; `graded_answer` resolves one
- `benchmarks/shared_grading/case_grades.py` — per-position filing for the streamed aggregate
- `benchmarks/shared_grading/benchmark_aggregation.py` — mark one Case's row at a time
- `runner/operation_capture.py`, `runner/main.py` — one store per run, deleted with the run
- NEW tests: `tests/unit/test_case_result_store.py`, `tests/unit/test_case_result_memory.py`

## Test plan

- Store: append/read round trip, offsets, many rows, a missing key, a corrupt row (digest
  mismatch, bad JSON) -> typed `CaseResultStoreError` (fail closed), cleanup removes the dir,
  read after close fails closed, unbound store -> route stays inline (today's bytes).
- Route: with a bound store the row is a small reference and the reader resolves it to the
  same `GradedAnswer`; a grading-error envelope keeps its Candidate answer; a success row is
  stored without the duplicate `candidate_invocation`.
- Memory: stub-gateway harness, synthetic Cases at N=500 and N=2,000; per-Case peak growth
  of the per-Case phase and of the aggregate stays under a fixed bound at both sizes.

## Acceptance

- Engine gates green; repro harness at 12,032 Cases shows the per-Case slope and aggregate
  peak far below the baseline (366 MiB end of Case phase, 2,963 MiB peak).
- No public contract change: the report's shape and the SDK-visible span names are unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**

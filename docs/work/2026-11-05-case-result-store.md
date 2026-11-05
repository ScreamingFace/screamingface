---
ticket: OME-1833   # filed under OME-1314
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-11-05
finished: 2026-11-05
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

- **Actual files:** as planned, plus `runner/operation_capture.py:new_case_result_store`.
  The memory test lives in `tests/unit/inspect/test_case_result_memory.py`, because it needs
  the `inspect` extra; CI runs that lane as `uv run --extra inspect pytest tests/unit/inspect`.
- **Commits:** `052dd303d` docs (spec, plan, ledger); then the `feat(engine)` commit on
  branch `OME-1833-case-result-store`.
- **Gates:** `run_gates.py screamingface-engine --base origin/main` ALL GATES GREEN (exit 0).
  The inspect lane passed 2936 tests. url4 is untouched.
- **Measured (tracemalloc, single-model Candidate, test above):**

  | Measure | Before | After |
  |---|---|---|
  | Aggregate, KiB per Case (N=500 / N=2,000) | 91 / 92 | 14.6 / 14.3 |
  | Case phase, marginal slope, KiB per Case | 6.3 | 1.6 |

- **Measured (repro harness, 12,032 Cases, 2-member fusion, RSS):**

  | Measure | Before | After |
  |---|---|---|
  | Case phase, 2k→10k Cases | 277→378 MiB (~12.9 KiB/Case) | 210→214 MiB (~0.4 KiB/Case) |
  | Peak RSS | 2,963 MiB | 1,016 MiB |
  | End RSS | 1,821 MiB | 1,003 MiB |

- **Deviations:**
  - `benchmark_aggregation.py` was already over the 450-line cap (1,056 lines); this unit adds
    7 lines and leaves the split to its own unit.
  - The report is still built whole. That is about 800 MiB of the 1,016 MiB peak (fusion
    `operations` included). Streaming `cases` into the artifact store would make the run body
    a reference, which changes the public shape, so it is left as an owner decision (see the
    spec).

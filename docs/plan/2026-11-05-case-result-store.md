# Plan — case-result store

Spec: `docs/spec/2026-11-05-case-result-store.md`.

1. RED: `tests/unit/test_case_result_store.py`. Cover the store's round trip, offsets,
   missing and corrupt rows, and cleanup. Cover the route's reference output and the
   reader's resolution, the error row keeping its Candidate answer, and the unbound store
   staying inline.
2. RED: `tests/unit/test_case_result_memory.py`. Use the stub-gateway harness at N=500 and
   N=2,000 synthetic Cases and assert per-Case peak growth bounds for both phases.
3. GREEN: `case_result_store.py`, then the route and the reader in `graded_answer.py`, then
   per-position filing in `case_grades.py` and the streamed marking in
   `benchmark_aggregation.py`, then the per-run binding in `operation_capture.py` and
   `runner/main.py`.
4. Gates: `run_gates.py screamingface-engine --base origin/main`. Then re-run the repro
   harness at 12,032 Cases.

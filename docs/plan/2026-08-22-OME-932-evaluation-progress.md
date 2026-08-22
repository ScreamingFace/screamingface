# OME-932 — Implementation plan

Spec: `docs/spec/2026-08-22-OME-932-evaluation-progress.md`
Stack: `screamingface-engine`
Ledger: `docs/work/2026-08-21-OME-932-evaluation-progress.md`

Preconditions:

1. OME-934 is merged and its generic run-scope/Log contract is fixed.
2. `OME-932-evaluation-progress` is rebased onto the resulting `origin/main`.
3. Complete — owner approved the revised terminal-snapshot design on 2026-08-22.
4. Post-rebase URL4, identity, final-result, error, and paid-call fixtures are recorded.

Every iteration begins with failing tests; existing tests are append-only.

## Iteration 1 — exact run discovery and terminal tracker

### RED

- During run-scope setup, activate only when the rendered expression contains exactly one
  registered aggregate route with a valid literal `aggregate:N`.
- Missing, malformed, unknown, or ambiguous matches install no tracker and do not affect execution.
- Limits `1`, `10`, and full size resolve the exact adapter and total without changing URL4.
- Concurrent terminal notifications cannot cross-talk or double-count.
- Candidate exceptions contribute one failed terminal Case and re-raise identically.

### GREEN

- Add `benchmarks/progress.py` with exact run discovery, immutable adapter, strict snapshot, and
  run-local tracker.
- Wire adapters through `BenchmarkRegistry`; add no heuristic or legacy fallback.
- Notify on shared Case execution success and Candidate adapter failure.

Commit: `feat(screamingface-engine): track terminal benchmark cases`

## Iteration 2 — one projection/scorer seam per Benchmark

### RED

- Built-in Benchmarks declare aggregate route, selected Case resolver, `grade_case`, and scorer.
- Live and final paths return the same `CaseResult` from an identical raw envelope.
- Out-of-order completion is sorted into selected order before scoring.
- Refused-with-score, refused-without-score, Candidate failure, grading failure, malformed grading,
  failed-without-score, and no-gradeable-subset accounting is exact.
- Scorer exception yields null provisional score without affecting later snapshots or aggregation.

### GREEN

- Extract pure per-row conversion into one Benchmark-owned `grade_case` shared by live and final
  paths.
- Expose the existing pure scorer through the same adapter without copying arithmetic.
- Emit one complete snapshot after each newly terminal Case through OME-934.

Commit: `refactor(screamingface-engine): share case scoring with live progress`

## Iteration 3 — cross-Benchmark conformance and regressions

### RED

- Multi-Candidate Evaluations keep independent subjects, sequences, trackers, scores, and totals.
- Bridge pressure or instrumentation failure cannot prevent the final result.
- Exact final payload fixtures remain byte-identical across success, refusal, partial, grading
  failure, and Candidate failure.
- Fake gateway ledgers prove identical call count, model, prompt, and order.
- Privacy tests reject Case ids/content, rubrics, Judge reasoning, model identity, and raw errors.
- Layering tests reject Benchmark imports from generic Runner/core modules.

### GREEN

- Complete IFEval, DRACO, and HealthBench conformance fixtures.
- Preserve current errors, spans, usage, cache telemetry, cost, and final results.

Commit: `test(screamingface-engine): prove terminal progress is observational`

## Verification

After every iteration:

```text
uv run .claude/scripts/run_gates.py screamingface-engine
```

Before PR:

- run focused Benchmark, Runner seam, URL4-rendering, failure-policy, and layering tests;
- compare URL4, protocol/revision/cache identity, final payloads, and paid-call ledgers against the
  post-OME-934 baseline;
- confirm `packages/url4` and URL4 templates are unchanged;
- record commands, counts, commit SHAs, and deviations in the ledger.

## Risks

| Risk | Mitigation |
|---|---|
| Progress becomes an execution dependency | OME-934 is fail-open; no URL4 node/value wrapping; byte-identical fixtures. |
| Wrong Benchmark or total is selected | Exact registered route plus literal `aggregate:N`; zero/ambiguous matches decline. |
| Concurrent completions double-count | One run-local tracker with terminal identity de-duplication and out-of-order tests. |
| Live and final scores drift | One `grade_case` and scorer seam called by both paths. |
| UI stalls between Case completions | OME-933 continues folding existing spans, model calls, cost, usage, and cache Events. |
| Result-affecting semantics become implicit | URL4/manifest remain authoritative; tracker only observes terminal results. |

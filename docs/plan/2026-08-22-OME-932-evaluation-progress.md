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

## Iteration 4 — deepen the Benchmark Evaluation adapter

Owner approved this replacement on 2026-08-23 before OME-932 review. Because the interface is
unreleased, it has no compatibility fallback: the loose `aggregate_route` field and per-Case
`register_case_projection(..., scorer=...)` interface are replaced, not layered.

### RED

- A Benchmark declares one Evaluation adapter containing its aggregate route and bind operation.
- Exact discovery binds that adapter once to the deployment asset root and `aggregate:N` count.
- A bound adapter projects a raw terminal envelope into one selected index plus `CaseResult` and
  owns one immutable scorer for the entire run.
- All shipped Benchmarks conform through the same generic interface.
- Generic progress requires no imports or callbacks from concrete Benchmark runtime endpoints.
- Adapter bind/project/score failure remains fail-open and privacy-bounded.

### GREEN

- Add the generic Evaluation adapter and bound-run value objects beside `Benchmark`.
- Add one concrete adapter inside each IFEval, DRACO, and HealthBench module.
- Move private asset/selection binding out of route-time progress callbacks and into adapter bind.
- Remove concrete runtime progress registration and simplify the tracker to normalized indexed
  Case results from its one bound adapter.
- Keep aggregate modules as the sole owners of shared per-Case grading and cross-Case scoring.

Commit: `refactor(screamingface-engine): deepen benchmark evaluation progress`

## Iteration 5 — review hardening and redundancy cleanup

Owner approved this review-fix iteration on 2026-08-23. The URL4 discovery parser remains because
the Runner receives only the independently executable expression; no Client/job sidecar or URL4
change is introduced.

### RED

- Anonymous Candidate failures cannot prevent a later identified Case terminal from being
  recorded, and counters remain bounded by the selected total.
- A per-board projection exception records that identified Case once as failed and allows later
  Cases to continue advancing progress.
- Binding a limited run performs no full-corpus asset validation or eager per-Case asset loading.
- Syntax-derived progress snapshots do not claim, conflict with, or disable authoritative
  Benchmark-owned Logs.
- Aggregate discovery finds registered calls nested inside Iteration body, intent, and reducer
  templates.
- The shared Case endpoint passes a typed terminal outcome to the tracker without a second JSON
  decode or a lazy import cycle.

### GREEN

- Reconcile anonymous failures when an identified terminal arrives at capacity.
- Retain projection failures as failed terminal records and delete unreachable status branches.
- Make board Evaluation binding selection-only and per-Case asset access lazy where necessary.
- Separate progress publication from the recorder's generic ownership claim.
- Extract and reuse one Benchmark-aware expression traversal helper.
- Move the typed Case outcome contract below the shared endpoint and notify the recorder with that
  value.

Commit: `fix(screamingface-engine): harden live evaluation progress`

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
| A run changes scorer between Cases | One bound Evaluation owns the scorer for its full lifetime. |
| Progress leaks into concrete route handlers | Shared terminal hooks call the generic tracker; concrete runtimes register nothing. |
| UI stalls between Case completions | OME-933 continues folding existing spans, model calls, cost, usage, and cache Events. |
| Result-affecting semantics become implicit | URL4/manifest remain authoritative; tracker only observes terminal results. |

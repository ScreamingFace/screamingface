# OME-932 — Implementation plan

Spec: `docs/spec/2026-08-22-OME-932-evaluation-progress.md`
Stack: `screamingface-engine`
Ledger: `docs/work/2026-08-21-OME-932-evaluation-progress.md`

Preconditions before production code:

1. OME-931 / PR #685 is merged.
2. `OME-932-evaluation-progress` is rebased onto the resulting `origin/main`.
3. The owner explicitly approves this specification and plan in plain words.
4. The post-rebase rendered URL4 and final-result fixtures are recorded as the regression base.

The work is split into four independently green SDLC iterations. Every iteration begins with new
failing tests; existing tests are append-only.

## Iteration 1 — generic run-local structured-log capability

### RED

- A generic Engine component can emit a structured Log with scalar attributes during one run.
- Concurrent runs have isolated sinks and state.
- A missing sink is a no-op; a failing sink cannot escape the caller's fail-open boundary.
- Structured run Logs use the existing CloudEvent sequence and are evictable under the same bridge
  policy as ordinary Logs.
- The generic Runner module has no import from `screamingface_engine.benchmarks`.

### GREEN

- Add a small neutral run-context/log port under `screamingface_engine`.
- Bind one context around `url4_run` in `runner/executor.py` and map its opaque structured Log to
  the existing `LogData` frame.
- Keep `_Bridge` and `_RunState` ignorant of ScreamingFace progress schemas and Benchmark types.

Commit: `feat(screamingface-engine): expose run-scoped structured logs`

## Iteration 2 — explicit pass-through Benchmark checkpoints

### RED

- The rendered protocol contains exactly one answering, grading, and case-complete checkpoint in
  the outer iteration template.
- Rendering with limits `1`, `10`, and the full Benchmark count proves the checkpoint length delta
  is constant in the limit.
- Each endpoint returns arbitrary UTF-8 `request.context` byte-for-byte, including malformed JSON,
  while phase/count/Case identity travel only in the checkpoint intent.
- Dependency-order tests prove Candidate invocation cannot start before answering, grading cannot
  start before Candidate return, and Case completion cannot occur before the shared Case envelope.
- Failure in checkpoint validation, tracking, or emission leaves the original value and Evaluation
  result unchanged.
- Exact pre-OME-932 URL4 changes only by the approved checkpoints, serialization annotation from
  OME-931, and protocol/revision identities derived from those changes.

### GREEN

- Add `benchmarks/progress.py` with the strict snapshot value object, run-local tracker, checkpoint
  route, and generic log publication adapter.
- Make progress configuration mandatory for built-in Evaluation protocols; add no optional legacy
  branch.
- Update shared `candidate(...)` and `preserve_candidate_outcome(...)` composition to insert the
  pass-through dependencies.
- Observe an exception at the existing shared Candidate adapter, mark the active Case failed, and
  re-raise the identical exception so outer `on_error=collect` remains authoritative.
- Bump the shared Evaluation protocol revision and the affected Benchmark revisions exactly once.

Commit: `feat(screamingface-engine): add benchmark progress checkpoints`

## Iteration 3 — one Case projection and scorer seam per Benchmark

### RED

- Contract tests require every shipped Benchmark to declare exact selected order, progress route,
  `grade_case`, and scorer adapters through `BenchmarkRegistry`.
- IFEval, DRACO, HealthBench Professional, HealthBench worst-30, and every DRACO board produce the
  same `CaseResult` from live `grade_case` and final aggregation for identical raw Case envelopes.
- Prefix tests feed terminal Cases in completion order but assert scorer input remains selected
  order.
- Refused-with-score, refused-without-score, Candidate failure, grading failure, malformed grading,
  failed-without-score, and no-gradeable-prefix accounting is exact.
- Scorer exception yields a count snapshot with null provisional score and does not affect the next
  terminal Case or final aggregation.

### GREEN

- Extract pure per-row conversion from each existing aggregate module into one Benchmark-owned
  `grade_case` adapter shared by live and final paths.
- Expose the existing pure scorer through the same adapter; do not copy arithmetic into progress.
- Wire adapters via `Benchmark`/`BenchmarkRegistry`, preserving the rule that shared core imports no
  plugins.
- Emit a full snapshot after every valid phase transition and terminal Case.

Commit: `refactor(screamingface-engine): share benchmark case projection with live progress`

## Iteration 4 — finalizing, end-to-end conformance, and regressions

### RED

- Aggregate endpoint entry emits `finalizing` while retaining the latest completed counts and
  provisional projection.
- Multi-Candidate runs keep independent run subjects, sequences, trackers, scores, and totals.
- Bridge pressure may drop progress Logs without failing the Evaluation; final result still
  arrives unchanged.
- Exact final `CandidateResult` payload fixtures before and after OME-932 are byte-identical for
  successful, refused, partial, grading-failed, and Candidate-failed runs.
- Fake gateway call ledgers prove identical Candidate/Judge request count, model, prompt, and order.
- Privacy tests reject Case ids, inputs, outputs, rubrics, Judge reasoning, model identity, and raw
  errors from every progress attribute set.
- Layering tests reject concrete Benchmark imports from generic Runner and shared core modules.

### GREEN

- Hook finalizing at the existing shared aggregate endpoint entry.
- Complete cross-Benchmark end-to-end fixtures and strict attribute validation.
- Remove no old behaviour: final results, errors, spans, usage, cache telemetry, and costs continue
  through their current paths.

Commit: `test(screamingface-engine): prove live progress preserves evaluation results`

## Verification

After every iteration:

```text
uv run .claude/scripts/run_gates.py screamingface-engine
```

Before PR:

- run all focused Benchmark, Runner, URL4-rendering, failure-policy, and layering tests;
- compare rendered URL4 length deltas at limits `1`, `10`, and full size;
- compare exact final payloads and fake paid-call ledgers against the post-OME-931 baseline;
- inspect the diff to confirm `packages/url4` has no changes;
- record commands, counts, commit SHAs, and deviations in the work ledger.

## Risks

| Risk | Mitigation |
|---|---|
| A checkpoint mutates the value it observes | Byte-identity property tests over arbitrary strings and exact final-row fixtures. |
| Progress changes paid execution order | Dependency-order and fake-gateway request-ledger comparisons. |
| Generic Runner wiring learns Benchmark semantics | Import/layering test plus opaque scalar Log contract. |
| Live and final scoring drift | One extracted `grade_case` and scorer seam, called by both paths, with cross-Benchmark conformance tests. |
| A dropped Log leaves the UI stale | Full snapshots, existing sequence handling, and authoritative final-result reconciliation in OME-933. |
| Protocol revision invalidates cache entries | Intentional one-time v1 protocol change; no compatibility fallback before release. |

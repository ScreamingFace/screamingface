# Benchmark stage activity

Owner requested implementation and a draft PR on 17 September 2026. Extends the approved OME-887 activity vocabulary using the merged OME-1161 plugin.

## Behavior and rationale
Researchers need to distinguish loading cases, producing an answer, preparing grading work, checking answers/verdicts, reducing grades and aggregating a run. The endpoint implementation that owns the work declares these execution facts explicitly. Shared factories instrument their work once for every benchmark caller; registration only mounts routes. Route strings and payloads are never inspected to infer stages. Existing model-call events remain distinct from surrounding benchmark operations.

The benchmark package owns an optional stage-observation protocol and a dual synchronous/asynchronous stage scope around actual work. The execution observation registry provides generic access to its current, active run and its existing once-per-run fault guard. It imports no benchmark or activity code. The activity plugin implements the optional benchmark port and owns scopes, record schema, admission and timers. Removing the plugin and registration leaves wrappers inert.

The scope reports operation success, exception or cancellation, never a pass/fail grade inferred from returned data. Answer refusal that is encoded in a normal CandidateInvocation remains visible in model-call activity; this stage completes because the candidate adapter returned its record. No prompt, result, exception text, case/member identity or counters are added. Exact attribution is separate; occurrence IDs, node spans and genuine nested parent IDs remain available.

Sync handlers retain sync execution and start/terminal records; they cannot heartbeat while blocking the event loop. Async handlers use the existing fixed 60-second timer and joined cleanup, with all stage timers included in run cleanup. Telemetry errors cannot replace original results/errors. Empty/disabled/nested run registrations cannot inherit another run's observer. No new archive, schema, transport or deployment policy.

## Coverage
Case data providers: case_loading. Candidate adapter: answering. Rubric task builders: grading_prepare. Deterministic checks, check surfaces and verdict processors: grading_check. Criterion/rubric/attempt and case evaluation reducers: grading_reduce. Aggregate endpoints: aggregation. Imported single-shot benchmarks inherit scopes from the shared imported runtime and evaluation factories. Actual provider/judge work still emits model_call; reducer timing is not total grading wall time. Startup asset preparation, control-plane browsing and custom producers without activity declarations are not covered.

## Acceptance
Tests establish stage kind/state, unchanged results and exceptions, safe output, node attachment, off/removal semantics, concurrency, nested model parentage and async cleanup. Direct-factory tests verify emission without installer decoration; installation tests verify every declared role. Full Engine gates and independent Standards/Spec review precede the draft.

## Owner-approved revision
URL4 already provides DAG lifecycle and a structured Log sink. Neither changes here. Aggregation and case-reduction scopes belong in shared evaluation factories; rubric check scope belongs in its shared handler; candidate answering scope belongs in the candidate handler. Board-specific loading/check/prepare/reduce work scopes itself. No installer wrapper, route annotation API, guessed stage, or parallel grading pipeline. These are lifecycle records, not invented case counts or provisional scores. Sync handlers still cannot heartbeat while blocking the event loop.

Declare a whole native sync/async handler with `@reports_stage(BenchmarkStage...)`; use `with stage_scope(...)` or `async with stage_scope(...)` for a smaller work region. The decorator is not a universal adapter for synchronous functions returning awaitables; that work uses an explicit async scope. Shared factories declare once, callers do not wrap them again.

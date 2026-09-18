# Benchmark stage activity

Owner requested implementation and a draft PR on 17 September 2026. Extends the approved OME-887 activity vocabulary using the merged OME-1161 plugin.

## Behavior and rationale
Researchers need to distinguish loading cases, producing an answer, preparing grading work, checking answers/verdicts, reducing grades and aggregating a run. The endpoint implementation that owns the work declares these execution facts explicitly. Shared factories instrument their work once for every benchmark caller; registration only mounts routes. Route strings and payloads are never inspected to infer stages. Existing model-call events remain distinct from surrounding benchmark operations.

The benchmark package owns an optional stage-observation protocol and a decorator around native synchronous/asynchronous work. The execution observation registry provides generic access to its current, active run and its existing once-per-run fault guard. It imports no benchmark or activity code. The activity plugin implements the optional benchmark port and owns scopes, record schema, admission and timers. Removing the plugin and registration leaves wrappers inert.

The scope reports operation success, exception or cancellation, never a pass/fail grade inferred from returned data. Answer refusal that is encoded in a normal CandidateInvocation remains visible in model-call activity; this stage completes because the candidate adapter returned its record. No prompt, result, exception text, case/member identity or counters are added. Exact attribution is separate; occurrence IDs, node spans and genuine nested parent IDs remain available.

Sync handlers retain sync execution and start/terminal records; they cannot heartbeat while blocking the event loop. Async handlers use the existing fixed 60-second timer and joined cleanup, with all stage timers included in run cleanup. Telemetry errors cannot replace original results/errors. Empty/disabled/nested run registrations cannot inherit another run's observer. No new archive, schema, transport or deployment policy.

## Coverage
Case data providers: case_loading. Candidate adapter: answering. Rubric task builders: grading_prepare. Deterministic checks, check surfaces and verdict processors: grading_check. Criterion/rubric/attempt and case evaluation reducers: grading_reduce. Aggregate endpoints: aggregation. Imported single-shot benchmarks inherit scopes from the shared imported runtime and evaluation factories. Actual provider/judge work still emits model_call; reducer timing is not total grading wall time. Startup asset preparation, control-plane browsing and custom producers without activity declarations are not covered.

## Acceptance
Tests establish stage kind/state, unchanged results and exceptions, safe output, node attachment, off/removal semantics, concurrency, nested model parentage and async cleanup. Direct-factory tests verify emission without installer decoration; installation tests verify every declared role. Full Engine gates and independent Standards/Spec review precede the draft.

## Owner-approved revision
URL4 already provides DAG lifecycle and a structured Log sink. Neither changes here. Aggregation and case-reduction scopes belong in shared evaluation factories; rubric check scope belongs in its shared handler; candidate answering scope belongs in the candidate handler. Board-specific loading/check/prepare/reduce work scopes itself. No installer wrapper, route annotation API, guessed stage, or parallel grading pipeline. These are lifecycle records, not invented case counts or provisional scores. Sync handlers still cannot heartbeat while blocking the event loop.

Declare a whole native sync/async handler with `@observe_stage(ActivityKind...)`. All boards use the same fixed enum; there is no bespoke-stage registry or public block-scope API. Shared factories declare once, callers do not wrap them again. Sync functions returning awaitables are outside this decorator contract; awaited work must use an async def handler.

## Researcher-facing stage names
Exactly four categories: **Loading cases**, **Answering**, **Grading**, **Aggregating**. Preparation, checking and reduction all emit the same `grading` kind. There are no separate grading subkinds. Model-call/retry/heartbeat records are details within operations, not additional top-level stages. Log messages use these labels now; the future Client owns grouping/rendering. Concurrent cases can occupy different stages, so this is not a single exclusive run state.

## Single vocabulary and client verbosity
`activity_kinds.py::ActivityKind` is the one plugin-independent definition: case_loading, answering, grading, aggregation, plus model_call diagnostic detail. The duplicate BenchmarkStage enum and string conversion are removed. Producer work uses the same enum as the activity plugin. Model calls are not accepted by the benchmark decorator.

Compact/detailed Client views change presentation, not server filtering by verbosity. The Client receives emitted stage/model records subject to deployment privacy, producer rate limits and best-effort transport. This does not promise every possible fact or lossless delivery. Distinct grading operations keep their own occurrence IDs, timing and parentage but share one kind. Client rendering remains a separate task; private payloads are never justified by a detailed view.

## Case attribution wiring — 2026-09-18
Stage records inherit the explicit benchmark case scope, using the same public-ID validation as model calls. Candidate Answering observation starts only after decoding the case envelope and entering its scope. Unknown or unsafe identity remains absent; invalid identity cannot suppress the entire stage. This does not establish whole-case grading boundaries or attribute graph siblings.

## Remaining attribution — owner assigned to this PR

Owner selected #980 for the remaining Engine producer work; #988 stays focused on the existing Case identity envelope. Preserve four stage kinds and keep optional observation out of execution decisions.

Required facts: stable Case ID plus one-based position in the actual selected sequence and exact selected total; explicit model role/operation identity where the author supplies it; a grading lifecycle enclosing all work for a Case, not each individual endpoint. IDs remain distinct from positions. Corrective-loop checks inside candidate execution must remain distinguishable from the benchmark's final grading.

Selection owns position/total. Candidate/ensemble authors own operation roles. Benchmark orchestration owns grading boundaries. The activity adapter projects those facts with existing privacy/admission/fault isolation. The Client renders them without parsing prompts, routes, source names or arrival order.

Inspection constraints: model Request contains path/context/intent/params but no semantic owner. Current retained operation attribution joins URL4 source fingerprints after completion; that cannot establish exact live roles when requests are identical. URL4 query parameters are serialized without interpolating $item, so dynamic Case metadata cannot be placed in a query parameter template. Some rubric model calls resolve before their verdict handler runs; extending the verdict decorator does not scope those calls.

Role production needs a companion authoring change: explicit metadata from the Client compiler (#983), consumed by #980. An owner question is pending on including that compiler scope; Engine-only work must leave unsupported roles absent. No new URL4 grammar is proposed. Existing results, model request bytes, retrieval/seed policy, retries, accounting and cache behavior must be parity-tested before claiming equivalence.


## Scope correction — selected-case numbering only

Owner deferred model-role attribution and whole-case grading boundaries. The earlier compiler question is superseded; do not implement that expansion. #988 now owns selected-case position/count in the candidate envelope and scope. #980 forwards the validated pair on model and scoped stage activity; #983 renders it. Preserve existing privacy/off behavior, parentage and all four stages. Add pair-validation and native event tests, then run full Engine gates.

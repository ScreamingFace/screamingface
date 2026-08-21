# OME-932 — Benchmark-native live Evaluation progress

Status: APPROVED 2026-08-22. Production code remains blocked on OME-931 and rebase.

## 1. Problem

An Evaluation can run several Candidates over tens or hundreds of Cases. The Engine currently
streams URL4 spans and model-call telemetry, but those records do not state the Benchmark facts a
user needs: which Case the Candidate is answering, whether Benchmark grading has begun, how many
Cases are terminal, or the Benchmark-native score over the gradeable Cases completed so far.

Inferring those facts from model-call spans is incorrect. A Candidate Recipe may be one model, a
Fusion, a Pipeline, or a CorrectiveLoop containing its own Judge calls. Those calls are all part of
answering the Case; none establishes the boundary at which the Benchmark begins assessment.

The final `CandidateResult` already owns authoritative score and coverage. Live progress must reuse
that Benchmark authority without duplicating paid work, changing Case results, or teaching the
Client how a Benchmark scores.

## 2. Decision

The Benchmark protocol will contain three explicit pass-through progress checkpoints per Case and
one existing aggregate boundary:

```text
Cases *( answering checkpoint
         -> Candidate Recipe
         -> grading checkpoint
         -> Benchmark grading
         -> case-complete checkpoint )
      -> aggregate/finalizing
```

Each checkpoint is a relative call to a revision-pinned Benchmark `/progress` route. Its intent
carries the current Case identity, selected Case total, and phase; its context is the raw value
already flowing through the protocol. The route observes the value and returns
`request.context` unchanged. It never wraps, decodes, or reserializes the pass-through value.

This intentionally changes the rendered Benchmark URL4 and its protocol revision. The checkpoint
template appears once inside the outer iteration, so its length overhead is constant rather than
multiplied by the number of selected Cases. There is no compatibility path because Client v1 has
not shipped.

`packages/url4` remains unchanged. URL4 executes ordinary relative calls using its existing DAG,
transport, error, and observation contracts.

## 3. Ownership and module boundaries

### 3.1 Benchmark progress module

`benchmarks/progress.py` is the deep module that owns:

- the `screamingface.evaluation-progress.v1` schema;
- run-local Case lifecycle state;
- checkpoint validation and exact pass-through behaviour;
- conversion of a terminal raw Case execution into its Benchmark-owned `CaseResult`;
- selected-order provisional scoring;
- privacy filtering and fail-open publication.

Its public internal interface is small: a Benchmark declares one immutable progress adapter, and
the shared protocol calls one checkpoint constructor. Core code never imports concrete Benchmark
plugins; the existing `BenchmarkRegistry` wires their adapters.

### 3.2 Generic Runner mechanism

The Runner owns only a generic run-local context and structured-log sink. It can accept an opaque
log body plus scalar attributes and enqueue it using the same ordering and eviction policy as an
ordinary Log. It does not import `benchmarks.progress`, recognize Benchmark routes, interpret
phases, calculate scores, or construct ScreamingFace progress attributes.

The composition rule is:

```text
Benchmark semantics -> generic run-log port -> existing Runner event bridge
```

This is an Engine integration capability, not a URL4 language or executor-core feature.

### 3.3 Client boundary

OME-932 publishes strict structured Log records only. OME-933 will decode those records and render
one Candidate row. The Client never parses URL4, counts spans, reconstructs Case outcomes, or
computes a score.

## 4. URL4 protocol contract

The checkpoint calls are ordinary instrumental sources with zero weight. Their dependencies force
the semantic order; they do not contribute text to a reducer.

For one Case the protocol establishes:

1. `answering` runs before `/benchmarks/candidate` and passes the Candidate input unchanged.
2. `grading` runs only after `/benchmarks/candidate` returns and passes the complete Candidate
   invocation record unchanged.
3. `case_complete` runs only after `/benchmarks/case-execution` returns and passes the complete
   `screamingface.case-execution.v1` string unchanged.
4. `finalizing` is observed when the existing shared aggregate endpoint begins.

If Candidate invocation raises, the existing shared Candidate adapter marks the active Case as a
terminal live failure before re-raising the exact exception. The outer URL4 `on_error=collect`
continues to create the authoritative raw failure row exactly as it does today; no synthetic value
is inserted into the URL4 data path.

OME-931 serializes the outer Case iteration. Therefore `answering` for Case `n + 1` cannot begin
until Case `n` reaches its terminal checkpoint, while concurrency inside a Candidate Recipe and
inside Benchmark grading remains unchanged.

The following are regression invariants:

- checkpoint output is byte-identical to checkpoint input;
- the value received by final aggregation is byte-identical to the pre-OME-932 Case envelope;
- no Candidate, Judge, checker, or grader call is added, removed, repeated, or reordered within a
  Case;
- the final aggregate implementation receives the same ordered raw rows and produces the same
  `CandidateResult` bytes;
- only the rendered protocol, protocol revision, and resulting URL4/cache identity change.

## 5. Structured Log contract

Each snapshot is an `ai.url4.log` record on the existing sequenced CloudEvents stream.

Body:

```text
evaluation progress
```

Required scalar attributes:

| Attribute | Contract |
|---|---|
| `screamingface.event.schema` | Exact value `screamingface.evaluation-progress.v1` |
| `evaluation.phase` | `answering`, `grading`, `case_complete`, or `finalizing` |
| `cases.current` | One-based selected Case ordinal |
| `cases.total` | Fixed positive selected Case count |
| `cases.completed` | Terminal Cases observed so far |
| `cases.graded` | Terminal Cases carrying a numeric `CaseGrade.score` |
| `cases.refused` | Terminal `CaseResult.status == "refused"` count |
| `cases.failed` | Terminal `CaseResult.status == "failed"` count |
| `score.provisional` | Finite Benchmark-native number or null |
| `score.coverage` | `cases.graded / cases.total`, in `[0, 1]` |

Candidate identity and ordering come from the existing run subject and CloudEvent sequence; they
are not repeated in attributes. Unknown optional attributes may be added within v1, but every
required attribute and invariant above is strict.

The snapshot contains no Case id, input, answer, prompt, attachment, rubric, Judge explanation,
model identity, provider error, or Benchmark-private metadata.

## 6. State and accounting

Snapshots are complete state, never deltas. Replayed, duplicated, or skipped intermediate Logs
cannot double-count work.

The run-local tracker enforces:

- `cases.total` never changes;
- `cases.current` is between `1` and `cases.total` and never decreases;
- completed, graded, refused, and failed counts never decrease;
- graded, refused, and failed are each no greater than completed;
- a Case becomes completed exactly once;
- a numeric provisional score is finite;
- coverage is always derived from graded and total.

The counters intentionally overlap. A graded refusal increments both `graded` and `refused` and
participates in the score, matching the existing finalizer. A generic Candidate or grading
execution failure has no numeric grade, so it increments `completed` and `failed` without changing
`graded`, coverage, or the gradeable scoring subset. If a future valid Benchmark adapter produces
a failed Case carrying a numeric grade, the existing numeric-grade contract remains authoritative:
both `failed` and `graded` increment.

Before the first numeric grade, `score.provisional` is null. It is also null for a snapshot whose
non-authoritative scorer calculation fails; the next terminal Case performs one fresh calculation.
Progress failure never retries a model or grader and never stops the Evaluation.

## 7. Benchmark authority

Each Benchmark progress adapter declares:

- its exact revision-pinned progress and aggregate routes;
- the installed selected Case sequence;
- `grade_case(raw_case_execution, selected_case, ordinal) -> CaseResult`;
- its existing pure cross-Case scorer.

The final aggregate and live projection must call the same `grade_case` and scorer functions.
Extraction is therefore a refactor of existing IFEval, DRACO, and HealthBench logic, not a second
implementation of their semantics.

The scorer contract is computation-only, deterministic, re-entrant, prefix-safe, and free of
model, network, filesystem mutation, and paid calls. Live scoring supplies completed gradeable
`CaseResult` values in the Benchmark's selected order, never completion order. The provisional
score remains in the Benchmark's native scale and is never converted to a percentage.

A new Benchmark supplies its progress adapter through `BenchmarkRegistry`; shared core files do
not gain a benchmark-specific branch or import.

## 8. Failure and error contracts

Progress is observational and fail-open:

- malformed checkpoint intent metadata logs an internal warning and returns `request.context`;
- missing run-log context suppresses the snapshot and returns the original value;
- adapter, projection, or sink failure suppresses that snapshot and returns the original value;
- bridge pressure may evict progress exactly as it evicts ordinary Logs;
- no progress failure becomes a URL4 `ResolutionError`, public `Failure`, or Client exception;
- existing URL4, Benchmark, authentication, planning, execution, and provider errors retain their
  current types, codes, permanence, and final-result treatment.

The Client may consequently miss intermediate snapshots. OME-933 will reconcile from the final
`CandidateResult`; the returned Report remains authoritative.

## 9. Out of scope

- Any `packages/url4` grammar, AST, compiler, executor, observer, or transport change.
- A new public CloudEvent or Client Event kind.
- Client UI and decoding, owned by OME-933.
- Persisting progress into `CandidateResult`, Report, leaderboard records, or cache entries.
- Retry orchestration, new grading, or new model calls.
- Multi-turn, agentic, execution-grading, arena, or human grading semantics.
- Compatibility fallbacks for PR #649 or any unreleased progress schema.

## 10. Acceptance

1. Rendered URL4 contains explicit answering, grading, and case-complete checkpoints once inside
   the outer Case template; its length delta is bounded independently of selected Case count.
2. IFEval, DRACO, and HealthBench emit strict snapshots at the four semantic phases.
3. Case ordinals and totals are exact under OME-931's serialized outer iteration.
4. Provisional scores match the existing final scorer on every completed gradeable prefix in
   selected order.
5. Refusal, grading failure, Candidate failure, ungradeable Case, and scorer/sink failure follow
   §§6–8.
6. Checkpoint input/output, final aggregate rows, final `CandidateResult`, paid-call counts, and
   existing error contracts are regression-tested unchanged.
7. No Engine core module imports a concrete Benchmark plugin; adding a conforming Benchmark does
   not edit shared progress code.
8. `uv run .claude/scripts/run_gates.py screamingface-engine` is green.

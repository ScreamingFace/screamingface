# OME-901 — Retain evaluation accounting by operation (spec)

Status: approved after source audit, 2026-08-27. The owner approved the narrowed design and
OME-1030 implementation. Evidence:
`../work/2026-08-27-OME-901-runtime-accounting-lineage.md`.

A completed evaluation already retains an authoritative Candidate/run usage total. What it loses
is the exact join between model-call accounting and the benchmark records that name Candidate
operations, Cases, Checks, and grading Evidence. OME-901 retains that join for completed Reports.

## 0. Locked decisions

- No `packages/url4` or AI Gateway change. URL4 remains unaware of benchmarks, Candidates,
  members, synthesizers, graders, Cases, and Checks.
- Reuse the existing ScreamingFace Engine `operation_calls` capture module with two deliberately
  different task-local record shapes: Candidate-local calls retain the output needed by existing
  operation projection, while the run-local grading ledger retains only request identity and
  accounting. Do not add another queue, log seam, event type, or transport.
- Use one shared `OperationAccounting` value on the two records that already own the semantics:
  - Candidate member and synthesis accounting lives on `CaseOperation`;
  - rubric-judge accounting lives on grading `Evidence`.
- Candidate/root usage remains authoritative. The breakdown never replaces or recomputes it.
- Exact-only attribution: ambiguous or incomplete joins remain null. Never divide, duplicate, or
  infer usage from execution order.
- OME-901 covers retained completed-Report accounting. Typed live semantic events remain
  `OME-699`; failed-path evidence/accounting remains `OME-784`.
- CorrectiveLoop retains its authoritative outer total but not a nested member/judge/coach split.
  The current loop discards nested operation records when it projects each isolated invocation
  into the selected output and round metadata. OME-901 reports that work as unattributed rather
  than inventing recursive ownership.
- Reuse the Gateway's existing complete provider-attempt latency AND its attempt count. The count
  is owner-approved (2026-08-28, review of PR #762) and reverses this spec's earlier "no attempt
  counter" constraint: a client-facing Report must explain a cost, not only state it, and the
  summed latency cannot separate a slow model from a flaky route without it. It reads the same
  already-validated `usage_accounting.attempts` array the completeness gate walks, so it adds no
  Gateway read, timer, or transport. Do not add an Engine timer and
  do not populate member wall duration from provider time.
- Current-run cache semantics only: a confirmed hit has zero current provider consumption and
  cost. No avoided-cost estimate is invented.
- Bookkeeping is fail-open and payload-free in diagnostics. It never changes answers, Evidence,
  failures, scores, retries, model-call cardinality, or successful evaluation outcomes.
- Candidate Invocation/Result v1 contracts are pre-release and evolve directly. No legacy parser
  or compatibility fallback ships.

## 1. Existing boundary

The required raw facts already exist:

1. AI Gateway emits bounded attempt accounting, including usage, direct cost, cache outcome,
   provider/model identity, and provider-attempt latency.
2. ScreamingFace Engine normalizes consumed responses into generic URL4 observations.
3. The Client receives detailed generic Span/self-Usage events live.
4. The terminal Client outcome retains only root usage, while benchmark results separately retain
   Case, Check, Evidence, and Candidate-operation semantics.

Client-only reconstruction is not exact. Nested Candidate member and synthesis calls have already
folded into the outer Candidate node before the wire, and direct grading calls have no retained
Case/Check identity. The missing capability is therefore a retained Engine-side semantic join,
not another delivery channel.

## 2. Smallest architecture

### 2.1 Two payload-scoped recorders, isolated ownership

`operation_calls.py` remains the only capture module. It publishes one terminal call into whichever
task-local scopes are active, but the scopes retain different records so the run ledger never keeps
model output payloads:

```text
evaluation run
├── payload-free grading ledger: request key + accounting
│   ├── grading call
│   └── grading call
└── Candidate-local call recorder: route + output + accounting
    ├── member call
    ├── member call
    └── synthesis call
```

The Candidate adapter keeps its existing isolated output recorder and suspends the payload-free
grading ledger, so Candidate calls do not enter both scopes. A composition-root `Executor`
decorator enters the grading ledger around the existing `Url4Executor`. The generic executor
remains unchanged and benchmark-agnostic.

The scope must unwind on success, failure, cancellation, and early iterator close. Concurrent
runs receive distinct recorder state; nested DAG tasks inherit only their own run state.

### 2.2 Normalized accounting

The connector deepens the existing `OperationCall` with facts already present in the consumed
Gateway response:

```text
provider
request_model
response_model
usage: input/output/cache-read/cache-creation/reasoning tokens and USD cost
provider_latency_ms
provider_attempts
cache: hits/misses/bypasses/unknown
```

No new timer, Gateway retry mechanism, prompt, URL4 expression, cache key, Gateway id,
provider-attempt id, trace payload, or serialized request digest is added. The retained
`provider_attempts` count is derived from the existing Gateway attempt ledger that the Engine
already validates for completeness.

Field aggregation is strict:

- complete Gateway accounting with no omissions: sum every observed attempt;
- partial or omitted attempt evidence: attempt-derived fields remain null;
- no Gateway accounting: final response input/output may be retained, while unsupported token
  classes, cost, cache, and latency remain null;
- confirmed cache hit: zero current tokens, cost, and provider latency, plus one hit; `provider`
  remains the Engine's canonical provider for the declared model route because no current provider
  dispatch exists to observe;
- several tool/retry/redraw calls assigned to one semantic operation: strict field-wise sum;
- provider/response-model identity is populated only when the observed values agree.

`provider_latency_ms` is the sum of complete provider-attempt latencies. It is not Candidate,
Case, operation wall time, or critical-path duration. The UI calls it **Provider time**.

### 2.3 Candidate member and synthesis join

Deepen the existing Candidate operation-output projector. It already knows the declared operation
IDs and records the actual call path, sorted parameters, output, and finish reason.

- A unique existing path/parameter match receives `OperationAccounting`.
- Equal outputs may keep their existing output compatibility behavior, but accounting is never
  copied to several ambiguous operations.
- A solo Model gains its one natural `CaseOperation`, enabling per-Case generation accounting.
- No complete-request fingerprint is computed for Candidate calls and no explicit URL4
  operation-id parameter is introduced.
- CorrectiveLoop nested invocations remain unsupported for exact internal attribution.

### 2.4 Grading join

Grading Evidence already owns `case_id`, `check_id`, sequence, producer, verdict, explanation, and
raw judge reply. Accounting therefore belongs on Evidence rather than in parallel grading
`CaseOperation` rows.

The benchmark registers an **in-memory request key** when it authors each judge request. The
connector computes the same SHA-256 key from the actual model request and records its accounting.
The key is never serialized, logged, or exposed.

This key is the minimum exact join because many Cases use the same judge model, route, and
parameters; execution order is unsafe under redraws, retries, and concurrency. If one key maps to
more than one semantic Evidence owner, all affected accounting remains null. Several actual calls
for one unique Evidence owner are redraws/retries and aggregate into that Evidence accounting.
Accounting is reconciled once more when the complete Candidate Result is finalized, after all
grading owners have registered. This final pass revokes any provisional Evidence attribution when
a later registration made the request key ambiguous.

Boards supply their own expected request material through a shared port. Shared benchmark code
performs keying and projection without importing concrete boards.

Deterministic Evidence has `accounting=null`. A grading failure that produces no Evidence has no
retained operation accounting in OME-901; `OME-784` owns failed-path preservation.

## 3. Retained contract

One required nullable field is added to both owners:

```text
CaseOperation.accounting: OperationAccounting | null
Evidence.accounting: OperationAccounting | null
```

`OperationAccounting` contains only:

```text
provider: string | null
request_model: string | null
response_model: string | null
usage: existing strict optional six-field Usage
provider_latency_ms: integer | null
provider_attempts: non-negative integer | null
cache: {hits, misses, bypasses, unknown}
```

The sum of cache outcome counts is the number of consumed model-call responses represented by the
record. Provider retries internal to one Gateway response are not presented as extra model calls.

The Client computes views over `CaseOperation.accounting` and `Evidence.accounting`; it does not
serialize a second summary truth and never computes benchmark scores.

- Candidate stage: Candidate `CaseOperation` accounting.
- Grading stage: Evidence accounting.
- Per-Case: both owners grouped by their existing Case.
- Per-member: strict sum of uniquely attributed Candidate operations.
- `MemberResult.usage` may be populated from that projection.
- `MemberResult.duration_ms` remains null; provider latency is not wall time.

An exact unattributed **cost** remainder may be shown only when root cost and every included
attributed cost are known and disjoint. Current root token fields cannot prove equivalent
completeness, so OME-901 does not claim an exact token remainder. Negative or inconsistent cost
arithmetic disables the breakdown and emits a payload-free diagnostic; it never fails the Report.

## 4. Completed-Report UI

The completed Report may render a compact SFDS table:

```text
Operation · Stage · Model · Calls · Cache · Tokens · Cost · Provider time
```

Per-Case details remain available through expansion and the Python API. Unknown values are
explicit. The existing live evaluation widget remains unchanged.

CorrectiveLoop and any other ambiguous work appears only through the authoritative total and, when
cost arithmetic is exact, an **Unattributed** remainder. It is never assigned to a member, judge,
coach, round, or Case by inference.

## 5. Failure and privacy boundaries

- OME-901 retains calls that already survive into a successful/refused Candidate operation or
  successful grading Evidence, including redraws that feed the accepted Evidence.
- It does not intercept non-2xx/transport failures or invent a partial Report for a failed root
  run. Extending both root totals and evidence for those paths belongs to `OME-784`.
- Diagnostics name only the accounting phase and exception type. They never interpolate requests,
  prompts, URL4, parameters, outputs, request keys, or Gateway bodies.
- Run-level capture retains only in-memory request identity and accounting; it never retains model
  outputs. The Candidate-local recorder retains only the outputs required by the existing
  Candidate operation contract.

## 6. Non-regression and acceptance

1. Scores, grading outcomes, Evidence meaning, outputs, failures, URL4 rendering, cache keys,
   retries, concurrency, model-call cardinality, and root usage remain unchanged.
2. Existing live Span/Usage delivery and the live widget's cost/token/call/cache/Case-progress
   behavior remain unchanged.
3. A Model/Fusion/Pipeline plus rubric judge Report can group exact known cost by generation,
   synthesis, grading, model, and uniquely attributable Case.
4. Partial Gateway evidence, identical operations, duplicate grading requests, unpriced calls, and
   unsupported paths never become guesses or false zeros.
5. CorrectiveLoop's total remains authoritative; nested details remain unattributed and are never
   double-counted.
6. Concurrent runs, nested tasks, cancellation, and early iterator close do not leak recorder
   state.
7. The same run proves detailed generic events still reach `on_event` while terminal Report
   accounting comes only from the retained semantic projection.
8. No `packages/url4` or AI Gateway source file changes.

## 7. Explicit non-goals

- Live semantic operation events, stable execution identity, or true member wall timing
  (`OME-699`).
- Failed-path accounting/evidence or partial failed Reports (`OME-784`).
- Recursive CorrectiveLoop round/member/judge/coach attribution.
- Exact Case wall-clock duration or critical-path analysis.
- Avoided-cost estimates, provider rate cards, or prices for unpriced calls.
- Retaining prompts, URL4 expressions, request keys, cache keys, or provider/Gateway identifiers.

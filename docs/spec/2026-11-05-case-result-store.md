# Case-result store — memory fix 2 for the MMLU-Pro `memory_budget_exceeded` kill

Status: approved (Sergey + Kevin, 2026-11-05; Kevin's proposal). Ledger:
`docs/work/2026-11-05-case-result-store.md`.

## Problem

A Benchmark run is one url4 expression: a per-Case `iterate` whose body ends at
`/benchmarks/case-execution`, then one aggregate call over `$case_evaluations`.

- Every Case's case-execution row (~12.5 KB for an MMLU-Pro fusion Candidate) stays in
  `MapNode.resolve`'s `asyncio.gather` (`packages/url4/src/url4/dag/nodes/iteration.py`) until
  the last Case finishes.
- The rows are then JSON-joined into one ~150 MB aggregate context, and
  `CaseGradeReader.index` decodes and keeps every row before the first Case is marked.
- Each row carries the Candidate answer twice: `candidate_invocation`, and the same answer
  re-recorded in `grading[0].attempts[0]`.

Local repro (12,032 Cases, stub gateway): the Case phase grows from 127 to 366 MiB, and the
aggregate peaks at 2,963 MiB RSS.

## Design

1. **`CaseResultStore`** (`screamingface_engine/benchmarks/case_result_store.py`). This is an
   append-only NDJSON file in a private temp directory, with an in-memory offset index that
   maps an opaque key to (offset, length, sha256). It is bound to the run through a
   ContextVar, the same way `media_parking` binds a run's attendant.
2. **case-execution route.** It validates the envelope exactly as today. With a store bound,
   it appends the envelope and returns a reference row,
   `{"schema":"screamingface.case-execution-ref.v1","case_id":…,"key":…}` (~90 B). With no
   store bound (a test, a remote peer, a nested world), it returns today's envelope
   byte for byte.
3. **Dedup.** A stored envelope keeps `candidate_invocation` only when grading failed. That
   is the only reader of it (`grading_failure_case_result`). A graded row is read from
   `grading` alone.
4. **Readers.** `graded_answer()` is the single decoder of a case-execution row, and it
   resolves a reference through the bound store. So the aggregate, the Attempts join (its
   rows are references), and MedXpert's early `/case-result` route all work unchanged.
5. **Streamed aggregate.** `BenchmarkAggregation` stops building one index of every row. It
   validates every row first (pass 1: resolve, decode, discard), which keeps the "abort
   before any scoring" invariant. It then files and marks one position at a time (pass 2).
   Only the reference list and the finished `CaseResult`s stay in memory.

### Why local NDJSON and not the artifact store

The rows are written and read by the same Runner process within one run, and they must be
gone when the run ends. The artifact store hands results across pods, and it is
content-addressed and swept by TTL (S3 has no sweep configured). A store there would mean
12k PUT/GET round trips with 30 s timeouts, and rows left behind after the run. A local file
costs one `write` per Case and is deleted when the run closes.

## Invariants

- **Run-scoped.** Each `OperationCapturingExecutor.execute` creates one store, binds it for
  that run's steps only (the token never crosses the outward yield), and deletes it in
  `finally`, including on failure and cancellation.
- **Tenant-scoped.** Local mode runs several tenants' runs in one process, so isolation comes
  from run scoping. Each run has its own store instance and a 0700 temp directory, and a key
  resolves only through the store bound to that run. No path or key is shared between runs.
- **Durable until the report is built.** The store lives for the whole `execute`, which
  outlives the aggregate.
- **Fail closed and typed.** An unknown key, a bad digest, undecodable JSON, a closed store,
  or a reference with no store bound all raise `CaseResultStoreError` (a `ValueError`). The
  aggregate's existing contract-error path turns that into a failed run, never a quietly
  missing Case.

## Compatibility

- The report (`screamingface.candidate-result.v1`) and its delivery are unchanged. Today the
  aggregate's JSON is the run body, and `build_result` puts it inline or spills it whole to
  the artifact store (OME-892). The SDK reads either one.
- The SDK counts Cases by the `/benchmarks/case-execution` span name, and that name is
  unchanged.
- No published Benchmark expression or revision moves. Only the route's runtime output
  changes when a store is bound.

## Out of scope / owner decision

The SDK-visible run result is the report body itself. To stop the aggregate from ever holding
the full report, it would have to write `cases` to the artifact store and return a reference
as the run body. That changes the run result's shape, so per the brief this is reported and
not built.

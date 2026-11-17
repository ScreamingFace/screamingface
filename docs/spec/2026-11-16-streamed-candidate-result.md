# Streamed Candidate Result — memory fix 3 for `memory_budget_exceeded` at the end of a run

Status: draft, waiting for owner approval (2026-11-16).
Plan: `docs/plan/2026-11-16-streamed-candidate-result.md`.
Tickets: `OME-1835` (the fix), `OME-1885` and `OME-1887` (the user reports). Follows memory
fix 1 (`OME-1834`, `d21db9196`) and memory fix 2 (`OME-1833`, `7221a5c05`).

Words: the tickets say "the report". In the glossary (`CONTEXT.md`) the body of one run is a
**Candidate Result**; a Report is the record of every Candidate Result of an Evaluation. This
spec says Candidate Result.

## Problem

Large runs fail with `memory_budget_exceeded` immediately after the last Case.

- `OME-1885`: a 5-model Fusion on full MMLU-Pro (12,032 Cases) with `capture=True` peaked at
  2,926 MB. Single-model runs complete.
- `OME-1887`: large MMLU-Pro and `cross_pair` runs fail while the final result is built.
  Production blocker.
- Production (`b2e65c8c8`, engine v2.0.0+) already has fixes 1 and 2. So this is what remains.

**Who stops the run.** The worker reads the run child's process-tree RSS every 2 s
(`worker/memory_watch.py:84`). Over the per-run budget it kills the child and publishes a
permanent `memory_budget_exceeded` (`worker/supervisor.py:761`). The budget is
`runnerPool.perRunCharge.memoryLimitMi`, 2,560 MiB (`deploy/helm/values.yaml:687`).

**Why at the end.** After the last Case is marked, the run builds the whole Candidate Result
in memory, in five stages. All paths are under
`apps/screamingface-engine/src/screamingface_engine/`.

| # | Stage | Code |
|---|---|---|
| 1 | every `CaseResult` (pydantic) in a list | `benchmarks/shared_grading/benchmark_aggregation.py:329-345` |
| 2 | finalize copies | `benchmarks/aggregation.py:109-207` |
| 3 | `as_payload()` dict tree | `benchmarks/contract.py:635` |
| 4 | `compact_json` → one `str`, then url4 copies it when it substitutes `$result` | `benchmarks/grading_endpoints.py:189`, `packages/url4/src/url4/dag/semantics/ensemble.py:249` |
| 5 | `.encode("utf-8")` → bytes, written whole to the store | `runner/executor.py:681`, `artifacts/filesystem.py:51`, `artifacts/s3.py:122` |

## Measurement (2026-11-16, `main` at `4679d5c6a`)

Method: the OME-1833 harness (synthetic MMLU-Pro, stub gateway, ~1.3 KB answers, no network)
with a tracemalloc mark after each stage. Numbers are KiB per Case above the level at the
start of the aggregate. They are traced Python memory; RSS is higher.

| Stage | 1 model, N=2,000 | 5 members + synthesizer, N=1,000 | same, ONE emoji in ONE answer, N=300 |
|---|---|---|---|
| Candidate Result bytes on the wire | 3.8 | 9.9 | 9.9 |
| 1. `CaseResult` list held | 10.0 | 30.4 | 30.8 |
| 2. + finalize | 11.3 | 31.6 | 31.8 |
| 3. + dict tree | **14.3** | **39.1** | 39.2 |
| 4. `str` + url4's copy | 8.1 | 23.5 | **77.6** |
| 5. bytes + store write | 5.8 | 17.3 | 76.7 |
| held until the run ends | 2.0 | 7.3 | 37.0 |

What the numbers say:

1. **With ASCII answers the peak is 4 × the result bytes**, and the `CaseResult` list is 70 to
   78 % of it. The `str` and the bytes come after the list is freed.
2. **One wide character moves the peak to the `str`.** CPython stores a `str` at the width of
   its widest character. One emoji in one of 1,800 answers makes the whole result `str`
   4 bytes per character, and url4's `$result` substitution makes a second copy. The peak
   becomes **8 × the result bytes**. Real model answers contain such characters (arrows,
   typographic quotes, emoji), so this is the production case.
3. **The run keeps a full copy of the result until it ends.** That is the `$result` copy.
4. **This explains `OME-1885`.** At 8 × the result bytes, a 5-member Fusion with real answers
   on 12,032 Cases needs 2 to 3 GiB for the result alone. No other per-Case holder is close:
   capture keeps ~0.4 KB per call, and Candidate calls do not enter the request ledger
   (`operation_calls.py:171-177`).
5. **A result assembled one Case at a time is byte-identical** to today's
   `compact_json(as_payload())`. Checked on a real run: 120 Cases, 720 operations, with each
   Case sent through a JSON round trip to disk: 1,218,105 bytes, equal.

## Goals

- The end of a run holds O(1) full Cases in memory.
- The Candidate Result bytes do not change: same `screamingface.candidate-result.v1`, same
  keys, same order, same numbers.
- No change to the SDK, Studio, Scoreboard, any Benchmark expression or any Benchmark Revision.
  A large result arrives as today's artifact ticket (`id`, `size_bytes`, `sha256`), which the
  SDK already streams to disk and checks.

## Non-goals

- The 1 GiB result hard cap and the 512 KiB inline cap do not change.
- `OME-1675` (load only the selected Cases) stays separate.
- The MedXpert early-grade finalize (`shared_grading/incremental.py:62`, `Scoring.finish`) is not
  parked in unit 2. Its rows already arrive in memory as one array, and MedXpert is small.
- The SDK's in-memory read path and Studio's 256 MiB artifact cap stay as they are.

## Alternatives

| Option | Memory | Risk | Verdict |
|---|---|---|---|
| A. Raise the budget | none; 4 slots × limit per pod | none | An operator workaround only. |
| B. Stream the encode, keep the `CaseResult` list | removes stages 3, 4, 5 and the held copy: 77.6 → ~32 KiB per Case | low: byte-identical by construction | **Unit 1.** |
| C. B + park each `CaseResult` on disk, score on projections | flat in Case count | medium: scoring on projections, late accounting | **Unit 2**, after unit 1's numbers. |
| D. Change the wire shape (Cases as a separate artifact) | as C | high: old SDKs refuse unknown keys | Rejected. C gives the same memory with no contract change. |
| E. Write final bytes to the result during marking | as C | not possible in one pass: `score`, `coverage` and `metrics` come before `cases`, and accounting is final only after the last Case | Rejected. |

Two units, not one: each is byte-identical and measurable alone, unit 1 carries the
infrastructure risk and unit 2 the scoring risk, and unit 1 alone is expected to put the
reported runs under the budget.

## Design

```
UNIT 1                                                   UNIT 2 changes only this part
marking loop ──► list[CaseResult] ──► finalize           marking loop ──► builder.add(case)
                      │                                     ├─ park the Case's wire JSON on disk
                      ▼                                     └─ keep scoring_projection(case)
              ResultBody (head + one JSON fragment per Case)
                      │  write_result_body()
                      ▼
aggregate endpoint: spool = bound_result_spool()
  none, or inside a Candidate invocation ──► the body as one str (today)
  else ──► spool.deliver(body)           [worker thread; counts bytes]
             ≤ inline cap ──► the text                       (today's inline frame)
             ≤ hard cap  ──► artifact sink.commit() ──► a ~100 B reference
             > hard cap  ──► result_too_large                (today's error)
url4 passes the endpoint's string to the executor unchanged
build_result: spool.redeem(body) ──► ResultData(artifact=…)  (today's ticket)
              an issued reference that is not redeemed ──► result_spool_unredeemed
```

### Unit 1 — streamed delivery

1. **`ResultBody`** (new, `benchmarks/result_body.py`). A protocol with `head()` (the top-level
   payload with an empty `cases`, keys in wire order) and `case_fragments()` (each Case as
   compact JSON, in roll-call order). `write_result_body(body, write)` writes `{`, then every
   key of `head()` in order; for `cases` it writes `[`, the fragments separated by `,`, and
   `]`. `HeldResultBody` wraps a finished `CandidateResult`: its fragment is
   `compact_json(case.model_dump(by_alias=True))`. No dict tree of the whole result exists.
2. **Aggregates return the model.** `BenchmarkAggregation.aggregate_result_async` and
   `Scoring.finish_result` / `aggregate_result` return the `CandidateResult`. The old
   dict-returning methods keep their signatures and call them. Production adapters
   (`single_shot.py:1161`, `medxpert/aggregate.py:85`, `incremental_routes.py:59-80`) use the
   new methods.
3. **Artifact sink** (port change, `artifacts/ports.py`). A new protocol
   `StreamingArtifactWriter.open_sink() -> ArtifactSink` with `write(chunk)`, `commit() ->
   ResultArtifact`, `abort()`. The adapter hashes as it writes, so "the id is the sha256 of the
   content" stays inside the adapter. `ArtifactWriter` does not change, so its other users
   and test doubles do not change.
   - Filesystem: writes `.<uuid>.tmp` in the store root, then `os.replace` to the digest name
     (one filesystem; the sweeper already reaps `.tmp` leftovers, `filesystem.py:120`). An
     existing object gets `os.utime`, as a dedup hit does today.
   - S3: writes an anonymous local temp file, then one streamed `PUT` in 64 KiB chunks with
     `x-amz-content-sha256` = the digest and an explicit `Content-Length`. The signer already
     takes a payload hash. This is not chunked payload signing, so the `sigv4.py:15` limit
     holds. The store verifies the body against the signed hash.
4. **`ResultSpool`** (new, `artifacts/spool.py`). One per run, made with the run's store, inline
   cap and hard cap. `deliver(write_body) -> str`:
   - encodes each chunk to UTF-8 and counts bytes; keeps up to the inline cap in memory;
   - past the inline cap it opens a sink and moves the buffer into it;
   - past the hard cap it aborts the sink and only counts, then raises today's
     `result_too_large` with today's message;
   - at the end it asks today's `decide_result_delivery` for the verdict, so the three-way
     rule and "hard cap first" have one owner. INLINE returns the text. SPILL commits the
     sink and returns `{"schema":"screamingface.result-spool-ref.v1","key":"<32 hex, random>"}`.
   `redeem(body)` returns the `ResultArtifact` for a body that is exactly an issued reference.
   `close()` sets a stop flag that the writer checks at every chunk, and aborts an open sink.
5. **Endpoints** (`grading_endpoints.py:144-189`). A `CandidateResult` goes to the bound spool in
   `asyncio.to_thread` (the run loop keeps its heartbeats). A plain mapping, no spool, or a
   call inside a Candidate invocation (`candidate_scope.in_candidate_invocation()`) takes
   today's path. A store or disk failure is raised outside the `(OSError, ValueError)` guard,
   so it is never reported as `benchmark_unavailable`.
6. **`build_result`** (`runner/executor.py:649`) first redeems the body. A redeemed body returns
   `ResultData(artifact=…)`. If the spool issued a reference and the body is not exactly one,
   the run fails with `result_spool_unredeemed` (permanent). Every other body takes today's
   path unchanged.
7. **Binding.** `OperationCapturingExecutor.execute` makes, binds and closes the spool next to
   the Case-result store (`runner/operation_capture.py:74-110`).
8. **Evidence in production.** `log_process_memory` (`process_memory.py:58`) at the start of
   the aggregate, after marking and after delivery.

### Unit 2 — parked Cases

1. **`scoring_projection`** moves from `activity/progress.py:83` to `benchmarks/`. Two changes:
   it replaces a non-`None` `attempts` with `[]` (today it keeps every Attempt's output, grade
   and operations; scorers only test `attempts is not None`, `single_shot.py:1588`), and it
   returns its argument when that is already a projection, so the live progress and the
   builder share one object per Case.
2. **`CandidateResultBuilder`** (new, `benchmarks/result_builder.py`). `add(case)` takes each
   marked Case once. It parks the Case's wire dict (input already echoed) in the run's
   Case-result store and keeps the projection, the store key and the replay flag computed
   from the full Case. With no store bound it keeps the fragment in memory. `finish()` does
   what `finalize_candidate_result` does today, in the same order, on projections, and builds
   a light `CandidateResult` so every whole-set validator still runs once.
   `finalize_candidate_result` keeps its signature and runs on the builder, so one
   implementation orders, fills, scores and validates.
3. **`ParkedResultBody`.** For each position it reads the parked text and recomputes the
   grading accounting of each Evidence item (`accounting_for_grading_evidence`). If no value
   changes, it writes the parked text verbatim. If one changes, it sets the value and encodes
   that Case again. When no registry or ledger is bound it changes nothing, as today's
   reconcile does (`grading_accounting.py:126`). The revocation rule (`:152`) depends only on
   the registry, which is complete when marking ends.
4. **`aggregate_result_async`** uses the builder in place of the list and returns a
   `ParkedResultBody`. Unit 1's writer, spool and endpoint do not change.

## Invariants

- **Byte identity.** For the same Cases, the delivered bytes equal
  `compact_json(CandidateResult.as_payload())` of the previous code. Tested on every existing
  aggregate fixture and on generated Cases.
- **Score identity.** For every Benchmark scorer, `scorer(full Cases) == scorer(projections)`,
  for `score`, `metrics` and `scores`. Today only the live progress `score` relies on this,
  inside a guard that swallows errors, so it gets its own test.
- **One delivery rule.** `decide_result_delivery` decides inline, spill or too large for the
  held and the streamed path.
- **Run-scoped and tenant-scoped.** The spool, its temp files and the parked Cases belong to
  one run and are removed when its `execute` ends, on success, failure or cancellation. A
  reference resolves only through the spool that issued it.
- **Fail closed.** A parked Case that cannot be read raises `CaseResultStoreError`. An issued
  reference that does not come back as the run body raises `result_spool_unredeemed`.

## Behaviour change

One case changes. An expression that uses a Benchmark's aggregate output inside another
node, with a result over the inline cap, fails with `result_spool_unredeemed`. Today it works
if memory allows. No published Benchmark does this: the aggregate is the sink
(`benchmarks/protocol.py:332-345`), and the SDK's link passes it through unchanged
(`packages/screamingface/src/screamingface/_evaluation/linking.py:39-41`). Results at or under
the inline cap are never affected.

## What stays O(Cases) after both units

| Holder | Size at 12k Cases | Note |
|---|---|---|
| Case inputs, twice: url4 iterate items and `selected_cases` (`case_grades.py:336`) | 20 to 30 MB each; hundreds of MB with pictures | `OME-1675` |
| one projection per Case | ~3 KB each; more on judged Benchmarks | shared with live progress |
| inspect `kept` Scores (`single_shot.py:1159`) | 40 to 60 MB, whole-run-metric Benchmarks only | |
| capture tally | ~40 MB in capture or replay mode | |
| request ledger and grading registry | judged runs only, ~1.7 KB per judge call | |

## Disk

`/tmp` in the runner pod is a disk `emptyDir` with no size limit
(`deploy/helm/templates/deployment-runner.yaml:333`), shared by 4 slots. A run holds its
case-execution rows, its parked Cases (unit 2) and the sink's temp file: about 3 × the result
size. A 300 MB result needs about 1 GB until the run ends. Disk is not RSS. Check node
ephemeral storage before the prod rollout.

## Rollout and proof

- Unit 1, then the same measurement, then unit 2. Each unit records the stage table above,
  before and after, in its ledger.
- The existing memory test (`tests/unit/inspect/test_case_result_memory.py`) gets a Fusion
  variant and a wide-character variant, and its aggregate bound is lowered to the measured
  value plus a margin.
- In dev, the `process memory point=…` log lines show the effect on a real run.

## Open questions for the owner

1. **Ownership.** `OME-1835` and `OME-1887` are assigned to Sergey. Who takes the fix?
2. **Tickets.** Proposal: unit 1 is `OME-1835`. Unit 2 is a new leaf under `OME-1314`, filed
   when its PR opens.
3. **Fail closed** on an unredeemed reference (see "Behaviour change"). The endpoint cannot
   know that it is the run's sink, so the only other choice is not to spool at all.

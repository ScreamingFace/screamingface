# Plan — streamed Candidate Result (memory fix 3)

Spec: `docs/spec/2026-11-16-streamed-candidate-result.md`. Stack: `screamingface-engine` only.
Paths are under `apps/screamingface-engine/` unless they say otherwise; `E/` is
`src/screamingface_engine/`, `I/` is `src/screamingface_engine_inspect/`.

Two units, two PRs, in this order. Each is byte-identical to today and measured alone.
Each gets its own worktree from `origin/main`, its own ledger and its own issue at PR-open.

## Unit 0 — the measurement tool (first commit of unit 1)

- NEW `scripts/bench/report_memory.py`: the stage probe used for the spec's table. It runs the
  OME-1833 harness (synthetic MMLU-Pro, stub gateway, no network) under tracemalloc and
  prints live and peak KiB per Case after each end-of-run stage. Arguments: `single|fusion`,
  N, `--one-emoji`. It patches nothing in `src/`; it wraps the stage functions at run time.
- Record the "before" table in the ledger (the spec's numbers, run again on the unit's base).

## Unit 1 — streamed delivery

Ledger: `docs/work/2026-11-16-streamed-result-delivery.md`.

### Files

| File | Change |
|---|---|
| `E/benchmarks/result_body.py` | NEW: `ResultBody` protocol, `HeldResultBody`, `write_result_body`, `encode_result_body` |
| `E/artifacts/ports.py` | NEW protocols `ArtifactSink`, `StreamingArtifactWriter` (`ArtifactWriter` unchanged) |
| `E/artifacts/filesystem.py` | `open_sink()`: `.<uuid>.tmp` in the root, incremental sha256, `os.replace`, dedup `utime` |
| `E/artifacts/s3.py` | `open_sink()`: local temp file, then one streamed PUT; `_request` accepts an iterator body and extra headers |
| `E/artifacts/spool.py` | NEW: `ResultSpool`, `binding_result_spool`, `bound_result_spool`, `ResultSpoolError` |
| `E/benchmarks/grading_endpoints.py` | NEW `deliver_result`; both aggregate endpoints use it; adapter types accept `CandidateResult` |
| `E/benchmarks/shared_grading/benchmark_aggregation.py` | NEW `aggregate_result_async` / `aggregate_result`; old methods call them; three `log_process_memory` points |
| `E/benchmarks/shared_grading/incremental.py` | NEW `finish_result` / `aggregate_result` on `Scoring`; old methods call them |
| `E/benchmarks/shared_grading/incremental_routes.py`, `E/benchmarks/medxpert/aggregate.py`, `I/single_shot.py` | production adapters return the model |
| `E/runner/operation_capture.py`, `E/runner/main.py` | one spool per run: make, bind, close |
| `E/runner/executor.py` | `build_result(..., spool=None)` redeems first; the call site passes the bound spool |

### TDD order (RED first, then GREEN, one step at a time)

1. **Writer byte identity.** `tests/unit/test_result_body.py`: for `CandidateResult` fixtures that
   cover scored, failed and `case_result_missing` Cases, Attempts, `operations` with `decision`
   and `charges`, `abstained`, `inverted_grade` and `scores` (both set: they come after
   `cases`), an empty selection, non-ASCII and emoji text, `NaN` in `metrics`:
   `encode_result_body(HeldResultBody(r)) == compact_json(r.as_payload())`.
2. **Filesystem sink.** Content, id = sha256, `size_bytes`; dedup `utime`; temp file in the
   store root and gone after `commit` and after `abort`; no object after `abort`.
3. **S3 sink** (with `httpx.MockTransport`, as the existing S3 tests): exactly one PUT; key =
   digest; `x-amz-content-sha256` = digest; `Content-Length` present and
   `Transfer-Encoding` absent; body read in chunks; a 4xx raises `S3StorageError` and leaves
   no temp file.
4. **Spool decision parity.** For sizes around both caps (cap − 1, cap, cap + 1) and for
   inverted knobs (inline cap > hard cap), with and without a store: the spool's outcome
   equals `decide_result_delivery`. INLINE returns the exact text. SPILL returns a reference
   and one committed artifact whose sha256 and size match the bytes. TOO_LARGE raises
   `result_too_large` with today's message and leaves no artifact and no temp file.
5. **Spool references.** `redeem` of an issued reference, of an unknown one, of a plain body;
   a second run's spool refuses the first's reference; `close()` during a write stops the
   writer at the next chunk and aborts the sink; keys are random.
6. **`build_result`.** A redeemed reference → `ResultData(artifact=…)` with `media_type`; an
   issued but unredeemed reference → `result_spool_unredeemed` (permanent); no spool → today's
   three paths, unchanged tests.
7. **Endpoint.** With a spool: a small result returns its text; a large one returns a
   reference. With no spool, with a plain mapping, and inside `candidate_invocation_scope()`:
   today's string. A sink failure is not `benchmark_unavailable`; pin the code it gets.
8. **Hosted path, end to end** (`build_executor` → `lifecycle.run`, as
   `tests/unit/inspect/test_case_result_memory.py` does): with the default inline cap and with
   a small one, the terminal result decodes to the payload the old code produced, and the
   artifact's bytes equal `compact_json(as_payload())`. This also proves url4 passes the
   reference unchanged through the SDK-shaped link expression.
9. **Memory.** Add a 5-member Fusion and a one-emoji variant to
   `test_case_result_memory.py`. Lower `_AGGREGATE_KIB_PER_CASE` to the measured value plus a
   margin. Record the "after" table.

### Edge cases

- `inverted_grade` / `scores` after `cases`; `case_count` 0 → `"cases":[]`.
- A lone surrogate in an answer: today `.encode("utf-8")` fails the run in `build_result`.
  The spool fails the run at the same character; pin that the run still fails, not which line.
- Cancellation while the writer thread runs: `close()` sets the stop flag and aborts the
  sink; the thread ends at the next chunk; nothing is left in `/tmp` or the store root.
- The aggregate is called twice in one run: each call gets its own reference; only an exact
  match redeems.
- `serve --local` uses the same `build_executor`, so it gets the spool and the filesystem sink.

### Acceptance

- Engine gates green. Existing aggregate, result-delivery and e2e replay tests pass unchanged.
- Stage table after unit 1: no dict-tree, `str` or bytes stage; the peak is the `CaseResult`
  list (expected ~32 KiB per Case for the 5-member Fusion, against 77.6 with one emoji), and
  nothing result-sized is held until the run ends.

## Unit 2 — parked Cases

Starts after unit 1 merges and its numbers are recorded. Ledger:
`docs/work/<date>-parked-case-results.md`, created when the unit starts.

### Files

| File | Change |
|---|---|
| `E/benchmarks/scoring_projection.py` | NEW home of `scoring_projection`; strips `attempts` to `[]`; returns a projection unchanged |
| `E/activity/progress.py` | imports it (moved, not copied) |
| `E/benchmarks/case_result_store.py` | NEW `read_text(key)`; `read` uses it |
| `E/benchmarks/result_builder.py` | NEW: `CandidateResultBuilder`, `ParkedResultBody` |
| `E/benchmarks/aggregation.py` | `finalize_candidate_result` runs on the builder (same signature, same result) |
| `E/grading_accounting.py` | NEW `grading_accounting_bound() -> bool` (the no-op condition of today's reconcile) |
| `E/benchmarks/shared_grading/benchmark_aggregation.py` | the marking loop calls `builder.add`; `aggregate_result_async` returns the parked body |

### TDD order

1. **Score identity** (before any refactor; it must pass on today's code).
   `tests/unit/test_scoring_projection_parity.py`: for every Benchmark scorer in the catalogue
   (MedXpert `_accuracy`; inspect `_accuracy`, Named Scores columns, whole-run metrics, verdict
   counts) and Cases that cover scored, failed, abstained, Attempts and Named Scores:
   `scorer(cases) == scorer([scoring_projection(c) for c in cases])` for `score`, `metrics` and
   `scores`, under both failure policies. Then the two projection changes, each with its test:
   `attempts` becomes `[]` and never `None`; a projection of a projection is the same object.
2. **Builder equals finalize.** For the unit 1 fixtures, with and without a bound store:
   `encode_result_body(builder.finish())` equals the unit 1 bytes. Duplicate id, unselected
   id, wrong count → today's `ValueError` messages. `record_case_results` receives the same
   pairs. The light result is built from projections; a contract violation still raises.
3. **Late accounting.** With a grading registry and ledger bound: bytes equal today's
   whole-result reconcile, including a request key with two owners (revoked for both) and
   an owner registered after an earlier Case was parked. With none bound: parked text is
   written verbatim. A Case whose accounting does not change is written verbatim (assert the
   store's bytes are the fragment's bytes).
4. **Aggregate.** `aggregate_result_async` over the existing aggregate fixtures: bytes equal
   unit 1's. Existing dict-returning tests pass unchanged.
5. **Hosted path and memory.** As unit 1 steps 8 and 9. Lower the bound again. Run the
   12,032-Case repro outside CI for single model and 5-member Fusion; record peak and end RSS.

### Edge cases

- A Case marked twice → refused, as today. A Case with no row → today's `case_result_missing`
  fill, with the echoed selected input.
- No store bound (unit tests, a remote peer): fragments stay in memory; same bytes.
- A parked Case that cannot be read → `CaseResultStoreError` → the run fails (OME-1833 rule).
- `Scoring.finish` (MedXpert early grade) keeps the held path: it does not pass
  `inverted_grade` today and its rows are already in memory. Do not change either here.

### Acceptance

- Engine gates green; all existing aggregate tests unchanged.
- Aggregate growth per Case is flat between N=500 and N=2,000 and is a small multiple of one
  projection; the 12,032-Case repro peak is recorded against 1,016 MiB.

## What not to do (both units)

- Do not change the result's keys, order, separators, `ensure_ascii=False` or `NaN` handling.
- Do not use `world/streamed_json.py` (it sets `allow_nan=False`) or `encode_result`
  (`model_dump_json`, a different encoder) for the result body.
- Do not change a Benchmark expression, a route name, a Benchmark Revision, the SDK or Studio.
- Do not add multipart upload or an S3 dependency.
- Do not write the spool on the run loop from an async endpoint; use `asyncio.to_thread`.
- Do not let a disk or store failure become `benchmark_unavailable`.
- Do not keep a second finalize implementation.

## Verification

- `uv run .claude/scripts/run_gates.py screamingface-engine --base origin/main`.
- `uv run --extra inspect pytest tests/unit/inspect` (the memory test).
- `uv run --extra inspect python scripts/bench/report_memory.py fusion 1000 --one-emoji` before
  and after each unit; tables into the ledger.
- The `screamingface` stack's e2e replay lane once per unit: recorded result bytes still match.

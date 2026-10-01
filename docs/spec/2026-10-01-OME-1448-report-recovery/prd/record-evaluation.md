# PRD: Record an Evaluation while it runs

**Source:** prompt (option A) / ans:Q3, Q7, Q10, Q12 · **Priority:** P0 (data loss)
**Lifecycle:** existing (characterize + delta) · **Owner:** @ionesio

## 1. Summary and user story

As a researcher who runs `sf.evaluate` on a large Benchmark, I want the SDK to write down each
finished run before it downloads the result, so that a crash during download, decode, or export
does not lose a result I paid for. `[stated prompt]`

## 2. Background and constraints

- "At the terminal frame the SDK writes [a recovery pointer]." `[stated prompt]`
- One recover call returns the whole Evaluation, so the record describes the Evaluation, not only
  one run. `[stated ans:Q3]`
- Only finished runs are recorded. `[stated ans:Q7]`
- After a normal success, the record stays quietly as `delivered`. `[stated ans:Q10]`
- Large downloads stay parallel. This flow must not serialize them. `[stated ans:Q12]` (The user
  picked against the recommendation. The spec does not reopen it.)
- Uses: `prd/recovery-store.md` (all store invariants, the state machine, and pruning).

### 2.1 Current behavior

- `evaluate_sync` compiles, sets the answer seed on each Candidate once, runs preflight, runs the
  Candidates, and then calls `report_from_outcomes`.
  `[existing packages/screamingface/src/screamingface/_evaluation/runner.py:62]`
- The answer seed is set by `_seeded_candidates`
  `[existing packages/screamingface/src/screamingface/_evaluation/runner.py:513]`, so "the transport,
  the progress observer and the report all see the same objects" (runner.py:85).
- Up to 8 Candidates run at the same time on threads.
  `[existing packages/screamingface/src/screamingface/_evaluation/runner.py:523]`
- The transport accepts the terminal frame, and then calls `_materialize_sync` outside the socket
  scope `[existing packages/screamingface/src/screamingface/_engine/transport.py:284]` (async twin:
  `transport.py:677`). That call fetches and buffers the whole artifact.
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:1277]`
- Every `_RunOutcome` keeps its `result_body` string until all Candidates settle, and only then
  does the runner decode them. `[existing packages/screamingface/src/screamingface/_evaluation/runner.py:110]`
- The OME-1193 note says the run-transport port, "and every fake implementing it", must not
  widen. `[existing packages/screamingface/src/screamingface/_evaluation/model.py:51]` There are
  17 test files that implement `run(self, candidate, …)` fakes (grep of
  `packages/screamingface/tests`, 2026-10-01).

**Delta:**
1. The runner opens an EVALUATION_RECORD after preflight and before the first run starts.
2. The runner stamps a `recovery_slot = (evaluation_id, index)` on each Candidate, with the same
   pattern as `_with_answer_seed` (model.py:171). The port does not widen. `[proposed]`
3. The built-in transports write a RUN_RECORD when a root run succeeds, **before**
   `_materialize_*`. `[stated prompt]`
4. The runner marks the record `delivered` when it hands a Report to the caller (complete, or
   partial inside `candidates_failed`). `[stated ans:Q10]`
5. The runner decodes each Candidate as soon as it settles and drops its `result_body`. This lowers
   the peak by the total body size (2.2 GB in the incident) and changes no public behavior.
   `[proposed — gap §cross-cutting/capacity]`

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**RE-H1. A normal Recipe Evaluation leaves a delivered record.** `[stated ans:Q10]`
Given `sf.evaluate([r1, r2], benchmark="contracteval")` with the built-in transport,
When it returns a Report,
Then `<data_dir>/runs/<id>/evaluation.json` has `state: "delivered"` and two run records, and no
line is printed.

**RE-H2. The record is written before the download.** `[stated prompt]`
Given a run whose result frame carries an artifact ticket,
When the terminal frame is accepted,
Then the run record with the ticket exists on disk before the first `GET /artifacts/{id}` request
is sent.

**RE-H3. A URL4 replay is recorded too.** `[implied]`
Given `sf.evaluate("<complete url4>")`,
Then a record with `origin: "url4"` and one Candidate is written.

**RE-H4. Async parity.** `[implied]`
Given `await AsyncClient.evaluate(...)`,
Then the same records are written as in RE-H1.

### 3.2 Error paths

**RE-E1. The record cannot be written.** `[proposed — gap §per-connection/data]` · H × L
Given `<data_dir>` is read-only,
When the Evaluation opens or a run settles,
Then the Evaluation runs and returns its Report as today, and one WARNING says that recovery is
off for this Evaluation and why. A paid run never fails because of the record.

**RE-E2. Download or decode dies after the record.** `[stated prompt]` · H × H
Given a run record on disk,
When `_materialize_sync` or the decode raises `MemoryError`, or the process is killed,
Then the record stays `open` with that run record. (`prd/recover-evaluation.md` RC-E2E-1 proves
the recovery.)

**RE-E3. A Candidate fails.** `[stated ans:Q7]`
Given a run that ends `failed`, `stopped`, or `timed_out`,
Then no run record is written for it, and the other Candidates are recorded as normal.

### 3.3 Derived scenarios (risk order)

**RE-D1. The Candidate can be rebuilt from the record.** `[implied]` · H × M
Given a compiled Candidate of each kind (`model`, `fusion`, `pipeline`, `corrective_loop`,
`self_corrective`),
When the SDK rebuilds it with `_candidate_from_url4(candidate.url4)` and the stored `name` and
`answer_seed`,
Then `name`, `kind`, `models`, `url4`, `operations`, `members` and `answer_seed` equal the
compiled Candidate. If a kind fails this test, the record must store that projection explicitly
(see `erd.md` §2.3).

**RE-D2. The owner aborts.** `[proposed]` · M × M
Given Ctrl-C after 3 of 11 Candidates finished,
When `sf.evaluate` raises,
Then the record stays `open` with 3 run records. The next process can recover those 3.

**RE-D3. No Candidate succeeded.** `[proposed]` · L × M
Given every Candidate failed,
When `sf.evaluate` raises `candidates_failed` with no partial Report,
Then the SDK removes the record (nothing can be recovered).

**RE-D4. A custom transport.** `[proposed]` · L × L
Given `Client(run_transport=fake)`,
Then the SDK writes no record. Recovery covers only the built-in transports.

**RE-D5. Parallelism is unchanged.** `[stated ans:Q12]` · M × L
Given 11 Candidates with spilled results,
Then up to 8 downloads still run at the same time, as today.

**RE-D6. Early decode drops each body.** `[proposed — gap §cross-cutting/capacity]` · M × M
Given 3 Candidates that settle one after another,
When Candidate 1 settles,
Then its `CandidateResult` is decoded, and its `result_body` string is no longer referenced. The
final Report equals the one that today's code builds.

**RE-D7. Two Evaluations in one process.** `[proposed — gap §per-flow/concurrent]` · M × L
Given two `sf.evaluate` calls in two threads,
Then each gets its own `evaluation_id`, and no run record lands in the other's directory.

## 4. Non-functional requirements

- Added wall time per Evaluation: ≤ 20 ms per Candidate (RS §4). `[proposed]`
- Peak memory of `sf.evaluate` in the incident's shape drops by at least the total body size,
  because of RE-D6. `[proposed]`
- Observability: the run id and the artifact id are logged at DEBUG when the record is written.
  The ticket notes that today "nothing logs the result file id". `[stated prompt]`

## 5. Out of scope

- Serializing downloads. `[stated ans:Q12]`
- Option B (streaming decode) and option C (schema change). `[stated ans:Q1]`
- Re-attaching to runs that are still live. `[stated ans:Q7]`

## 6. Open questions

None.

## 7. TDD plan

Build outside-in from the transport hook, because the write order (record before download) is
the invariant that saves money. Characterization tests first.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RE-0a | CHAR `evaluate_sync_returns_same_report_as_today` (existing report tests stay green) | integration | §2.1 | — | none |
| RE-0b | CHAR `up_to_eight_candidates_materialize_concurrently` | integration | RE-D5 | — | none |
| RE-1 | `candidate_rebuilt_from_url4_equals_compiled_candidate` (parametrized over every kind) | unit | RE-D1 | H×M | uses `_candidate_from_url4`; on failure, widen the record |
| RE-2 | `run_record_is_on_disk_before_first_artifact_request` (httpx MockTransport asserts the file exists when `/artifacts/` is hit) | integration | RE-H2 | H×H | hook after `_run_connected`, before `_materialize_sync` |
| RE-3 | `record_survives_memory_error_in_materialize` | integration | RE-E2 | H×H | the record write precedes the fetch |
| RE-4 | `unwritable_data_dir_still_returns_report_and_warns_once` | integration | RE-E1 | H×L | catch `RecoveryStoreUnavailable` |
| RE-5 | `async_transport_records_before_materialize` | integration | RE-H4 | H×M | mirror in `transport.py:677` |
| RE-6 | `successful_evaluate_marks_record_delivered_without_output` | integration | RE-H1 | M×H | `mark_delivered` after `report_from_outcomes` |
| RE-7 | `partial_report_marks_delivered_and_failed_candidate_has_no_run_record` | integration | RE-E3 | M×M | mark in the `candidates_failed` path |
| RE-8 | `early_decode_drops_result_body_and_report_is_unchanged` (weakref on the body) | unit | RE-D6 | M×M | decode via `on_complete` |
| RE-9 | `ctrl_c_leaves_record_open_with_finished_runs` | integration | RE-D2 | M×M | no mark on abort |
| RE-10 | `all_failed_evaluation_removes_its_record` | integration | RE-D3 | L×M | `remove` |
| RE-11 | `url4_replay_writes_single_candidate_record` | integration | RE-H3 | M×M | open in `evaluate_url4_*` |
| RE-12 | `two_concurrent_evaluations_keep_separate_records` | integration | RE-D7 | M×L | slot carries the id |
| RE-13 | `custom_run_transport_writes_no_record` | unit | RE-D4 | L×L | store only for the built-in transports |

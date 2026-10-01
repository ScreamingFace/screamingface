# PRD: Recovery store (component)

**Source:** prompt (OME-1448 option A) / ans:Q3, Q4, Q6, Q10 · **Priority:** P0 (data loss)
**Lifecycle:** planned · **Owner:** @ionesio

## 1. Summary and flows served

The recovery store keeps a small, durable record of each Evaluation and of each finished run on
the researcher's disk. It is the "recovery pointer" of option A. `[stated prompt]`

It serves these flows:
- `prd/record-evaluation.md`: writes the records.
- `prd/recover-evaluation.md`: reads the records and removes them.
- `prd/recovery-notice.md`: scans and prunes the records.

This PRD owns the store's invariants: layout, atomic writes, permissions, validation, the state
machine, and pruning. The flow PRDs do not repeat them.

## 2. Background and constraints

- "At the terminal frame the SDK writes `~/.screamingface/runs/<run_id>.json` holding engine URL,
  Candidate name, result file id, size, sha256." `[stated prompt]` This spec keeps the location
  and changes the key from `run_id` to `evaluation_id`, because one recover call must return the
  whole Evaluation. `[stated ans:Q3]`
- "Until recovered or expired." `[stated ans:Q4]` A successful recover counts as delivered, not
  as a deletion. `[stated ans:Q13]`
- "Pointer only": the store never holds result bytes that the Engine spilled. `[stated ans:Q6]`
- "Keep quietly": a delivered record stays without a notice, and is deleted when the server copy
  is confirmed gone or after 7 days. `[stated ans:Q10]`
- Hexagonal rule: the core defines ports, and adapters implement them (CLAUDE.md). The port lives
  in `_core/ports.py`, next to `SyncRunTransport`
  `[existing packages/screamingface/src/screamingface/_core/ports.py:103]`. The filesystem
  adapter lives in a new `screamingface/_recovery/` package. `[proposed]`
- Entities, layout, and the state table: `erd.md` §2.

### 2.1 Current behavior

- The SDK writes nothing to disk during `sf.evaluate`. `[existing packages/screamingface/src/screamingface/_evaluation/runner.py:62]`
- No log line carries the artifact id. `[stated prompt]` (checked: no log call in
  `_engine/transport.py`, `runner/executor.py`, or `artifacts/`.)
- `<data_dir>` exists for the local runtime: `runtime.json`, `runtime.log`, and the SQLite files
  `[existing packages/screamingface/src/screamingface/_runtime/config.py:44]`.

**Delta:** add the `RecoveryStore` port, the filesystem adapter, and `<data_dir>/runs/`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**RS-H1. Open an Evaluation.** `[stated ans:Q3]`
Given a writable `<data_dir>`,
When the runner calls `open_evaluation(manifest)`,
Then `<data_dir>/runs/<evaluation_id>/evaluation.json` exists with `state: "open"`, mode `0600`,
and its directory has mode `0700`.

**RS-H2. Record a finished run.** `[stated prompt]`
Given an open Evaluation,
When the transport calls `record_run(slot, outcome)` for a `succeeded` outcome with an artifact
ticket,
Then `runs/<index>.json` holds the ticket `id`, `size_bytes`, `sha256`, and every `_RunOutcome`
field except `result_body`.

**RS-H3. Record an inline result.** `[implied]`
Given an outcome with an inline `result_body` and no ticket,
When `record_run` runs,
Then the record holds `{"kind":"inline","body":…}` with the exact body text.

**RS-H4. Mark delivered.** `[stated ans:Q10]`
Given an open Evaluation,
When the runner calls `mark_delivered(evaluation_id)`,
Then `state` is `delivered` and `delivered_at` is set. A second call changes nothing.

**RS-H5. Load for recovery.** `[stated ans:Q3]`
Given an Evaluation with records,
When `load(evaluation_id)` runs,
Then it returns the manifest and the run records, each validated, in Candidate order.

### 3.2 Error paths

**RS-E1. Unwritable data dir.** `[proposed — gap §per-connection/data]` · Impact H × Likelihood L
Given `<data_dir>` is read-only or the disk is full,
When `open_evaluation` or `record_run` fails with `OSError`,
Then the store raises `RecoveryStoreUnavailable`, and the caller continues the Evaluation without
a record (see RE-E1). The store never leaves a partial file under a final name.

**RS-E2. Unknown evaluation id.** `[implied]`
Given no directory for `ev_…`,
When `load` runs,
Then it raises `ExecutionError(code="recovery_not_found")`, and the message names the id.

**RS-E3. Malformed id.** `[proposed — gap §cross-cutting/security]` · H × L
Given an id that does not match `^ev_[0-9a-f]{32}$` (for example `../x`),
When any store call receives it,
Then the store raises `ValueError` before it touches the filesystem.

### 3.3 Derived scenarios (risk order)

**RS-D1. A crash during a write never tears a record.** `[proposed — gap §per-connection/data]` · H × M
Given a write that dies between the temporary-file write and `os.replace`,
When a later process loads the Evaluation,
Then it sees the previous complete file, or no file. It never sees a truncated final file.
Stale `.tmp` files older than 1 hour are removed during a scan.

**RS-D2. Eight Candidates settle at the same time.** `[proposed — gap §per-flow/concurrent]` · H × M
Given 8 threads that call `record_run` for different indexes at the same moment,
When all calls return,
Then 8 complete records exist, and no record has another index's data.

**RS-D3. A record file is tampered with or corrupt.** `[proposed — gap §cross-cutting/security]` · H × L
Given a record that is not valid JSON, is larger than 2 MiB, has a wrong type, has an
`engine_url` that is not `https` and not loopback `http`, or has an artifact id that is not 64
lowercase hex characters,
When `load` reads it,
Then it raises `ExecutionError(code="recovery_record_invalid")`, names the file, and does not send
any request.

**RS-D4. Unknown schema version.** `[proposed]` · M × L
Given `schema: "screamingface.recovery.evaluation.v2"`,
When `load` runs, Then it raises `recovery_record_unsupported`.
When a scan or prune runs, Then the record is skipped and never deleted.

**RS-D5. The owner is alive.** `[proposed — gap §per-flow/concurrent]` · M × M
Given an `open` record whose `owner.hostname` is this host and whose `owner.pid` is alive,
When the store classifies it,
Then the view is `in_progress`.
Known limit: if the OS reuses a pid, the store can report a crashed Evaluation as
`in_progress`. The record stays loadable with `sf.recover(id)`. `[proposed]`

**RS-D6. Prune delivered records after 7 days.** `[stated ans:Q10]` · L × H
Given a `delivered` record with `delivered_at` 7 days and 1 second ago,
When a scan runs, Then the Evaluation directory is removed.
Given 6 days and 23 hours, Then it stays.

**RS-D7. Prune empty crashed records.** `[proposed]` · L × M
Given an `open` record whose owner is not alive and that has no run records,
When a scan runs, Then the directory is removed.

**RS-D8. Remove an Evaluation.** `[stated ans:Q4]` · M × M
Given two processes that remove the same Evaluation at the same time,
When both call `remove(evaluation_id)`,
Then both return without an error, and the directory is gone. A reader sees the whole directory
or nothing.

**RS-D9. Values round-trip exactly.** `[implied]` · H × M
Given any `_RunOutcome` that the contract layer can build (decimals with many digits, null usage,
`cache_hits` 0, timezone-aware times),
When the store writes and then loads it,
Then the loaded outcome equals the original field by field.

**RS-D10. Permissions.** `[proposed — gap §cross-cutting/security]` · M × L
Given a umask of `022`,
When the store creates files and directories,
Then files are `0600` and directories are `0700`.

**Empty state:** RS-H1 covers the first run, where `<data_dir>/runs/` does not yet exist.
**Repeat:** RS-H4 and RS-D8 cover idempotency.

## 4. Non-functional requirements

- `record_run` takes ≤ 20 ms at p99 on a laptop SSD, `fsync` included. It runs once per
  Candidate, at the end of a run that took hours. `[proposed]`
- The scan of 200 Evaluation directories takes ≤ 50 ms and reads only `evaluation.json` and
  directory listings. `[proposed]`
- Disk: about 5 KB per Evaluation, plus at most 512 KiB for each inline result. `[proposed]`
- Observability: each `RecoveryStoreUnavailable` logs one WARNING per Evaluation on the
  `screamingface` logger, with the path and the `errno` name. A DEBUG line logs each
  `record_run` with the run id and the artifact id. `[proposed]`
- Security: the store never logs a result body. It never stores a token. `[proposed]`

## 5. Out of scope

- Storing result bytes (`[stated ans:Q6]`).
- A cross-machine record sync or export. `[proposed]`
- The E5 runs/history API. It can wrap this store later. `[stated ans:Q2]`

## 6. Open questions

None. OQ-1 is resolved: a successful recover marks the record `delivered` and restarts the 7-day
clock. It does not delete the record. `[stated ans:Q13]` A record is deleted only when the server
copy is confirmed gone, or by the 7-day prune.

## 7. TDD plan

Build core-out: the store first, because every flow depends on its invariants. Order follows
risk. RED first for every row; each test must fail on the missing behavior, not on an import
error.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RS-1 | `record_survives_crash_between_tmp_write_and_replace` | unit | RS-D1 | H×M | tmp + fsync + `os.replace`; patch `os.replace` to raise |
| RS-2 | `concurrent_record_run_for_eight_indexes_keeps_each_record_intact` | unit | RS-D2 | H×M | one file per index; ThreadPoolExecutor(8) |
| RS-3 | `run_outcome_round_trips_field_by_field` (property: hypothesis over decimals/None/datetimes) | unit | RS-D9 | H×M | explicit codec; decimals as text |
| RS-4 | `tampered_record_is_refused_before_any_request` (parametrized: bad JSON, >2 MiB, bad id, `http://evil` engine) | unit | RS-D3 | H×L | strict decoder; reuse the `_require_secure_connection_origin` rule |
| RS-5 | `malformed_evaluation_id_never_touches_the_filesystem` | unit | RS-E3 | H×L | regex check first |
| RS-6 | `unwritable_data_dir_raises_store_unavailable_and_leaves_no_final_file` | unit | RS-E1 | H×L | map `OSError` |
| RS-7 | `open_evaluation_writes_open_manifest_with_private_modes` | unit | RS-H1, RS-D10 | M×H | `os.open(..., 0o600)`; `mkdir(mode=0o700)` |
| RS-8 | `artifact_outcome_is_recorded_without_body` | unit | RS-H2 | H×H | `result.kind = artifact` |
| RS-9 | `inline_outcome_is_recorded_with_exact_body` | unit | RS-H3 | M×M | `result.kind = inline` |
| RS-10 | `mark_delivered_is_idempotent` | unit | RS-H4 | M×H | rewrite manifest |
| RS-11 | `load_returns_runs_in_candidate_order` | unit | RS-H5 | M×H | sort by index |
| RS-12 | `load_unknown_id_raises_recovery_not_found` | unit | RS-E2 | M×M | — |
| RS-13 | `unknown_schema_is_refused_by_load_and_skipped_by_prune` | unit | RS-D4 | M×L | version gate |
| RS-14 | `live_owner_on_this_host_classifies_as_in_progress` | unit | RS-D5 | M×M | `os.kill(pid, 0)` behind a seam |
| RS-15 | `concurrent_remove_is_idempotent_and_atomic` | unit | RS-D8 | M×M | rename to trash, then rmtree |
| RS-16 | `delivered_record_is_pruned_after_seven_days_not_before` (boundary: 7d−1s, 7d+1s; injected clock) | unit | RS-D6 | L×H | clock seam |
| RS-17 | `empty_crashed_record_is_pruned` | unit | RS-D7 | L×M | — |
| RS-18 | `stale_tmp_files_older_than_an_hour_are_swept` | unit | RS-D1 | L×M | — |
| RS-19 | `record_run_p99_under_20ms` (benchmark marker, not a gate) | unit | §4 | L×L | — |

Refactor on green: keep the codec in one module (`_recovery/codec.py`), so the store and the
recover flow share one decoder.

# PRD: Recover an Evaluation

**Source:** prompt (option A) / ans:Q2, Q3, Q4, Q7, Q8, Q9, Q11, Q13 · **Priority:** P0 (data loss)
**Lifecycle:** planned · **Owner:** @ionesio

## 1. Summary and user story

As a researcher whose notebook died after an Evaluation finished, I want one call that returns
the same Report, or writes the same `report.json`, so that I keep the results I paid for and do
not run the Evaluation again. `[stated prompt]`, `[stated ans:Q3]`

## 2. Background and constraints

- "A notebook that dies at ⑤ or ⑥ can be followed by one SDK call that returns the same
  `Report`, on local and on hosted." `[stated prompt]` (ticket acceptance 1)
- Public surface: a standalone `sf.recover(...)` and a `screamingface recover` CLI that the
  future E5 runs API can wrap. `[stated ans:Q2]`
- One call covers the whole Evaluation. Single runs stay addressable. `[stated ans:Q3]`
- A successful recover marks the record `delivered` and restarts its 7-day clock. The record is
  removed only when the server copy is confirmed gone, or by the 7-day prune. `[stated ans:Q4]`,
  `[stated ans:Q13]`
- A Candidate that did not finish is named as failed, as in a partial Report. `[stated ans:Q7]`
- A 404 reads as "expired or not found", with the age. No infra change. `[stated ans:Q8]`
- Recover-to-file keeps memory bounded by one Candidate. In-memory recover stays.
  `[stated ans:Q9]`
- If the local stack is down, give a clear error and start nothing. `[stated ans:Q11]`
- "The SDK says 'expired' with the file's age when the pointer's file is gone, never a bare 404."
  `[stated prompt]` (ticket acceptance 4)
- Uses: `prd/recovery-store.md` (load, validation, removal) and `prd/report-json-writer.md`.

**Reused code (do not copy it):**
- `_materialize_sync` / `_materialize_async`: a fresh token, retries, size and sha256 checks.
  `[existing packages/screamingface/src/screamingface/_engine/transport.py:1299]`
- `_candidate_from_url4`: rebuilds the Candidate projection.
  `[existing packages/screamingface/src/screamingface/_evaluation/url4.py:109]`
- `_compiled_evaluation` and `report_from_outcomes` / `_candidate_result`.
  `[existing packages/screamingface/src/screamingface/_evaluation/model.py:249]`,
  `[existing packages/screamingface/src/screamingface/_evaluation/results.py:75]`
- `raise_candidates_failed`: the partial-Report error shape.
  `[existing packages/screamingface/src/screamingface/_evaluation/outcome.py:65]`

## 3. Public surface `[proposed]`

```python
# screamingface/__init__.py (through _default_client.py) and Client / AsyncClient
@overload
def recover(evaluation_id: str, *, to: None = None) -> Report: ...
@overload
def recover(evaluation_id: str, *, to: str | PathLike[str]) -> Path: ...
```

```
screamingface recover --list [--all]
screamingface recover <evaluation_id> [--to PATH]     # PATH default: ./report-<evaluation_id>.json
exit codes: 0 complete · 2 partial (file written, some Candidates failed) · 1 error, no file
```

The CLI always writes a file (recover-to-file), so it never builds the whole Report.
`[stated ans:Q9]` `--list` is specified in `prd/recovery-notice.md`.

## 4. Scenarios and acceptance criteria

### 4.1 Happy path

**RC-H1. In-memory recovery returns the same Report.** `[stated prompt]`
Given a `recoverable` Evaluation with 11 run records whose artifacts still exist,
When the researcher calls `sf.recover("ev_…")`,
Then the returned Report is equal to the Report that `sf.evaluate` would have returned, and
`report.export()` writes the same bytes.

**RC-H2. Recover-to-file writes the same bytes.** `[stated ans:Q9]`
Given the same Evaluation,
When the researcher calls `sf.recover("ev_…", to="report.json")`,
Then `report.json` holds exactly the bytes of RC-H1's `report.export()`, and the call returns the
path.

**RC-H3. The original Engine is used.** `[implied]`
Given a record with `engine_url` A, while the default client points at Engine B,
When `sf.recover` runs,
Then every request goes to A. A Client that the call made for A is closed before it returns.

**RC-H4. The record is kept as delivered after success.** `[stated ans:Q13]`
Given RC-H1 or RC-H2 completed,
Then `state` is `delivered` and `delivered_at` is the time of the recover. No notice names it
again, and a second `sf.recover` still works for 7 days.

**RC-H5. Hosted recovery.** `[stated prompt]`
Given a record for `https://fusion.dev.screamingface.ai` and a logged-in Access session,
When `sf.recover` runs,
Then the SDK mints a fresh capability token for each fetch and rebuilds the Report.

### 4.2 Error paths

**RC-E1. Every artifact has expired.** `[stated ans:Q8]` · H × M
Given a local record that finished 3 days ago, whose artifacts return 404,
When `sf.recover` runs,
Then it raises `ExecutionError(code="result_expired")`. The message names the Engine and says
"finished 3 days ago; local results are kept 48 hours". The record is removed.

**RC-E2. The local stack is not running.** `[stated ans:Q11]` · M × H
Given a record for `http://127.0.0.1:9108`, and nothing listens there,
When `sf.recover` runs,
Then it raises `ExecutionError(code="local_stack_not_running")` with the hint "start the local
stack with `screamingface up`, then recover again". The record stays, and nothing is started.

**RC-E3. Unknown id.** `[implied]`
Given no record for the id, Then `recovery_not_found` (RS-E2), and the hint names
`screamingface recover --list`.

**RC-E4. Not logged in (hosted).** `[implied]` · M × M
Given a record for a hosted Engine and no Access session,
When the token mint is refused,
Then the existing Access login error reaches the caller, and the record stays.

**RC-E5. The bytes do not match.** `[existing packages/screamingface/src/screamingface/_engine/transport.py:1237]` · H × L
Given an artifact whose size or sha256 differs from the record,
Then `result_integrity_mismatch` (permanent), and the record stays.

### 4.3 Derived scenarios (risk order)

**RC-D1. Some Candidates did not finish.** `[stated ans:Q7]` · H × H
Given a record with 8 of 11 run records and a dead owner,
When `sf.recover` runs,
Then it raises `ExecutionError(code="candidates_failed")`. The error carries a partial Report of
the 8, and names the 3 missing Candidates with the code `not_finished`. In file mode, the partial
file is written, `details["path"]` names it, and the CLI exits with 2. The record is marked `delivered`. `[stated ans:Q13]`

**RC-D2. Some artifacts have expired.** `[proposed]` · H × L
Given 2 of 11 artifacts return 404,
Then the result is like RC-D1, with the code `result_expired` for those 2, and the record is
marked `delivered`. `[stated ans:Q13]`

**RC-D3. The owner is still alive.** `[proposed — gap §per-flow/concurrent]` · M × M
Given an `in_progress` record (another notebook is still running it),
When `sf.recover` runs,
Then it rebuilds only the finished runs, names the others as `not_finished`, and does not change
or remove the record.

**RC-D4. A transient network error.** `[proposed — gap §per-connection/sync]` · M × M
Given the fetch fails after the existing retries (`_ARTIFACT_FETCH_RETRY_DELAYS`,
transport.py:1265),
Then `EngineUnavailableError` reaches the caller. The record stays, and no partial file is left at
`to`.

**RC-D5. A crash during recover-to-file.** `[proposed — gap §per-connection/data]` · H × L
Given the process dies while Candidate 6 of 11 is written,
Then `to` is not created (or the old file there is unchanged). The record stays, and the
`tmp/` staging file is swept by the next scan (RS-D1).

**RC-D6. Disk full during recover-to-file.** `[proposed — gap §per-connection/data]` · M × L
Given `ENOSPC` while it stages an artifact or writes the output,
Then `ExecutionError(code="recovery_disk_full")` names the needed size. The staging files are
removed, and the record stays.

**RC-D7. Two recovers at the same time.** `[proposed — gap §per-flow/concurrent]` · L × L
Given two processes that recover the same id,
Then both succeed, each with its own staging names, and removal is idempotent (RS-D8).

**RC-D8. Memory bound in file mode.** `[stated ans:Q9]` · H × M
Given 11 Candidates of equal size S,
When recover-to-file runs,
Then peak traced memory is ≤ 1.5 × (decoded size of one Candidate) + 64 MiB. It does not grow
with the Candidate count.

**RC-D9. Inline results.** `[implied]` · M × M
Given run records with inline bodies (results ≤ 512 KiB),
Then recovery sends no artifact request for them and decodes the stored body.

**RC-D10. A delivered record.** `[stated ans:Q10]` · M × M
Given a `delivered` record (the kernel died after `sf.evaluate` returned),
Then `sf.recover` works the same as for an `open` record.

**RC-D11. The output path is not `.json`.** `[implied]`
Given `to="report.txt"`,
Then `ValueError` before any request, the same rule as `Report.export`
(`report.py:467`).

**Cancel:** Ctrl-C during recover leaves the record unchanged and leaves `to` untouched (RC-D5).
**Empty state:** RC-E3. **Repeat:** after RC-H4, a second recover returns the same Report again (RC-D10).

## 5. Non-functional requirements

- File mode: peak memory as in RC-D8. Staging disk: at most the largest artifact, plus the output
  file. `[proposed]`
- In-memory mode: Candidates are fetched one at a time, and each body is dropped after its decode.
  The peak is the Report's own size plus one artifact. `[proposed]`
- Time: about the download time of the artifacts plus the decode time. No model calls, so no
  spend. `[stated prompt]`
- Security: the SDK sends credentials only to an `engine_url` that is `https`, or `http` on
  loopback (RS-D3). `[proposed]`
- Observability: each Candidate logs one INFO line with its name, run id, and source (inline,
  fetched, missing, expired). `[proposed]`

## 6. Out of scope

- Re-attaching to live runs. `[stated ans:Q7]`
- Starting the local stack. `[stated ans:Q11]`
- A Report loader for an existing `report.json`. `[proposed]`
- Recovery of an Inspect `.eval` export. `[proposed]`

## 7. Open questions

None. OQ-1 is resolved by `ans:Q13`.

## 8. TDD plan

Build outside-in: the E2E spine first (it is the ticket's acceptance 1), then the cases inside
it. RED first for every row.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RC-E2E-1 | `killed_notebook_after_terminal_frame_recovers_same_report` (subprocess runs `sf.evaluate` against a fake Engine, is SIGKILLed inside `_materialize_sync`; a new process calls `sf.recover`; compare `export()` bytes with a control run) | e2e | RC-H1, RE-E2 | H×H | the whole flow |
| RC-1 | `recover_to_file_bytes_equal_in_memory_export` | integration | RC-H2 | H×H | writer + per-Candidate decode |
| RC-2 | `recover_to_file_peak_memory_is_bounded_by_one_candidate` (tracemalloc; 6 Candidates of 20 MB) | integration | RC-D8 | H×M | stage to file, `json.load` one at a time |
| RC-3 | `missing_runs_yield_partial_report_named_not_finished` | integration | RC-D1 | H×H | reuse `raise_candidates_failed` |
| RC-4 | `all_expired_raises_result_expired_with_age_and_removes_record` | integration | RC-E1 | H×M | map 404 from `/artifacts/` |
| RC-5 | `integrity_mismatch_keeps_record` | integration | RC-E5 | H×L | existing check |
| RC-6 | `crash_during_recover_to_file_leaves_target_untouched` | integration | RC-D5 | H×L | tmp + `os.replace` |
| RC-7 | `recover_uses_record_engine_not_default_client` | integration | RC-H3 | M×M | temporary Client for the record's origin |
| RC-8 | `local_stack_down_raises_clear_error_and_starts_nothing` | integration | RC-E2 | M×H | connect error on loopback → code |
| RC-9 | `partial_expiry_marks_those_candidates_result_expired` | integration | RC-D2 | H×L | per-Candidate 404 |
| RC-10 | `in_progress_record_recovers_finished_runs_without_state_change` | integration | RC-D3 | M×M | check the owner view |
| RC-11 | `transient_fetch_error_keeps_record_and_writes_no_file` | integration | RC-D4 | M×M | — |
| RC-12 | `disk_full_while_staging_raises_recovery_disk_full_and_cleans_up` | integration | RC-D6 | M×L | map `ENOSPC` |
| RC-13 | `inline_runs_send_no_artifact_request` | integration | RC-D9 | M×M | — |
| RC-14 | `delivered_record_recovers_like_open` | integration | RC-D10 | M×M | — |
| RC-15 | `successful_recover_marks_delivered_and_restarts_clock` | integration | RC-H4 | M×H | `mark_delivered` |
| RC-16 | `hosted_recover_mints_fresh_token_per_fetch` | integration | RC-H5 | M×M | reuse `_materialize_sync` |
| RC-17 | `unauthenticated_hosted_recover_keeps_record` | integration | RC-E4 | M×M | — |
| RC-18 | `cli_recover_exit_codes_0_2_1` | integration | §3 | M×M | argparse subcommand in `_runtime/cli.py:40` |
| RC-19 | `concurrent_recovers_both_succeed` | integration | RC-D7 | L×L | unique staging names |
| RC-20 | `non_json_target_is_refused_before_any_request` | unit | RC-D11 | L×M | shared path rule |
| RC-21 | `unknown_id_hint_names_recover_list` | unit | RC-E3 | L×M | — |

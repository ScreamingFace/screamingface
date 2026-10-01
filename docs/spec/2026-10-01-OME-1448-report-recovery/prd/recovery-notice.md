# PRD: Find recoverable Evaluations (notice and list)

**Source:** prompt / ans:Q5, Q10 · **Priority:** P1
**Lifecycle:** planned · **Owner:** @ionesio

## 1. Summary and user story

As a researcher who restarts a dead notebook, I want the SDK to tell me that a finished
Evaluation can be recovered, so that I do not believe the run is lost and pay for it again.
`[stated prompt]` ("Nothing told the researcher that the results were sitting on disk.")

## 2. Background and constraints

- "The first SDK call in a new process prints one info line … `screamingface recover --list`
  also lists them. This is quiet when there is nothing to recover." `[stated ans:Q5]`
- Delivered records get no notice. `[stated ans:Q10]`
- The notice follows the existing local-stack notice, which uses one `print` line in
  `default_client()` `[existing packages/screamingface/src/screamingface/_default_client.py:54]`.
- Uses: `prd/recovery-store.md` (scan, views, prune).

## 3. Public surface `[proposed]`

```python
@dataclass(frozen=True, slots=True)
class RecoverableEvaluation:
    evaluation_id: str
    created_at: datetime
    view: Literal["recoverable", "in_progress", "delivered"]
    benchmark_id: str
    engine_url: str
    finished: int          # run records present
    total: int             # Candidates in the Evaluation
    last_completed_at: datetime | None

def recoverable(*, include_delivered: bool = False) -> tuple[RecoverableEvaluation, ...]
```

Notice text (exactly one line on stdout):

```
1 finished evaluation can be recovered: sf.recover("ev_…") — list them with `screamingface recover --list`
3 finished evaluations can be recovered (newest: sf.recover("ev_…")) — list them with `screamingface recover --list`
```

## 4. Scenarios and acceptance criteria

### 4.1 Happy path

**RN-H1. Notice after a crash.** `[stated ans:Q5]`
Given one `recoverable` record,
When a new process constructs its first `Client` (directly or through `default_client()`),
Then exactly the one-record line above is printed once.

**RN-H2. Quiet when nothing to recover.** `[stated ans:Q5]`
Given no record, or only `delivered` and `in_progress` records,
Then nothing is printed.

**RN-H3. List.** `[stated ans:Q5]`
Given 2 recoverable and 1 delivered record,
When `screamingface recover --list` runs, Then it prints a table of the 2 (id, created, benchmark,
engine, finished/total), newest first. `--all` adds the delivered one.
`sf.recoverable()` returns the same 2 entries, and `include_delivered=True` returns 3.

### 4.2 Error paths

**RN-E1. The store cannot be read.** `[proposed]` · M × L
Given `<data_dir>/runs` is unreadable,
When the first Client is constructed,
Then no notice and no exception. One DEBUG log line names the reason. Client construction never
fails because of the notice.

### 4.3 Derived scenarios (risk order)

**RN-D1. Once per process.** `[proposed]` · M × H
Given three Clients constructed in one process,
Then the notice prints at most once.

**RN-D2. The scan prunes.** `[stated ans:Q10]` · L × H
Given a delivered record older than 7 days and an empty crashed record,
When the notice scan runs,
Then both are pruned (RS-D6, RS-D7) and neither is counted.

**RN-D3. The current process's own Evaluation.** `[proposed — gap §per-flow/concurrent]` · M × M
Given this process has an `open` record (its own Evaluation is running),
Then it is `in_progress` and not counted.

**RN-D4. A local record that has probably expired.** `[proposed]` · L × M
Given a local record whose newest run finished more than 48 hours ago,
Then it is still counted, and `--list` marks it "probably expired (local results are kept 48 h)".
The SDK does not delete it until a recover confirms the 404. `[stated ans:Q4]`

**RN-D5. Opt-out.** `[proposed]` · L × L
Given `SCREAMINGFACE_RECOVERY_NOTICE=0`,
Then no notice. `recoverable()` and `--list` still work.

**RN-D6. No network.** `[proposed]` · M × L
The scan sends no request and starts no thread. It reads the filesystem only.

**RN-D7. Many records.** `[proposed — gap §cross-cutting/capacity]` · L × L
Given 200 Evaluation directories, the scan takes ≤ 50 ms (RS §4).

## 5. Non-functional requirements

- Notice scan ≤ 50 ms for 200 records. No network. `[proposed]`
- The line is plain text, with no ANSI color, so notebooks and logs show it the same way.
  `[proposed]`

## 6. Out of scope

- A notebook widget for recovery. `[proposed]`
- Printing the id at `sf.evaluate` start (the user did not pick this option). `[stated ans:Q5]`

## 7. Open questions

None.

## 8. TDD plan

Core-out: classification first, then the print, then the CLI.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| RN-1 | `first_client_prints_one_line_for_one_recoverable_record` | integration | RN-H1 | M×H | hook in `Client.__init__`, module-level once flag |
| RN-2 | `notice_is_silent_for_delivered_in_progress_and_empty_store` | unit | RN-H2, RN-D3 | M×H | count only `recoverable` |
| RN-3 | `client_construction_never_fails_on_unreadable_store` | unit | RN-E1 | M×L | catch everything, log DEBUG |
| RN-4 | `notice_prints_at_most_once_per_process` | unit | RN-D1 | M×H | once flag |
| RN-5 | `scan_prunes_old_delivered_and_empty_records` | unit | RN-D2 | L×H | calls the store's prune |
| RN-6 | `scan_sends_no_request` (httpx transport that fails on any call) | unit | RN-D6 | M×L | filesystem only |
| RN-7 | `multi_record_line_names_count_and_newest` | unit | §3 | L×M | format |
| RN-8 | `recoverable_and_cli_list_agree_and_all_adds_delivered` | integration | RN-H3 | M×M | one query function |
| RN-9 | `old_local_record_is_marked_probably_expired_not_deleted` | unit | RN-D4 | L×M | age vs 48 h |
| RN-10 | `env_opt_out_silences_notice_only` | unit | RN-D5 | L×L | env check |
| RN-11 | `scan_of_200_records_under_50ms` (benchmark marker) | unit | RN-D7 | L×L | — |

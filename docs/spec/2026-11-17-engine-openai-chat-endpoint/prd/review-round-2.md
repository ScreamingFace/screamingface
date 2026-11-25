# PRD: review round 2 after PR-open (2026-11-25)

Source: the re-review of PR #1937 by HupBaHa on 2026-11-24 (review 6043196944, 10 items, head
`3b1cfc34f`), the comment on the Engine CI path filters (7139903665), and the items of the
reviews of 2026-11-21 that were still open. Each item was checked against the code on 2026-11-25
(four read-only scouts and a second read by the planner). This PRD holds only the items that are
valid and reachable. Section 9 lists the items that wait.

Source tags: `[review N]` = item N of the review of 2026-11-24; `[review-1 N]` = item N of the
reviews of 2026-11-21; `[stated ans:Rn]` = owner answer of 2026-11-25; `[proposed]` = decision
of the planner.

## 0. Owner answers of 2026-11-25 (do not ask again)

| Id | Question | Answer |
|---|---|---|
| R1 | Item 6 reopens Q14 (ignored request fields). | "Keep ignore, add a signal": the fields stay ignored; the reply names them in `screamingface.ignored_parameters`; `n` below 1 gets HTTP 400. |
| R2 | The defects in the tool code, which no request can reach while tools are off (U11). | "Defer, no ticket yet": a list in the ledger only. |
| R3 | Changes to `.claude/test-change-approvals/OME-1963.json`. | "Yes, all three kinds": new hashes for files that `main` changed; the import line of `tests/unit/test_gateway_code_screen.py`; new hashes when a fix must change a test that this PR already changed. |
| R4 | Outward steps when the gates are green. | "Push and reply": force-push with lease, PR body update, one reply to the reviewer. No merge. |

## 1. Run start and stop (Engine)

**RR-S1 The start of a chat run is one attempt of its topic.** `[review 2]` `[review-1 1]`
The route wraps the schedule call in `job_runner.start_attempt(topic)`, as the `/runs` route does
(`rest/routes.py::_claim_topic`).

**RR-S2 The cleanup stops with the bound stop.** `[review 2]`
`ChatCleanup` gets `job_runner.stop_bound`. Given a request that is cancelled while the schedule
call waits, or a schedule that ends `queue_unavailable`, when the cleanup runs, then
`stop_bound(topic)` is called one time and plain `stop` is not called. WHY: the queue runner
writes a tombstone for a bound stop also when it has no record of the schedule
(`adapters/queue_runner.py::_tombstone_queued_run`), so a message that lands later is skipped.

**RR-S3 A refused schedule stops nothing** (unchanged, CC-S28). A 429 or another refusal that
queued nothing calls no stop.

**RR-S4 The cleanup deletes the input after the write has ended.** `[review 3]` `[review-1 2]`
The write runs as its own task, and the request waits for it behind a shield. The cleanup waits
for that task (its result or its error) before the delete. Given a request that is cancelled
while the store write runs in its thread, when the cleanup has ended, then the store holds no
blob of that request.

**RR-S5 No coroutine is left without an await.** `[review-1 7]`
`RunWait` and `wait_for_run` do not make the `scan_run` coroutine before their task runs. Given
a wait that is cancelled before its first step, then Python reports no "never awaited" warning.
(Reproduced on 2026-11-25 with a 10-line probe.)

## 2. Result delivery (Engine)

**RR-S6 A chat result has a size limit in the App.** `[review 4]` `[review-1 3]`
`CHAT_RESULT_MAX_BYTES = 8_388_608` (8 MiB) `[proposed]`. WHY 8 MiB: the same order as the
request body limit; a model answer is far below it; the Runner limit of 1 GiB is for benchmark
results. The App never holds more than the limit plus one read unit of a result:
- an inline body is at most 512 KiB (the Runner rule), so it passes;
- a local file is checked by its size before the read;
- a remote stream stops at the first chunk that passes the limit.
A result above the limit answers 502 `result_too_large`, `x-should-retry: false`.

**RR-S7 A store error on the result read is `result_unavailable`.** `[review 10]` `[review-1 8]`
`store.content(...)` is inside the `try`. `OSError` and `S3StorageError`, at the open or in the
stream, answer 502 `result_unavailable`, in the JSON answer and in the event stream.

**RR-S8 Keep-alive lines continue until the answer is ready.** `[review-1 5]`
In a stream, the read, the decode and the framing of the result run while keep-alive lines are
sent each `keepalive_s`.

**RR-S9 A short outage of the input store can be tried again.** `[review-1 18]` `[proposed]`
Terminal table row: failed, `chat_input_unavailable`, error not permanent → 503
`chat_input_unavailable`, `x-should-retry: true`, `Retry-After: 5`. WHY: no model call was made.
The permanent case (the blob is absent) stays 500 with `x-should-retry: false`.
`chat_input_invalid` stays 500, false.

## 3. Request boundary (Engine)

**RR-S10 Each body has a read deadline.** `[review-1 4]`
The body read has a total limit of 30 s from its start, for each size → 408 `request_timeout`.
The rule for a large body is unchanged (30 s from the parse place).

**RR-S11 `n` below 1 is refused.** `[review 6]` `[stated ans:R1]`
`n` = 0 or negative → 400 `invalid_request`, param `n`. `n` = 1 passes. `n` above 1 stays 400
`unsupported_parameter` (CC-S16).

**RR-S12 The reply names the fields that the Engine ignored.** `[stated ans:R1]`
- A field is ignored when it is a top-level key of the body, its value is not `null`, and the
  Engine does not read it. The Engine reads: `model`, `messages`, `tools`, `functions`, `stream`,
  `stream_options`, `n`, `logprobs`, `modalities`, `audio`.
- `screamingface.ignored_parameters` is the sorted list of these names. Limits `[proposed]`: a
  name longer than 64 characters is left out; the list holds at most 32 names.
- The key is absent when the list is empty, so a reply to a request with no such field does not
  change.
- The JSON answer and the stream chunk that holds the `screamingface` object both have it.
- INVARIANT: the names are request data. No log line, metric label or span holds them.
- CC-S7 stays: no model call gets the values.

## 4. Local blob files (Engine)

**RR-S13 Local blob files are private.** `[review 8]` `[review-1 16]`
`FilesystemBlobObjects` makes each directory with mode 0700 and each file with mode 0600, for
each umask. When the root exists: owned by another user → an error before any write, and local
mode does not start; owned by this user with a wider mode → set to 0700. POSIX only. WHY for the
whole class: only local mode uses the filesystem blob store (`app.py` refuses it with the queue
runner).

## 5. Final step on a cache hit (Engine and SDK)

**RR-S14 `final_step` tells a cache hit.** `[review 10]` `[review-1 13]` `[proposed]`
On a gateway cache hit the counts of `final_step.usage` are 0, by the same rule as the top-level
`usage` (ans:Q27, OME-1687), and `final_step.cached` is `true`. The key `cached` is absent on a
miss. WHY not the stored counts: the shared accounting record sets them to zero for a hit, and
that record also feeds the benchmark reports. The ERD line, the `FinalStep` docstring and the
guide are corrected: a client keeps its last known context size on a hit. The SDK type
`FinalStep` gets `cached: bool = False`; `to_dict()` has the key only when it is true.

## 6. OpenAPI document and CI (Engine)

**RR-S15 The served document matches the route.** `[review 10]` `[review-1 7]`
The chat operation declares: 408; each status and code that the route can answer (also
`result_too_large` and the two cases of `chat_input_unavailable`); the headers `Retry-After` and
`x-should-retry` on the answers that can have them; the `screamingface` object with
`ignored_parameters` and `final_step.cached`; in hosted mode the Access header as its security
scheme and not the capability scheme. A test compares the declared statuses with the statuses
that the route code can raise.

**RR-S16 The Engine CI runs on the SDK files that its chat tests read.** `[comment 7139903665]`
Both `paths:` lists of `.github/workflows/screamingface-engine-tests.yml` get
`packages/screamingface/tests/data/surface_parity.json` and
`packages/screamingface/src/screamingface/_operation_bindings.py`. PR #2035 edits the same lines.

## 7. SDK calls

**RR-S17 A cancelled stream releases its connection.** `[review 9]`
`AsyncChatStream.__anext__` releases the connection on each `BaseException` (a task cancel
included). `aclose()` is marked closed only when the release ended; a release that was cancelled
runs again at the next `aclose()`. `ChatStream` follows the same two rules.

**RR-S18 `timeout` is the limit of the full call.** `[review 9]` (contracts C1 P11: "seconds for
the full call") The time of the model resolution (the catalogue read and the compile) counts.
When the limit passes before the request, the call raises the error of a client timeout and
sends no request. Else the request and its tries get the time that is left. In the async call
the resolution itself is stopped at the limit. `timeout=None` is unchanged.

## 8. Docs

**RR-S19 The bridge examples turn the OpenAI retries off.** `[review 5]`
Each snippet and README block that makes an `openai` client for the Engine passes
`max_retries=0`, and each page says why: the OpenAI client tries two more times after a lost
connection, and each try is a new paid run. A docs test fails when such a block has no
`max_retries=0`.

**RR-S20 The guide states the new rules:** `ignored_parameters`; `final_step.cached`;
`result_too_large`; the retry of `chat_input_unavailable`; the 30 s body limit for each size.

## 9. Items that wait (owner answer R2: list only, no ticket)

No request can reach this code while tool use is refused at the route (U11). Fix each one before
tool calls are turned on again:
- `[review 7]` `[review-1 12]` the chat-route check is a text test; a percent-encoded eval path
  hides the prefix (bind the re-point to a token of the turn).
- `[review 7]` `[review-1 15]` a tool history with no matching call is not refused before the
  members run.
- `[review 7]` `[review-1 20]` the Gate intent is not checked against its join; `_find_source`
  takes the first source and url4 binds the last. Without tools this can only give wrong
  `final_step` data for a recipe written by hand.
- `[review 7]` `[review-1 6, 10]` a `binding=` parameter from the caller is kept on a final step.
- `[review 7]` `[review-1 14]` `_shown_context` sends the conversation two times for some contexts.
- `[review 6]` the message role `function` and tools of type `custom` answer `invalid_request`;
  a provider tool call with an empty function name is accepted.
- `[review-1 6]` a tool recipe with only outcome steps needs the model catalogue.
- `[review-1 19]` a provider tool call that fails the wire model ends `aigateway_bad_response`,
  and its call is not recorded.

Not code: `[review-1 17]` the deploy check with a forged `X-User-Email` header and `[review-1 22]`
the sentence about members and tools go into the PR body.

Already done before this round: `[review 1]` (the gateway code rule is in
`world/gateway_transport.py` since the rebase), `[review-1 9]`, `[review-1 11]`, `[review-1 21]`.

## 10. TDD plan (RED first; order by risk)

| # | Test | Level | Scenario |
|---|---|---|---|
| RR-1 | `cancel_during_schedule_calls_the_bound_stop` | unit | RR-S1, RR-S2 |
| RR-2 | `unknown_publish_calls_the_bound_stop` | unit | RR-S2 |
| RR-3 | `refused_schedule_calls_no_stop` | unit | RR-S3 |
| RR-4 | `cancel_during_input_write_leaves_no_blob` | unit | RR-S4 |
| RR-5 | `failed_input_write_still_cleans` | unit | RR-S4 |
| RR-6 | `local_result_file_above_the_limit_is_refused_before_the_read` | unit | RR-S6 |
| RR-7 | `remote_result_stream_stops_at_the_limit` | unit | RR-S6 |
| RR-8 | `store_error_at_open_and_in_stream_is_result_unavailable` (JSON and stream) | unit | RR-S7 |
| RR-9 | `keep_alive_lines_continue_during_a_slow_result_read` | unit | RR-S8 |
| RR-10 | `transient_input_outage_is_503_with_retry` and the permanent row | unit | RR-S9 |
| RR-11 | `small_body_that_stalls_gets_408` | unit | RR-S10 |
| RR-12 | `n_below_one_is_invalid` (0, -1, 1, 2) | unit | RR-S11 |
| RR-13 | `reply_lists_ignored_fields_sorted`, absent when none | unit | RR-S12 |
| RR-14 | `stream_info_chunk_lists_ignored_fields` | unit | RR-S12 |
| RR-15 | `null_values_long_names_and_the_cap` | unit | RR-S12 |
| RR-16 | `no_log_line_holds_an_ignored_name` | unit | RR-S12 |
| RR-17 | `blob_dirs_are_0700_and_files_0600_for_each_umask` | unit | RR-S13 |
| RR-18 | `a_wide_root_is_narrowed_and_a_foreign_root_is_refused` | unit | RR-S13 |
| RR-19 | `final_step_of_a_cache_hit_is_marked`, absent on a miss (JSON and stream) | unit | RR-S14 |
| RR-20 | `openapi_declares_each_status_the_route_can_answer`, headers, security | unit | RR-S15 |
| RR-21 | `cancelled_wait_leaves_no_unawaited_coroutine` | unit | RR-S5 |
| RR-22 | `engine_ci_paths_cover_the_sdk_files_the_chat_tests_read` | unit | RR-S16 |
| RR-23 | `docs_openai_clients_pass_max_retries_zero` (Engine docs test and SDK docs test) | unit | RR-S19 |
| MI-51 | `cancel_while_waiting_for_a_chunk_releases_the_connection` | unit | RR-S17 |
| MI-52 | `a_cancelled_aclose_runs_again` | unit | RR-S17 |
| MI-53 | `timeout_counts_the_model_resolution` (sync: no request is sent) | unit | RR-S18 |
| MI-54 | `the_request_gets_the_time_that_is_left` | unit | RR-S18 |
| MI-55 | `async_resolution_stops_at_the_timeout` | unit | RR-S18 |
| MI-56 | `final_step_cached_is_read_and_dumped_only_when_true` | unit | RR-S14 |

Rules for each test: a new test file or a new test function; a test that exists is changed only
when the new rule makes its old assertion false (owner answer R3), and the ledger lists each such
change.

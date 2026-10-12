---
ticket: OME-1435
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-08
finished: 2026-10-08
---

# e14-b3-engine-frozen-copy — engine capture mode (frozen copy) and replay mode

## Intent

E14 PR F-B3 (design `02-frozen-copy-design.md` §5, §9). A run that gets `X-Capture: true` opens a
frozen copy in the AI Gateway before its first step, sends `X-AIGW-Frozen-Copy: <id>` on every chat
call, posts every web-tool result string to the copy, and seals the copy when the steps end. A run
that gets `X-Replay-Frozen-Copy: <uuid>` sends every chat call to the copy's replay route, reads
every web-tool result from the copy, and never calls a provider or Tavily. A run-scoped tally (with
the old D1 and D2 rules) gives `capture.status`. The run summary always states `capture.*` for a
capture run and `capture.replay` for a replay run. Local only: no push, no PR, no Linear.

## Planned changes

- New: `src/screamingface_engine/capture_outcomes.py` (run-scoped tally, adapted from the old
  `replay_outcomes.py`).
- `request_scope.py`, `job_env.py`, `runner/main.py`: `capture` and `replay_frozen_copy` end to end.
- `rest/routes.py`, `ports.py`, `adapters/inprocess.py`, `adapters/queue_runner.py`,
  `runner_queue.py`, `local.py`: header into the job env, and the start-response echo.
- `world/connector.py`: copy header and capture status on chat; replay route and occurrence header;
  `open_frozen_copy` and `seal_frozen_copy` on the connector's gateway client.
- `world/web_tools.py`: tool-result capture before truncation; tool lookup in replay mode, no Tavily.
- `runner/executor.py`: bind the tally; open before the steps, seal after; summary attributes.
- `error_text.py`, `benchmarks/contract.py`, SDK `_report_primitives.py`: the two new failure codes.
- `README.md`: capture and replay section.
- New tests only, under `tests/unit/`.

## Test plan

The F-B3 TDD list, in order (risk order):

1. replay never calls Tavily or the normal chat route.
2. capture sends the copy header on every chat call and records the capture status.
3. a normal run is byte-identical (no new header, no tool-result post, no new summary attribute).
4. the `capture.status` rule table (D1, D2).
5. tool results are posted before truncation, failure strings included.
6. replay occurrence counter per digest.
7. replay 404 miss and unavailable fail the case with their codes; a tool lookup miss fails it.
8. replay success is accounted as zero spend.
9. header, env and scope plumbing for both modes; both present is 400; malformed uuid is 400; echo.
10. the summary is always written for capture and replay runs.
11. open and seal once per run; seal on a failed run; no seal on a cancelled run.

## Acceptance

- Gates green for `screamingface-engine` with `--base e14-b2-engine-tavily-cache`.
- No existing test edited, except the approved edits below.

## Approved test changes (append-only exception)

**Owner approval:** confirmed by the owner on 2026-10-08. The append-only gate may skip these edits.

Pre-approved by the F-B3 plan. Nothing else in an existing test may move.

1. `frozen_copy_miss` and `frozen_copy_unavailable` added to the exact sets in
   `tests/unit/test_failure_classes.py` and `tests/unit/test_terminal_error_detail.py`.
2. `capture` / `replay_frozen_copy` parameters added to fake `schedule` signatures (a fake that
   pyright rejects after the port gains the parameters).
3. `tests/unit/data/cache_hit_contract/run_events.json` regenerated only if the normal-run bytes
   change. They must not.

## Approved test changes — as applied

1. Two codes added to `ALLOWLISTED_CODES` in `tests/unit/test_terminal_error_detail.py` and to the
   exact set in `tests/unit/test_failure_classes.py` (two entries each, nothing else).
2. `capture: bool = False` and `replay_frozen_copy: str | None = None` added to one `schedule`
   signature in each of `tests/unit/_fakes.py`, `tests/unit/test_queue_admission.py`,
   `tests/unit/test_answer_seed_threading.py`, `tests/unit/test_cache_policy_threading.py`,
   `tests/integration/test_e2e_compose_flow.py` and
   `tests/integration/test_run_control_resilience.py` (pyright rejected the overrides after the
   port gained the parameters).
3. `run_events.json` is NOT regenerated: a normal run writes nothing new, and
   `test_cache_hit_contract.py` still passes on the old bytes.

## Decisions made inside the plan (flagged for review)

- D-a: the executor reaches the connector's gateway client through a side table keyed by the world
  node (`world.connector._GATEWAY_CLIENTS`, the idiom of `world.factory._DIRECT_MOUNTS`), read by
  `open_frozen_copy(node)` and `seal_frozen_copy(node, id)`. The plan said "use the connector's
  gateway client" and did not say how the executor gets it. A node with no client (a bare io
  layer) cannot open a copy, so the run is partial with reason `open`.
- D-b: `X-Capture` accepts only `true` (case-insensitive); any other value is 400. A replay id must
  be a lowercase hyphenated UUID (`job_env.FROZEN_COPY_ID`), so the echo equals what was sent.
- D-c: a 404 whose `detail` is exactly "Not Found" reads as `frozen_copy_unavailable` (design §9,
  a gateway older than B1, which has no replay route). Any other 404 without a replay code is the
  captured original error.
- D-d: tool lookup: any 404 is `frozen_copy_miss`, unless `detail.code` says unavailable; any other
  failure (transport, 5xx, a malformed body) is `frozen_copy_unavailable`, transient. The model
  never reads a made-up result.
- D-e: the engine's request digest is the chat body WITHOUT the cache field (the gateway pops it
  before it digests), or the tool description. Occurrence counters are keyed `(lane, digest)`.
- D-f: replay accounts a found answer as an UNRETRIED hit, so a transport retry of a replay call
  does not unprice it (a replay attempt can never have been billed).

## Known limits

- A capture run under a `max-age` bound stores the discarded hit AND the live re-issue (two 200
  entries for one logical call), and a replay takes entry 0 (the discarded hit). Review F8: kept as
  a documented limit. Since review round 1 the capture run is marked `partial` for it
  (`capture.partial.ambiguous`), so the limit is visible and never hidden in a `complete` run.
- A replay's occurrence slot follows the order requests are SENT, so two concurrent identical
  requests can take their entries in another order than capture did (design §9). They get distinct
  entries.
- No engine run path calls `/v1/models/admit` (only the catalog route
  `GET /v1/models/{id}/parameters` does), so a replay never calls it. A retired model still needs
  its route in the run's world config: replay does not add undeclared routes. See the open question
  in the report.

## Review round 1 (coordinator, 2026-10-08) — what changed

- F1+F2: a capture call that was re-issued under a `max-age` bound, or whose transport attempt was
  retried, records `ambiguous` (never forgiven); `capture.partial.ambiguous` counts it.
- F3: the replay occurrence slot is reserved when the call is sent and released unless it succeeds
  (`CaptureTally.reserve` / `release`), for chat and tool lookups. Concurrent tests for both.
- F4: a cancelled or crashed tool execution in capture mode records `error`, then re-raises.
- F5: a failed capture or replay run writes its `capture.*` attributes into the run summary and one
  log frame (no cache counters: a failed run's figures are not exact). A stopped run writes none.
- F6: mount routes and the local eval path answer 400 `capture_unsupported` for either header
  (presence counts). The sync producer and the forwarding allowlist no longer carry the headers.
- F7: a replayed answer is accounted as a hit at $0 with no saved-cost claim (the connector hands
  `_report_response` no `_aigw` for a replay).
- F10: the two wrong comments fixed (the lookup docstring; "permanent" in the contract and SDK mirror).
- F11: `FrozenToolResults.store`, `open_frozen_copy` and `seal_frozen_copy` catch `Exception`.
- F12: `CaptureTally.sealed` replaces `seal_failed`; `status()` is `complete` only when sealed. A
  copy that opened and was never confirmed sealed counts as `capture.partial.seal`.
- F16: the paths and header names are shared constants in `capture_outcomes.py`; the `_reason_of`
  mapping is gone.
- F17: the guard test `test_a_replay_never_calls_the_model_admission_route` was added. It passed
  before and after: no run path calls the admission route (see Known limits).
- Test edits: only files of this PR changed (`test_frozen_copy_headers.py`,
  `test_capture_outcomes.py`, `test_frozen_copy_normal_run.py`, `frozen_copy_support.py`). No
  prior test of the base branch moved beyond the approved list above.

## Outcome

- **Actual files:** as planned. New: `capture_outcomes.py`, and under `tests/unit/`:
  `frozen_copy_support.py` (shared fakes, not a test module), `test_frozen_copy_scope.py`,
  `test_frozen_copy_calls.py`, `test_frozen_copy_normal_run.py`, `test_capture_outcomes.py`,
  `test_frozen_copy_tool_capture.py`, `test_frozen_copy_occurrence.py`,
  `test_frozen_copy_replay_failures.py`, `test_frozen_copy_replay_accounting.py`,
  `test_frozen_copy_headers.py`, `test_frozen_copy_executor.py`. Changed: `request_scope.py`,
  `job_env.py`, `runner/main.py`, `runner/executor.py`, `rest/routes.py`, `ports.py`,
  `adapters/inprocess.py`, `adapters/queue_runner.py`, `runner_queue.py`, `local.py`,
  `world/connector.py`, `world/web_tools.py`, `error_text.py`, `benchmarks/contract.py`,
  `README.md`, and the SDK mirror `packages/screamingface/src/screamingface/_report_primitives.py`.
- **Commits:** see `git log --oneline e14-b2-engine-tavily-cache..HEAD`.
- **Gates:** after review round 1, engine with `--skip-append-only`: ruff, format, pyright,
  layering and pytest pass (`ALL GATES GREEN`). Without it, only the append-only check fails and it
  lists exactly the eight approved files above. SDK package (comment-only change in the mirror):
  ruff, format and pyright pass. SDK package (touched for the mirror): ruff, format and pyright
  pass; pytest gives `2245 passed, 26 skipped`. The SDK notebook, build and distribution gates
  were not run (a frozenset edit cannot affect them).
- **Deviations:** none from the plan's files or pinned decisions; see "Decisions made inside the
  plan" for the points the plan left open.

## Rebase onto main (2026-10-08)

- The stack was rebased onto `origin/main` `4cd063445` (87 new commits on main).
- Conflict in `world/connector.py`: main moved the POST into `_post_attempt`. That helper now takes
  a keyword `path` (default `_COMPLETIONS_PATH`), so the replay route still goes through the
  transport retry and the deadline rules.
- Conflict in `benchmarks/contract.py` and `tests/unit/test_failure_classes.py`: main added four
  timeout codes. Both sets keep main's codes and `frozen_copy_miss`, `frozen_copy_unavailable`.
- New commit: `test_normal_run_is_byte_identical` checks only for `X-AIGW-Frozen-Copy` and
  `X-AIGW-Replay-Occurrence`. Main now sends the gateway timeout headers on every chat call.
- Gates for stack `screamingface-engine` pass against `e14-b2-engine-tavily-cache`
  (`--skip-append-only`; the approved test edits are unchanged).

## Rebase 2026-10-11

- The stack was rebased onto origin/main 8e0c0a298. That commit has url4 2.0.
- In url4 2.0, an unquoted intent such as `!go` is a code pointer. It needs a code mount.
  Two tests in `test_frozen_copy_executor.py` used `!go` and failed with `no code mount at 'go'`.
- I quoted the intent (`!'go'`) in three expressions in that test file. Now `go` is a normal
  model intent. No assertion changed. No B3 production code changed.

## Review round 2026-10-12 (design review fixes)

- **Scope:** plan `R-2026-10-12-design-review-fixes.md`, sections 0a and B3. Design
  `02-frozen-copy-design.md` Q23, Q27, Q28, §4.2, §5.2, §5.3 (items 2 and 2a) and §5.4.
- **Status: NOT complete.** The gate fails in one place: eight existing tests in
  `test_frozen_copy_replay_failures.py` encode the old failure rule. They need an approval
  (see "Blocked"). Every other gate step passes.

### Changes

- **Q27, call key.** Every chat call and every web-tool call sends `X-AIGW-Call-Occurrence` (always)
  and `X-AIGW-Case-Key` (only when the key is not empty), in capture and in replay.
  `call_key_headers(case_key, occurrence)` in `capture_outcomes.py` builds the two headers for all
  four call sites.
  - The case key is `case_key_for(case_id, attempt)`. `current_case_key()` is in
    `benchmarks/case_context.py`.
  - The occurrence counts the logical calls of one (case key, lane, request digest). It is taken once,
    when the call is first sent, and it is never given back. Transport retries reuse it.
  - A tool call takes its occurrence in `_executed`, before the tool runs.
  - Capture and replay take the occurrence from the run's tally. A replay with no tally bound fails
    loudly (`RuntimeError`) and sends nothing.
  - D2 is removed: `_lost()` counts every outcome that is not `stored`.
  - The capture path reads its tally and copy id once (`_capture_target`).
- **Design §5.3 2a, permanent unserved failures.** In replay, these fail the case with
  `frozen_copy_unavailable`, permanently:
  - a chat call whose every transport attempt failed (`_fetch_replay` catches the transport
    `ResolutionError` from `_post_completion`);
  - a non-2xx answer without the `X-AIGW-Replay` header (`REPLAY_FIELD`, new constant);
  - a tool lookup failure that the copy did not serve. Every such failure is permanent, not only a
    transport error. The stale "a retry may fix it" comment is gone.
  A captured error with `X-AIGW-Replay: error` is raised as before. The 404 codes are unchanged.
- **Q23, local capture.** `local.py` sets `URL4_LOCAL_RUNTIME=1` on every run env it builds. The
  marker is listed in `job_env.WRITTEN_BY_APP`. It reaches `RequestScope.local_runtime`, and
  `_bind_frozen_copy_mode` sets `CaptureTally.local`. A local capture is `partial` with reason
  `local`, and a local capture is never reproducible (the local app may point at the hosted gateway).
- **Q28, provenance.** `screamingface_engine.__version__` comes from the installed package metadata.
  It raises `PackageNotFoundError` when the package is not installed; this is accepted, and a comment
  says so. `seal_frozen_copy` posts `{"provenance": {"engine_version": __version__}}`.
- **Can the sync surface replay?** No. Design §5.1 allows the run route only. The mount routes
  (`rest/mounts.py`, `_validated`) and the local eval path (`local.py`, before `bind_sync_request`)
  refuse `X-Replay-Frozen-Copy` with 400 `capture_unsupported` before anything is bound. The tally is
  bound in one place only: `runner/executor.py` (`_drive`).
  `test_frozen_copy_unsupported_surfaces.py` covers both refusals.
- **README.** The capture and replay paragraphs name the headers, the occurrence rule, the
  permanent failures, the `local` reason and the seal version.

### Commits (branch `OME-1435-e14-b3-engine-frozen-copy`, local only)

- `af374b82a` fix(screamingface-engine): key each frozen-copy call by case and occurrence (Q27)
- `e1201e692` fix(screamingface-engine): a local frozen-copy capture is partial (Q23)
- `65b5e0d68` fix(screamingface-engine): seal a frozen copy with the engine version (Q28)
- `231d73db2` docs(screamingface-engine): describe the call key, local capture and seal version
- `2922b6f5b` docs(work): record the B3 review round in the ledger
- `9cdda82ed` fix(screamingface-engine): count replay occurrences in the run tally only (Q27)
- `06cd16bdd` docs(work): record the replay tally fix and the approved test edits
- `d5b1b3084` fix(screamingface-engine): make an unserved replay failure permanent (design §5.3 2a)
- `ca6bb2282` docs(screamingface-engine): name the call-key headers and the permanent replay failures
- `be32f4084` test(screamingface-engine): rename a helper that shadowed a variable in the per-task replay test
- this ledger commit

### Approved test edits (2026-10-12)

First round (owner):

- `test_capture_outcomes.py`: deleted the five slot tests (reserve, release, freed).
- `test_capture_outcomes.py`, `test_capture_status_rule`: the two D2 rows now expect `partial`.
- `test_frozen_copy_overlap.py`: deleted (its two tests were the approved deletions).
- `test_frozen_copy_calls.py`: the three `3e5ee45eb` tests use `X-AIGW-Call-Occurrence`. They check
  the occurrence each task sends, in task order, through the shared helper
  `Gateway.record_arrivals` (`frozen_copy_support.py`). The helper records each occurrence when the
  request ARRIVES at the gateway, before the barrier. It checks the send order. It does not check
  the answers, because the barrier answers the parked requests in another order.

Second round (coordinator):

- `test_frozen_copy_normal_run.py`: `CALL_OCCURRENCE_HEADER` and `CASE_KEY_HEADER`, and
  `tally.occurrences == {}`.
- `test_frozen_copy_occurrence.py`: the header is `X-AIGW-Call-Occurrence`. Inverted:
  `test_a_failed_answer_does_not_move_the_counter` became `test_a_failed_answer_still_moves_the_counter`,
  and `test_a_tool_lookup_miss_does_not_move_the_counter` became
  `test_a_tool_lookup_miss_still_moves_the_counter`. Replaced:
  `test_a_run_without_a_tally_still_asks_for_the_first_answer` became
  `test_identical_replay_calls_take_occurrences_0_and_1_under_the_run_tally`.
- `test_frozen_copy_replay_review.py`: the header is `X-AIGW-Call-Occurrence`. Inverted:
  `test_a_reserved_slot_is_given_back_when_the_call_does_not_succeed` became
  `test_an_occurrence_is_never_given_back_when_the_call_does_not_succeed`.

Third round (coordinator, this feedback):

- `test_frozen_copy_replay_review.py`: the two concurrent tests,
  `test_two_identical_concurrent_replay_requests_get_occurrences_0_and_1` and
  `test_two_identical_concurrent_tool_lookups_get_occurrences_0_and_1`, check the arrival order
  (`["0", "1"]`, from `record_arrivals`) instead of `sorted(...)`.
- `test_frozen_copy_occurrence.py` and `test_frozen_copy_replay_review.py`: the module docstrings
  state the Q27 rule.
- `test_frozen_copy_calls.py`: the one literal occurrence header now uses `CALL_OCCURRENCE_HEADER`.

### New tests

- `tests/unit/test_frozen_copy_call_key.py` (8). The key of capture and replay, the concurrent cases,
  the retries, the gathered tool order, the grading and Attempt keys, and the case id type.
- `tests/unit/test_frozen_copy_review_round.py` (6). The unstored error, the local partial rule, the
  hosted rule, the marker path, the executor binding, and the seal version.
- `test_frozen_copy_occurrence.py`: `test_a_replay_call_with_no_bound_tally_fails_loudly`.
- `tests/unit/test_frozen_copy_replay_per_task.py` (2). Gathered replay chat calls, and gathered
  replay tool lookups, take their own answers in task order. The fake gateway holds occurrence 0 until
  occurrence 1 has answered, so task 0 finishes last. The lookup test checks the tool messages of the
  second chat body, keyed by call id.
- `tests/unit/test_frozen_copy_replay_unserved.py` (4). One test for each unserved case: (a) every
  transport attempt failed, (b) a 500 without the replay header, (c) a lookup transport error. Each
  checks that the replay endpoint was called once per attempt, all for occurrence 0. The fourth test
  is the control: a captured error with `X-AIGW-Replay: error` keeps its own code.

### Gates (`run_gates.py screamingface-engine --base refs/e14-backup/pre-phase2-2026-10-12/OME-1045-e14-b2-engine-tavily-cache`)

- Without `--skip-append-only`: FAILED. The check flags exactly the eight approved files
  (`test_cache_policy_threading.py`, `test_failure_classes.py`, `test_queue_admission.py`,
  `test_terminal_error_detail.py`, `test_e2e_compose_flow.py`, `test_run_control_resilience.py`,
  `_fakes.py`, `test_answer_seed_threading.py`). The B3 edits are not flagged, because the base
  holds none of these files.
- With `--skip-append-only`: ruff check PASS, ruff format PASS, pyright PASS,
  `check_layering.py` PASS. pytest FAILED: 8 failed, 4908 passed, 94 skipped. All 8 failures are in
  "Blocked".
- Unit (direct run, before the last test-only commit): 4870 passed, 8 failed.

### Blocked: approval needed (not edited)

`test_frozen_copy_replay_failures.py` encodes the old failure rule. The new rule (§5.3 2a) changes
these eight tests:

- `test_any_other_status_is_the_captured_original_error_handled_as_today` (4 cases). The four
  responses have no `X-AIGW-Replay` header. A captured error carries `X-AIGW-Replay: error`, so the
  fix is to add that header to each response. Without it the case becomes `frozen_copy_unavailable`.
- `test_tool_lookup_miss_fails_the_case` (`gateway-error`, `malformed-result`, `not-json`). The
  expected `permanent` changes from `False` to `True`. The comment at line 104 says a retry may fix it.
- `test_a_tool_lookup_transport_failure_fails_the_case_as_unavailable`. The expected `permanent`
  changes from `False` to `True`.

Question for the coordinator: may I make these edits? The proposed edit is the header on the four
captured-error responses, and `permanent` `True` in the four lookup expectations.

### Interpretation to confirm

- Design §5.3 2a names three cases. The code also makes permanent a tool lookup that returns HTTP 200
  with a malformed result or with a body that is not JSON. The copy did not serve either answer, and
  a retry would read the next occurrence, so I treat them the same way. Confirm or reverse.

### Deviations

- The plan says to remove the unreachable `0 if _tally is None` branch in the connector. The capture
  branch is removed. The replay branch was reachable only from tests that drive the connector with no
  tally bound. A replay with no tally now fails loudly.
- `FrozenToolResults.lookup` and `store` take `case_key` and `occurrence` as arguments. The `_read`
  helper is merged into `lookup`.
- `RequestScope.local_runtime` is the chosen name for the local-marker field. The plan left it open.
- `URL4_LOCAL_RUNTIME` is listed in `WRITTEN_BY_APP`, because the job-env contract test requires every
  App-written key to be listed there.
- `create_local_app` builds `run_env` in one dict expression. Three statements exceeded the
  `PLR0915` limit (26).
- `REPLAY_FIELD` (`X-AIGW-Replay`) and `call_key_headers` are new in `capture_outcomes.py`. The
  coordinator asked for `call_key_headers`; `REPLAY_FIELD` follows the `CAPTURE_FIELD` pattern.
- `Gateway.record_arrivals` moved the arrival helper from `test_frozen_copy_calls.py` into the shared
  support module, so the replay tests can use it too. The support module is not a test module.
- Comments and docstrings in the approved test files changed with the approved rows.

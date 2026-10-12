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
  `02-frozen-copy-design.md` Q23, Q27, Q28, §4.2, §5.2, §5.3 and §5.4.
- **Status: complete.** All gates pass. One approval round was needed for three existing test files
  (see "Approved test edits").

### Changes

- **Q27, call key.** Every chat call and every web-tool call sends `X-AIGW-Case-Key` (only when the
  key is not empty) and `X-AIGW-Call-Occurrence` (always), in capture and in replay.
  - The case key is `case_key_for(case_id, attempt)` in `capture_outcomes.py`, and
    `current_case_key()` in `benchmarks/case_context.py`.
  - The occurrence counts the logical calls of one (case key, lane, request digest). It is taken once,
    when the call is first sent, and it is never given back. Transport retries reuse it.
  - A tool call takes its occurrence in `_executed`, before the tool runs.
  - Capture and replay take the occurrence from the run's tally. A replay with no tally bound fails
    loudly (`RuntimeError`) and sends nothing. The occurrence-0 fallback is removed.
  - `CaptureTally.reserve` and `release`, the slot fields, and the headers `X-AIGW-Capture-Occurrence`
    and `X-AIGW-Replay-Occurrence` are removed.
  - D2 is removed: `_lost()` counts every outcome that is not `stored`.
- **Q23, local capture.** `local.py` sets `URL4_LOCAL_RUNTIME=1` on every run env it builds. The
  marker is listed in `job_env.WRITTEN_BY_APP`. It reaches `RequestScope.local_runtime`, and
  `_bind_frozen_copy_mode` sets `CaptureTally.local`. A local capture is `partial` with reason
  `local`.
- **Q28, provenance.** `screamingface_engine.__version__` comes from the installed package metadata.
  `seal_frozen_copy` posts `{"provenance": {"engine_version": __version__}}`.
- **README.** The capture and replay paragraphs name the new headers, the occurrence rule, the
  `local` reason and the seal version.

### Can the sync surface replay?

No. Design §5.1 allows the run route only. The mount routes (`rest/mounts.py`, `_validated`) and the
local eval path (`local.py`, before `bind_sync_request`) refuse `X-Replay-Frozen-Copy` with 400
`capture_unsupported` before anything is bound. The tally is bound in one place only:
`runner/executor.py` (`_drive`). So the fallback was reachable only from tests that drive the
connector directly. `test_frozen_copy_unsupported_surfaces.py` covers both refusals.

### Commits (branch `OME-1435-e14-b3-engine-frozen-copy`, local only)

- `af374b82a` fix(screamingface-engine): key each frozen-copy call by case and occurrence (Q27)
- `e1201e692` fix(screamingface-engine): a local frozen-copy capture is partial (Q23)
- `65b5e0d68` fix(screamingface-engine): seal a frozen copy with the engine version (Q28)
- `231d73db2` docs(screamingface-engine): describe the call key, local capture and seal version
- `2922b6f5b` docs(work): record the B3 review round in the ledger
- `9cdda82ed` fix(screamingface-engine): count replay occurrences in the run tally only (Q27)
- this ledger commit

### Approved test edits (2026-10-12)

First round (approved by the owner):

- `test_capture_outcomes.py`: deleted `test_slots_are_reserved_in_order_and_given_back`,
  `test_slots_are_kept_per_lane_and_per_digest`,
  `test_giving_back_a_slot_that_was_never_reserved_does_nothing`,
  `test_a_failed_slot_is_given_back_without_freeing_a_later_one` and
  `test_given_back_slots_are_taken_again_lowest_first_then_trimmed`.
- `test_capture_outcomes.py`, `test_capture_status_rule`: the two D2 rows (`error` then `stored` at
  the same request, for chat and for tool) now expect `partial` with `{"error": 1}`.
- `test_frozen_copy_overlap.py`: deleted (its two tests were the approved deletions and nothing else
  was in the file).
- `test_frozen_copy_calls.py`: the three `3e5ee45eb` tests use `X-AIGW-Call-Occurrence` and check
  each task's value in order. Two of them record the value when the request ARRIVES at the gateway,
  before the barrier. The barrier answers the parked requests in a different order, so the order
  of the answers is not the order of the tasks.

Second round (approved by the coordinator, 2026-10-12):

- `test_frozen_copy_normal_run.py`: imports `CALL_OCCURRENCE_HEADER` and `CASE_KEY_HEADER` in place of
  `REPLAY_OCCURRENCE_HEADER`; the e14 header set uses them; `tally.slots == {}` becomes
  `tally.occurrences == {}`.
- `test_frozen_copy_occurrence.py`: the header is `X-AIGW-Call-Occurrence`. Inverted:
  `test_a_failed_answer_does_not_move_the_counter` became `test_a_failed_answer_still_moves_the_counter`
  (`["0", "1", "2"]`), and `test_a_tool_lookup_miss_does_not_move_the_counter` became
  `test_a_tool_lookup_miss_still_moves_the_counter` (`["0", "1"]`). Replaced:
  `test_a_run_without_a_tally_still_asks_for_the_first_answer` became
  `test_identical_replay_calls_take_occurrences_0_and_1_under_the_run_tally`, which binds the run's
  tally (the run path) and expects `["0", "1"]`. Added: `test_a_replay_call_with_no_bound_tally_fails_loudly`.
- `test_frozen_copy_replay_review.py`: the header is `X-AIGW-Call-Occurrence`. Inverted:
  `test_a_reserved_slot_is_given_back_when_the_call_does_not_succeed` became
  `test_an_occurrence_is_never_given_back_when_the_call_does_not_succeed` (`["0", "1", "2"]`, and
  the counter stands at 3).

### New tests

- `tests/unit/test_frozen_copy_call_key.py` (8): capture and replay send one key sequence; two
  concurrent cases each take occurrence 0; transport retries reuse the occurrence; a new logical call
  takes the next one and never gives it back; gathered tool calls take values in task order, also
  when the second Tavily call finishes first; the grading key and the empty key; the Attempt 2 key;
  the case id keeps its type.
- `tests/unit/test_frozen_copy_review_round.py` (6): an unstored error is not forgiven; a local
  capture is `partial` with reason `local`; a hosted capture is unchanged; the local marker reaches
  the scope; the executor binds the marker; the seal sends the engine version.
- `test_frozen_copy_occurrence.py`: `test_a_replay_call_with_no_bound_tally_fails_loudly` (1).

### Gates (`run_gates.py screamingface-engine --base refs/e14-backup/pre-phase2-2026-10-12/OME-1045-e14-b2-engine-tavily-cache`)

- Without `--skip-append-only`: FAILED. The check flags exactly the eight approved files
  (`test_cache_policy_threading.py`, `test_failure_classes.py`, `test_queue_admission.py`,
  `test_terminal_error_detail.py`, `test_e2e_compose_flow.py`, `test_run_control_resilience.py`,
  `_fakes.py`, `test_answer_seed_threading.py`). The B3 edits are not flagged, because the base
  holds none of these files.
- With `--skip-append-only`: `ALL GATES GREEN`. Steps: ruff check, ruff format --check, pyright,
  `check_layering.py`, pytest (`-n auto`, coverage `--cov-fail-under=80`).
- Unit (run directly): 4872 passed, 54 skipped, 0 failed.
- Integration (run directly): 38 passed, 40 skipped.

### Deviations

- The plan says to remove the unreachable `0 if _tally is None` branch in the connector. The capture
  branch is removed. The replay branch was reachable only from tests that drive the connector with no
  tally bound. The owner's round-2 instruction removed it too, and a replay with no tally now fails
  loudly.
- `FrozenToolResults.lookup` and `store` take `case_key` and `occurrence` as arguments. The
  `_read` helper is merged into `lookup`, because the release it existed for is removed.
- The plan leaves the field name open. `RequestScope.local_runtime` is the chosen name.
- The marker `URL4_LOCAL_RUNTIME` is listed in `WRITTEN_BY_APP`, because the job-env contract test
  requires every App-written key to be listed there.
- `create_local_app` builds `run_env` in one dict expression. Three statements exceeded the
  `PLR0915` limit (26).
- Two comments and the module docstring in `test_capture_outcomes.py` now describe the new rule.
  They change with the approved rows. The docstrings and comments of the other approved files
  changed in the same way.
- The two concurrent tests in `test_frozen_copy_calls.py` record the occurrence at gate arrival
  (helper `_arrivals`). This goes beyond the header rename the owner approved, and the reason is
  given under "Approved test edits".

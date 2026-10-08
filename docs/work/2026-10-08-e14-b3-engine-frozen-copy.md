---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
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

# F-B3 — engine: capture mode and replay mode (frozen copy)

- **Worktree:** `.claude/worktrees/e14-b3-engine-frozen-copy` · **Branch:** `e14-b3-engine-frozen-copy`
- **Base:** `e14-b2-engine-tavily-cache` · **Stack:** `screamingface-engine`
- **Design:** `02-frozen-copy-design.md` §5, §9 (binding). Rules: `00-common.md`.
- **Reference only:** branch `e14-old-b3-cache-replay` (worktree
  `.claude/worktrees/e14-b3-engine-cache-capture-replay`) built the old cache-revision design. Reuse its
  GENERIC pieces under new names, by reading and adapting the code, not by cherry-picking commits:
  the header → job env → `RequestScope` plumbing (`request_scope.py`, `job_env.py`, `runner/main.py`,
  `rest/routes.py` incl. the start-route echo, `ports.py`, `adapters/*`, `runner_queue.py`, `local.py`),
  the run-scoped tally (`replay_outcomes.py`: ContextVar, `request_digest`, D1 cancelled/crashed →
  error, D2 digest forgiveness), the executor binding and the always-written summary for special runs,
  and the failure-code declarations (engine + SDK mirror + the two exact-set tests).
  Do NOT carry over anything cache-revision specific (`X-Cache-Replay`, `cache-revision`, `only-if-cached`,
  `cache.revision`, `cache.reproducible`, `cache.replay`, the revisions pre-check, `replay_cache_miss`,
  `unknown_cache_revision`).

## Files (expected)

`capture_outcomes.py` (new, adapted tally), `request_scope.py`, `job_env.py`, `runner/main.py`,
`runner/executor.py`, `rest/routes.py`, `ports.py`, `adapters/inprocess.py`, `adapters/queue_runner.py`,
`runner_queue.py`, `local.py`, `world/connector.py`, `world/web_tools.py`, `error_text.py`,
`benchmarks/contract.py`, `packages/screamingface/src/screamingface/_report_primitives.py` (SDK mirror of the
two codes), `README.md` (capture and replay section). New tests under `tests/unit/`.

## Decisions (pinned)

- **Headers / env / scope:** `X-Capture: true` ↔ `URL4_CLOUD_CAPTURE=1` ↔ `RequestScope.capture: bool`;
  `X-Replay-Frozen-Copy: <uuid>` ↔ `URL4_CLOUD_REPLAY_FROZEN_COPY` ↔ `RequestScope.replay_frozen_copy: str | None`.
  Both present → 400 `malformed_header`. A non-UUID replay value → 400 `malformed_header`. The start
  response (202, sync result, 202 fallback) echoes the accepted header.
- **Tally (`capture_outcomes.py`):** modelled on the old `replay_outcomes.py`. Fields: `mode` (capture|replay),
  `frozen_copy_id`, outcomes with `lane` (chat|tool), `status` (stored|failed|refused|missing|error),
  `digest`. `status()` → `complete` iff mode capture, open ok, seal ok, and every outcome is `stored`
  after D2 forgiveness. Replay keeps per-digest occurrence counters (successful answers received).
- **Open / seal:** in the executor's `_drive`, around the run steps: `POST /v1/frozen-copies` before the first
  step (capture mode), `POST /v1/frozen-copies/{id}/seal` after the steps (also on a failed run; never on a
  cancelled one — a cancelled run is `partial` and stays open). Use the connector's gateway client and
  `_headers(scope)`. Open or seal failure → reasons `open` / `seal`.
- **Chat in capture mode:** add `X-AIGW-Frozen-Copy: <id>`; read `X-AIGW-Capture` from every response
  including errors (`missing` when absent). Raised errors still record the header value they carry.
- **Tool results in capture mode:** in `web_tools.append_tool_results`, for each result string returned by
  `_execute_tool` (before truncation), `POST …/tool-results` with the same description the Tavily cache uses
  (`search_description`/`fetch_description`; for a tool without a description builder, `{"tool": name,
  "arguments": args}`) and the string. 5 s timeout; failure → `failed`, never raises into the tool loop
  (except `CancelledError`).
- **Chat in replay mode:** path `/v1/frozen-copies/{id}/chat/completions` instead of `/v1/chat/completions`,
  header `X-AIGW-Replay-Occurrence: <n>` from the tally's counter for this body's digest; no cache body
  field, no `max-age` re-issue. A 200 → accounted as a cache hit ($0; use the existing served-from-cache
  accounting path). A 404 with `detail.code` `frozen_copy_miss` / `frozen_copy_unavailable` →
  `ResolutionError(code=<that code>, permanent=True)`. Any other status → handled as today (it is the
  captured original error).
- **Tool calls in replay mode:** never call Tavily and never need a Tavily key; `POST
  …/tool-results/lookup` with the description and the occurrence header; 200 → the result string; 404 →
  raise the `frozen_copy_miss` failure so the case fails (re-raised by `_execute_tool`, as the old B3 did).
- **Summary:** capture runs always write `capture.frozen_copy_id`, `capture.status`,
  `capture.partial.<reason>` (omit zeros); replay runs always write `capture.replay = <id>`. Same emission
  rule the old B3 used for replay runs.
- **Failure codes:** `frozen_copy_miss`, `frozen_copy_unavailable` in `error_text.py`, `benchmarks/contract.py`
  and the SDK mirror. Approved existing-test edits (record in the ledger as before): add the two codes to the
  exact sets in `test_failure_classes.py` and `test_terminal_error_detail.py`; add `capture`/`replay` params to
  fake `schedule` signatures; regenerate `tests/unit/data/cache_hit_contract/run_events.json` only if the
  normal-run bytes change (they must not: a normal run writes nothing new).

## TDD list (risk order)

1. `replay_mode_never_calls_tavily_or_the_normal_chat_route` (MockTransport records every URL).
2. `capture_mode_sends_the_copy_header_on_every_chat_call_and_records_capture_status`.
3. `normal_run_is_byte_identical` (no new headers, no tool-result posts, no new summary attributes).
4. `capture_status_rule` table: all stored → complete; any failed/refused/missing → partial; open fail;
   seal fail; error forgiven by later same-digest stored; cancelled call → partial.
5. `tool_results_posted_before_truncation_including_failure_strings`.
6. `replay_occurrence_counter_per_digest` (identical requests get 0, 1, 2…).
7. `replay_404_miss_and_unavailable_fail_the_case_with_their_codes`; `tool_lookup_miss_fails_the_case`.
8. `replay_success_is_accounted_as_zero_spend`.
9. `headers_travel_header_env_scope` for both modes; both → 400; malformed uuid → 400; start echo.
10. `summary_always_written_for_capture_and_replay_runs`.
11. `open_and_seal_called_once_per_run_seal_on_failed_run_not_on_cancel`.

## Verify

`uv run .claude/scripts/run_gates.py screamingface-engine --base e14-b2-engine-tavily-cache` (with and without
`--skip-append-only`; list the approved edits).

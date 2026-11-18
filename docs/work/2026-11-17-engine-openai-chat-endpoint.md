---
ticket: OME-1963   # filed at PR-open on 2026-11-18, with OME-1964 (docs) and OME-1965 (repo), under epic OME-1297
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-11-17
finished:
---

# engine-openai-chat-endpoint — OpenAI-compatible chat endpoint on the Engine

## Intent

Users ask to use their url4 ensembles from OpenAI clients (SDKs and coding agents). The Engine
gets `POST /v1/chat/completions`, a dedicated chat run and a final-step endpoint for tools. The
spec is `docs/spec/2026-11-17-engine-openai-chat-endpoint/`.

## Planned changes

- Spec (10 files, four design review rounds) and plan are written:
  `docs/plan/2026-11-17-engine-openai-chat-endpoint.md`.
- Code files are listed by unit in the plan §2.

## Test plan

- 136 tests in 7 units (one pull request, ordered commits); see `docs/spec/2026-11-17-engine-openai-chat-endpoint/test-plan.md`.

## Acceptance

- The owner approved P1–P40 and P42 on 2026-11-17 (P33 and P41 withdrawn).
- The owner approved the plan on 2026-11-17 ("Plan approved"). Code started after that.

## Owner decisions at build start (2026-11-17)

- **S0:** plan approved.
- **S1:** option A. The unit gates run with `--skip-append-only`. The approval record for edits
  to existing tests is written at PR-open, and the full gates then run with no skip.
- **S3:** the owner allowed a small paid check with the OpenRouter key and a cheap model.

- **U2 questions (2026-11-17).** The owner chose: (1) add allow-list entries in
  `tests/unit/test_url4_executor.py` for `chat/recipe.py`, and keep the entry of U1 for
  `world/gateway_transport.py` (plan D7); (2) no new dependency: TC-5, TC-6 and TC-34 use a
  seeded generator, not `hypothesis` (plan D8).

## Build log

- **Base.** The branch moved forward from `8530a9d75` to origin/main `07b49059f` (fast-forward,
  20 commits, before the first code change). No commit of that range changes
  `world/connector.py`. The `[existing path:line]` tags of the spec refer to `8530a9d75`.
- **S3 result (2026-11-17, 8 calls, about 0.03 USD, direct to OpenRouter).** Models:
  `anthropic/claude-haiku-5.5` and `deepseek/deepseek-v4.1-flash-1017`.
  - Final-step message layout (two `system` messages first; a `user` message after a `tool`
    message; two `user` messages in sequence): HTTP 200 on both models. The first turn gives a
    tool call. The second turn gives the answer.
  - Provider search (`plugins: [{"id": "web"}]`) together with client function tools: HTTP 200
    on both models. A tool question gives a tool call. A web question gives an answer with
    citations.
  - Limit: the calls did not go through the AI gateway. Stop point S4 (manual run on the local
    stack) covers that path.
- **U1 list (plan D6).** The script found 35 existing test files that refer to a moved name
  through `world.connector` (the estimates were 18 + 5). Source files: `world/classification.py`
  (six imported names). Four more source files name a moved function in a comment only.
  The list is in the U1 section below when the unit ends.

## U1 — shared gateway round trip (done 2026-11-17)

- **Commits:** `3030845cf` (characterization tests GT-1, GT-2, GT-3, GT-4, GT-7; 33 cases, green
  on the code before the move) and `d616e3993` (the move, GT-5, GT-6, GT-8).
- **Method.** A script moved 61 top-level names (63 source segments, about 1,140 lines) with no
  change of a function body. A second script compared each definition before and after: each
  moved body is identical; each kept body is identical apart from the `gateway_transport.`
  prefix and three lines that the formatter wrapped. `connector.py`: 2,096 → 787 lines.
  `gateway_transport.py`: 1,387 lines.
- **New in the module:** `timeout_headers()` (also used by `classification.py`, which built the
  same two headers) and the public entry `round_trip`.
- **Golden values:** the same before and after the move. In the two characterization files,
  only the patch target of `_wait_to_retry` changed.
- **Gates:** `run_gates.py screamingface-engine --base origin/main --skip-append-only` → ALL
  GATES GREEN (ruff, format, pyright, layering, pytest with coverage).
- **Existing tests that changed (35 files; for the approval record at PR-open).**
  In each file, only the patch target or the import of a moved name changed
  (`connector` → `gateway_transport`), with these two exceptions:
  `tests/unit/test_url4_executor.py` got one allow-list entry for the new module (it imports
  url4, as `connector.py` does), and the pre-commit formatter removed one blank line in
  `tests/unit/test_model_activity_stream.py`.
  - `tests/integration/test_gateway_failure_report.py`
  - `tests/unit/inspect/test_local_task_frames.py`
  - `tests/unit/test_admission_report_classification.py`
  - `tests/unit/test_admission_transport_policy.py`
  - `tests/unit/test_aigateway_connector.py`
  - `tests/unit/test_ambiguous_retry_pricing.py`
  - `tests/unit/test_cache_hit_retry_pricing.py`
  - `tests/unit/test_candidate_call_retry.py`
  - `tests/unit/test_classification_endpoint.py`
  - `tests/unit/test_connector_deadline.py`
  - `tests/unit/test_connector_deadline_exceeded.py`
  - `tests/unit/test_empty_gateway_response.py`
  - `tests/unit/test_frozen_copy_ambiguous.py`
  - `tests/unit/test_frozen_copy_call_key.py`
  - `tests/unit/test_frozen_copy_calls.py`
  - `tests/unit/test_frozen_copy_replay_accounting.py`
  - `tests/unit/test_frozen_copy_replay_unserved.py`
  - `tests/unit/test_gateway_error_relay_contract.py`
  - `tests/unit/test_logprobs_unsupported_mapping.py`
  - `tests/unit/test_logprobs_unsupported_observed.py`
  - `tests/unit/test_model_activity_stream.py`
  - `tests/unit/test_model_call_lifecycle_logging.py`
  - `tests/unit/test_mount_routes.py`
  - `tests/unit/test_observation_execution.py`
  - `tests/unit/test_observation_seam.py`
  - `tests/unit/test_operation_accounting_failure_boundaries.py`
  - `tests/unit/test_profile_carrier_retirement.py`
  - `tests/unit/test_provider_admission.py`
  - `tests/unit/test_provider_admission_edges.py`
  - `tests/unit/test_reply_logprobs_connector.py`
  - `tests/unit/test_retry_cost_of_intelligence.py`
  - `tests/unit/test_signal_accounting_connector.py`
  - `tests/unit/test_terminal_error_detail.py`
  - `tests/unit/test_unsupported_content_part_refusal.py`
  - `tests/unit/test_url4_executor.py`
- **Deviations from the plan.** (1) The script found 35 files, not 18 + 5 (plan D6 expected a
  difference). (2) Two files patched the module through `mock.patch.multiple("…connector")` and
  one through a script in a string; the first gate run found them, as the import rule intends.
  (3) In some test files the patch-target change removed a function-local import of
  `connector` and added one module-level import of `gateway_transport`.
- **Design review of U1 (Opus, read-only):** no blocker, no major, 5 minor, 6 nits. The reviewer
  compared each moved definition by syntax tree: all identical, none lost. Verdict: accept with
  fixes. Commit `962dfea65` applies them:
  - `_logged_round_trip` is now `round_trip` (pure rename, no alias), and the module has an
    `__all__`. The PRD now states that the other names keep their underscore.
  - Comments in six source files that named `connector.py::<moved name>` now name the new
    module (my first try at this did not change the files; the reviewer found it).
  - Two more existing tests changed, each by an added check: `tests/unit/test_request_scope.py`
    (the no-stored-scope check covers the new module) and `tests/unit/test_observation_seam.py`
    (the import check covers the new module). `tests/unit/test_model_activity_stream.py` and
    `tests/unit/test_observation_execution.py` follow the rename.
  - GT-5 asserts the accounting, usage and response reports; a second test covers the deadline.
  - Not done, by the rule "no body change in the move": shared constants for the two time-out
    header names (reader and writer both spell them).
  - Open: the allow-list comment in `tests/unit/test_url4_executor.py` names "guard retry",
    which the new module does not import. It is corrected in U2, which edits the same list.

## U2 — chat leaf (pure code)

- **Build.** Tiered build run `wf_f5a52542-b69`: 2 waves, 5 tasks (wire, recipe, input, result,
  views), then gates, an Opus design review (18 findings, none structural, none high) and one fix
  round. Gates after the fixes: Engine and repo stacks, ALL GATES GREEN.
- **Files.** New package `chat/` (`wire.py`, `input.py`, `result.py`, `recipe.py`, `views.py`,
  `_codec.py`); tests `tests/unit/test_chat_*.py`, `_chat_conversations.py`, `_chat_corpus.py`;
  one docstring line in `.claude/scripts/check_layering.py`.
- **Existing test that changed:** `tests/unit/test_url4_executor.py`, the allow-list entry for
  `chat/recipe.py` (plan D7), and the corrected comment of the U1 entry.
- **Review points that I settled from the approved spec text** (the spec now says each one):
  - *Unknown final form (F2).* A root that is not a final form, or that names a binding with no
    source, is `recipe_invalid` in all cases (CC-S13). A root that names a real step which the
    check cannot classify runs as built with no tools, and is `recipe_not_supported` with tools
    (TC-S9). The two rules do not overlap.
  - *Unknown keys in messages (F4).* The spec says "the client messages, with no change". The
    first build dropped keys that the models do not declare (for example `reasoning_details`,
    `cache_control`). Now a message, a content part, a tool call and a tool definition keep
    unknown keys, and the final step sends them. Unknown top-level request fields are still
    ignored (ans:Q14). The text view never shows an unknown key.
  - *Join of text parts (F16).* Text parts join with a line feed, as the gateway joins them.
  - *Corrective loop (F1).* Refused at any depth, not only at the final position (CC-S14).
- **Commit:** `c5d5630dc`. Gates: Engine and repo stacks, ALL GATES GREEN.
- **Gate hang (once).** One Engine gate run stayed silent for 25 minutes with all test workers
  idle, while another session ran a gate in another worktree. I stopped it. The same suite then
  passed twice (10,009 passed). I could not reproduce the hang, so its cause is not known.
- **Gateway facts for U6 (scout, read-only).** The gateway refuses an unknown TOP-LEVEL key of a
  chat request with 400 `unsupported_parameters` (for example `parallel_tool_calls`). It
  accepts `tools` and `tool_choice` only on a provider with function-calling rules (OpenRouter
  has them). It does not check keys inside messages, parts, tool calls or tool definitions, so
  they go to the provider.
- **Allow-list (plan D7), applied to the same case in later units.** A new world adapter of this
  feature that registers a route on the node (`world/chat_turn.py` in U3, `world/chat_final.py`
  in U6) gets one entry in the url4 allow-list test, as `world/combine.py` and `world/branch.py`
  have. Each entry goes in the approval record.
- **Carried to later units.** U4: the message for a benchmark-linked expression (CC-S15); a final
  step on a route that is not a model must fail closed (the catalogue lookup of the route does
  this). U6: check what the gateway does with unknown keys in messages before the final step
  sends them.

## U3 — run shape, chat-input store, handler

- **Two gaps of the spec, found by the planner, settled by me (engineering level; the spec now
  says each one in `erd.md`).**
  - *Facts of the final step with no tools.* The handler takes `final_step`, `finish_reason`
    and `abstain_reason` from the attributed operation of the final binding in the Candidate
    Invocation envelope. The other choice (the shared outcome of all model calls) would report
    `stop` for a truncated synthesizer when its members gave `stop`.
  - *Delete operation.* It goes on `BoundedBlobObjects`, the filesystem backend, the S3 backend
    and the adapter for put/get-only backends (forward if the inner backend has it). No existing
    test changes. The spec named an in-memory backend that the source does not have.
- **Pre-check of plan step 8.** One more pin exists:
  `tests/unit/test_combine_wiring.py::test_factory_installs_the_registry_the_default_app_serves`
  asserts exactly one call of `install_combine_runtime`. It does not change; the design follows
  it (the routes are installed once, in `build_world`).
- **Run shape pins.** `test_job_env_contract.py` and `test_schedule_time_admission_rest.py` do
  not pin the full set of run shapes, so they do not change.
- **Approval record: existing test files that changed in U3.** Each change stays inside the approved
  scope.
  - `tests/unit/test_terminal_error_detail.py`: `ALLOWLISTED_CODES` gets `chat_input_unavailable`,
    `chat_input_invalid` and `final_step_ambiguous`.
  - `tests/unit/test_combine_wiring.py`: CR-25 replaces
    `test_a_world_without_benchmarks_has_no_combine_route` in place, because each gateway world now
    has the routes. `test_factory_installs_the_registry_the_default_app_serves` does not change.
  - `tests/unit/test_url4_executor.py`: one allow-list entry for `world/chat_turn.py` (plan D7a).
  - Six schedule-port fakes get the keyword `chat_input: str | None = None` and nothing else:
    `tests/unit/_fakes.py` (RecordingJobRunner), `tests/unit/test_answer_seed_threading.py`
    (_SeedRecordingRunner), `tests/unit/test_cache_policy_threading.py` (_CacheRecordingRunner),
    `tests/unit/test_queue_admission.py` (_AtCapacityRunner),
    `tests/integration/test_e2e_compose_flow.py` (MockRunnerJobRunner),
    `tests/integration/test_run_control_resilience.py` (_RecordingJobRunner).
- **Build.** Tiered build run `wf_01ccebc6-94b` (28 agents). Design review: 16 findings, none
  structural; the fix round resolved 12. I settled two more: a storage failure during the read
  of the input gives `chat_input_unavailable` marked as not permanent (CR-S7), and a run with no
  single attributed final operation reports `stop` and no `final_step` (erd §2.4).
- **Commit:** `92a612347`. Gates: Engine and repo stacks, ALL GATES GREEN.
- **Deviation from plan U3 step 5.** The turn target, the chat-run marker and the `dispatch_direct`
  call are in `world/chat_turn.dispatch_chat_turn`, not in `runner/executor.py`. Reason: the task
  rules say not to grow the long `executor.py`. The layering gate passes. `dispatch_chat_turn` takes
  `node: object` and repeats the executor's 'needs a url4 node world' check.
- **Behaviour change for the PR body and the deploy notes (CR-S19).** `build_world` now installs the
  combine, branch and chat routes in each gateway world, also in the App's mount-table world. A
  world file that puts a `[data]` mount on an internal route path (for example
  `/ensemble/combine/v1`, a branch route or `/ensemble/chat/v1/turn`) and has no Benchmarks now
  fails the world build with `WorldConfigError`, so the App does not start. Before U3 such a world
  was accepted. `test_a_data_mount_on_an_internal_route_fails_the_world_build` pins this only for
  the chat route.

## U4 — REST route, not streamed

- **Planner questions (2026-11-18).** The planner found nine cases. I settled seven from the
  spec intent; `prd/chat-completion.md` §3.4 lists them (error `type` names, retry headers of
  the errors outside the terminal table, the large-parse 429, the model lookup codes, "runs as
  built" with no tools, two metric series, the OpenAPI tag).
- **Two questions are with the owner (asked 2026-11-18, no answer when the build started):**
  1. *CLI tests.* The server subclass of CC-S37 means that `cli.py` no longer calls
     `uvicorn.run`. Three existing tests replace `uvicorn.run`
     (`tests/unit/test_app_factory.py::test_prod_cli_serves_the_env_wired_factory`, and two in
     `tests/unit/test_cli_local_mode.py`). My proposal: `cli.py` gets one seam `_run_server`,
     and the three tests replace that seam and check the same arguments. Until the answer,
     `cli.py` and CC-39 are NOT built; the drain object and the route's reaction to it are.
  3. *`tests/unit/test_mount_routes.py` (found by the second planning pass; NOT yet seen by the
     owner).* That file uses `/v1/chat/completions` as the path of its example mount. With the
     real route in place, two of its tests fail (the OpenAPI check and the wrong-method check).
     Edit made for the build: those two tests use the other example mount of the same table,
     `/v1/benchmarks/data/foo` (three strings). Nothing else changes. **The owner must confirm
     this in the approval record.** Related risk for the deploy: a deployed world file that
     mounts something on `/v1/chat/completions` would now fail the mount collision check. No
     world file in the repo does this; the deployed files must be checked.
  2. *No cost-usage frame.* Default built for now: 200, usage 0/0/0, `cost_usd: null`, one
     warning line. It is one function and one test, so another answer is a small change.

- **Build of U4.** Tiered build run `wf_74028057-1f4` (19 agents). The planner put the failing
  tests in their own wave. The workflow then read those expected failures as a broken wave, and
  its repair step (one Opus agent) wrote all route modules to make them pass. The run stopped
  there with a bookkeeping error ("expected red, got green"). I checked the result: 176 tests
  of U4 green. The planned unit tests of each stage module were not written; the black-box
  tests cover them.
- **New test dependency.** `openai==2.54.0`, not the newest line (3.x). Reason: 3.x needs
  `httpx2`, and when `httpx2` is installed, Starlette's test client uses it for ALL Engine
  tests; two existing tests then fail the type check. 2.54.0 (2026-08-11) is the newest release
  that uses `httpx`. Follow-up: move to 3.x when the Engine test stack moves to `httpx2`.
- **Design review of U4 (Opus):** accept with fixes; 3 major, 6 minor. Fix round in progress
  when this was written: unexpected errors keep the OpenAI envelope (500 `internal_error`, no
  retry); the input record is released after the blob write; large bodies are parsed off the
  event loop; a disconnect watch that cannot swallow a cancel; the run is stopped when the queue
  answer is not confirmed; one log line per request; test gaps.
- **Rules added by me in the fix round (for the owner to confirm):** a request that holds one of
  the 4 large-parse places must send the rest of its body in 30 s, or it gets 408
  `request_timeout`; the metric outcome `client_disconnected` (status label 499).
- **Fix round of U4: done.** All ten points applied (new tests in
  `test_chat_completions_hardening.py` and `test_chat_completions_cancel.py`; the cancel test
  failed on the old polling code at run 45 of 200). The request log line names the run by its
  trace id and never prints the topic.
- **Commit:** `b8f022ba1`. Gates: Engine and repo stacks, ALL GATES GREEN.
- **Existing test that changed in U4:** `tests/unit/test_mount_routes.py` (three strings, see
  above). NOT built yet: `cli.py` and CC-39.
- **FOLLOW-UP outside this feature (not changed here).** The reviewer showed that
  `Request.is_disconnected()` of Starlette can swallow a task cancel (2 of 20 tries). The shared
  helper `wait_terminal_or_gone` in `rest/routes.py`, which `GET /?q=` and the mounts use,
  polls it in a task and awaits that task in a `finally`. So that helper can hang on a cancel.
  This can also be the cause of the one gate hang of 2026-11-17. It is existing behaviour on
  `main`; a bug issue is proposed, not filed.

## U5 — Streamed response

- **Scope.** Tests ST-1 … ST-9 and ST-11 … ST-13 of `prd/streaming.md`. ST-10 (a streamed
  tool-call answer) is U6. `cli.py` is not changed (the owner question on the three CLI tests is
  still open).
- **Design (owner decision: buffered stream).** The route answers 200 `text/event-stream` when the
  run is scheduled. It sends the comment `: keep-alive` each `chat_keepalive_s` while the run
  works. Then it sends the full answer as chunks and `data: [DONE]`. There is no token relay from
  the gateway.
- **Modules.**
  - `chat/sse.py` (pure, no I/O): `KEEP_ALIVE`, `DONE`, `data_line` (ASCII-only JSON on one
    line), `error_event`, `frames`, `ChunkMeta`. `frames` also builds the tool-call chunk (one
    chunk, full arguments), so U6 adds no frame code.
  - `rest/chat_stream.py`: `ChatStream` (the lines of one stream), `ChatStreamResponse` (its
    `__call__` runs the cleanup and the observation on every exit, also when the body never
    started), `StreamPlan`, `stream_answer`.
  - `rest/chat_wait.py`: `RunWait` races the scan against the time limit and the drain, in steps
    of `chat_keepalive_s`. It does not read `receive()`.
  - `rest/chat_answer.py`: `read_result`, `completion_parts` and `completion_id` are shared by the
    plain and the streamed answer.
  - `rest/chat_body.py`: `ChatBody` keeps `stream` and `include_usage`. Neither goes into the
    CHAT_INPUT record.
  - `config.py`: `chat_keepalive_s` (default 15, must be more than 0; env
    `URL4_CLOUD_CHAT_KEEPALIVE_S`).
  - `rest/chat_completions.py`: after the schedule, it chooses the streamed or the plain answer.
- **Rules set in the build.**
  - One reader of `receive()`. Starlette's `StreamingResponse` watches the disconnect, so the
    streamed path does not start the U4 watcher task.
  - An error before the stream starts keeps the U4 JSON envelope and status. An error after the
    start is one SSE error event and no `[DONE]`.
- **Rules added in the build (for the owner to confirm).** A streamed request is counted, timed
  and logged once, at the end of the stream. Its log line has `status=200` (the status that was
  sent) and the true outcome; a disconnect has the outcome `client_disconnected`. The plain path
  logs the same disconnect with the status label 499.
- **Tests (new files).** Unit: `test_chat_sse.py`, `test_chat_sse_sdk.py` (chunk types of
  `openai` 2.54.0), `test_chat_stream_route.py`, `test_chat_stream_cleanup.py`,
  `test_chat_stream_support.py`, and the support module `_chat_stream.py`. Integration:
  `test_chat_stream_disconnect.py` (ST-8: a real uvicorn server on a free port of 127.0.0.1, a
  real HTTP client and a real TCP close).
- **Test support that changed.** `tests/unit/_chat_app.py`: `chat_app` gets the keyword
  `chat_keepalive_s` (default 15.0) and passes it to `Settings`. No existing test was edited.
- **Design review of U5 (Opus).** 11 findings, all low and LOCALIZED-FIX (F1–F11). Fix round:
  one settle step for the plain and the streamed wait (`settle_wait`), one timeout rule in
  `chat_wait.py`, no error round trip in `chat_stream.py`, the observer is attached to the stream
  response by the route, the disconnect code comes from `WAIT_ROWS`, the `ChatBody` stream flags
  are required, the OpenAPI entry lists the event stream and `stream_options`, and this entry.
  Not changed: the place of the `StreamPlan` build, the status label of a streamed disconnect
  (owner question), the refusal rule that `chat/sse.py` and `rest/chat_answer.py` both write
  (different wire shapes), and the self-contained fakes of the ST-8 test (local practice of
  `tests/integration`).
- **Known limit (review F10).** On an ASGI 2.3 server (uvicorn with h11 or httptools today), a
  disconnect cancels the stream at once. On an ASGI 2.4 server, Starlette sees the disconnect
  only at the next write, so the run can be stopped up to `chat_keepalive_s` (15 s) late.
- **Commit:** pending (the main session fills this in).
- **Gates:** pending.

- **U5 commit:** `0386fe2f2`. Gates: Engine and repo stacks, ALL GATES GREEN. Design review:
  11 low findings, none structural. Open point for the owner: a streamed request logs the
  status that was sent (200), also when the client disconnects; the plain path logs 499 for the
  same outcome.

## U6 — Final-step endpoint and tools

- **Build.** Tiered build run `wf_1ee76f8e-b46` (16 agents): the final-step endpoint, the route
  rules for tools, the installer, the handler re-point, the tool-call answer (plain and
  streamed), the SDK two-turn tests. Gates green. Design review: 14 low findings, none
  structural; the fix round resolved 8.
- **Modules.** New: `world/chat_final.py`, `world/chat_marker.py`, `rest/chat_tools.py`,
  `chat/_recipe_types.py` (url4-free types and messages, moved out of `chat/recipe.py` to keep
  it under 500 lines). Changed: `world/chat_turn.py`, `world/factory.py` (one config object
  for the world and the installer), `chat/recipe.py` (`final_model_steps`, `FinalModelStep`),
  `chat/wire.py`, `chat/sse.py`, `rest/chat_body.py`, `rest/chat_model.py`,
  `rest/chat_completions.py`, `rest/chat_answer.py`.
- **Rules added by me after the review** (`prd/tool-calls.md` §3.6 lists them with the known
  limits): with tools, a final step whose binding name is not unique at its scope is refused
  with 400 before the run; a model id with `~` (a colon in the real id) is tested end to end
  with tools.
- **Known limits, written in the spec §3.6:** the App check and the run check of the search rule
  can differ when an operator declares a route flag that is not the default (the client then
  gets 502 `internal_error`); no picture admission for the re-pointed final step; no answer seed
  on the final-step request; the error translation block is repeated from the model endpoint.
- **Existing test that changed in U6:** `tests/unit/test_url4_executor.py`, one allow-list entry
  for `world/chat_final.py` (plan D7a).
- **Commit:** `aa185c48d`. Gates: Engine and repo stacks, ALL GATES GREEN.
- **S3** (the paid provider check) passed before this unit; see the build log.

## Live check through the local stack (2026-11-18, after U6)

- **Why.** The S3 check went direct to OpenRouter. The tests of the build use a fake gateway,
  which does not apply the request rules of the real gateway. This check closes that gap.
- **Setup.** The gateway and the Engine of this branch, started by hand on this machine (the
  gateway on port 9105 with a COPY of the local playground database and the OpenRouter key from
  the local key file; the Engine in local mode on a spare port). Client: the `openai` SDK. The
  services are stopped and the database copy is deleted. The local Engine of the owner on port
  9108 was not touched.
- **Result: 8 of 8 cases as designed**, about 0.03 USD in total.
  1. A model id, plain → answer, usage, cost, `final_step`.
  2. A one-model recipe with `web_search=false` → answer.
  3. A model id, streamed → chunks, then `[DONE]`.
  4. A Fusion (two members and a synthesizer), no tools → answer; usage is the ensemble sum.
  5. A model id with tools, two turns → a tool call, then the answer.
  6. A Fusion with tools (synthesizer on Claude Haiku 5.5), two turns → a tool call from the
     synthesizer, then the answer.
  7. A model id with tools, second turn streamed → the answer in chunks with usage.
  8. An unknown model id → 404 `model_not_found`, `x-should-retry: false`.
- **Facts seen.**
  - *Cost of the default web search.* The same one-word question cost 0.0071 USD with a bare
    model id (search on by default, 576 prompt tokens) and 0.000012 USD with
    `web_search=false` (16 prompt tokens). This follows the owner decision "on by default".
  - *`final_step` is null when a member and the final step use the same route with the same
    parameters* (no tools). The Engine attributes an operation by route and parameters, so it
    cannot tell which call was the final one. `finish_reason` is then `stop`. With a different
    route or parameter for the final step, or with tools, `final_step` is present. This is an
    existing rule of the attribution; the docs page states it as a limit.
  - *Setup traps (not product defects).* The run half reads the gateway address from
    `url4.toml`, not from `URL4_CLOUD_LOCAL_AIGATEWAY_BASE_URL`. The gateway of today no longer
    reads the old "profile" credentials of the playground database; a connection must be made
    with `POST /v1/oauth/connections/api-key`.
- **Not done here:** the manual run with pi and opencode (stop point S4).

## U7 — Docs

- **Build.** Tiered build run `wf_0ce7d12e-6e1` (8 agents), then a fix round by one Opus agent
  (the run stopped at its review on one structural finding, see below).
- **Files.** `public-docs`: the page `src/pages/sf-client/guides/OpenAiApiPage.vue`, its route
  and navigation entry, the snippets `src/snippets/openai-chat/openai_sdk.py` and
  `candidate_url4.py`, `CLAUDE.md`. Engine: `README.md`, tests `test_chat_docs_example.py`
  (DOC-1), `test_chat_docs_page.py` (DOC-2), `test_chat_docs_candidate_url4.py`, and the shared
  test stack `tests/integration/_chat_sdk_stack.py`. Repo: `CONTEXT.md`, and two path filters
  in `.github/workflows/screamingface-engine-tests.yml`.
- **Structural finding of the review, settled by me.** The spec asks the page to show "a way to
  get the Candidate URL4 of a recipe from the SDK". The SDK has NO public call for this (checked
  twice). `report.candidates[name].url4` is the evaluation URL4, which the route refuses. The
  page shows the one public way: extract the `candidate` source of the evaluation URL4 with the
  public `url4` package (a tested snippet). So a user must run an evaluation first.
  **Follow-up for the owner:** a public SDK accessor for the Candidate URL4 of a recipe (an SDK
  change, outside this plan), or let the route accept an evaluation URL4.
- **Not verified:** the config keys of the pi and opencode examples (no source in this repo; the
  page says so). Stop point S4 checks them.
- **Gates:** Engine and repo stacks ALL GATES GREEN; `public-docs`: `npm ci`, `oxlint`,
  `eslint`, `npm run build` all pass.
- **Commit:** `8dbaa605b`.

## Final whole-branch code review (2026-11-18, ScreamingFace code reviewer, read-only)

- **Scope.** `origin/main..aa185c48d` (U1 to U6). 236 targeted tests green; the eight timing-based
  test files ran three times; probes of 7 recipes, 13 conversation shapes, 16 unusual bodies and
  7 path variants against the internal routes. The 43 changed pre-existing test files are
  exactly the lists of this ledger.
- **Verdict: no code defect in the units; NOT merge-ready because of one owner decision.**
- **BLOCKS PR-OPEN — owner decision needed: chat answers and the community cache.**
  A chat run uses the shared cache unless the client sends `Cache-Control: no-store` (owner
  answer Q15, "on by default", my recommendation at that time). The gateway then stores each
  model answer of the run in the global request cache, and each signed-in account can read the
  stored answers through `GET /v1/cache/entries` (the community cache; it shows answers, not
  prompts). The chat spec did not state this exposure when the owner answered. An agent session
  can put source code and tool-call arguments in those answers. The same reason made the owner
  delete the input record at the end of each request. Options: (a) the chat route does not use
  the shared cache by default, and a client opts in with `Cache-Control` (my recommendation
  now; one function and its tests change); (b) keep the default and make the gateway leave
  chat rows out of the community listing (a gateway change); (c) keep the default, with the
  exposure stated on the docs page. **The code today is as the owner decided (cache on).**
- **Commit of the last fixes:** `fa373a248`. Gates after it: Engine and repo stacks ALL GATES GREEN;
  `public-docs` lint and build pass.
- **Nonblocking, fixed in the last commit of the branch:** the re-point proof also runs in the
  App (a failing recipe now gets 400, not 502 after a queued run); the retryable 503 answers
  send `Retry-After: 5`; `chat_max_wait_s` must be positive; the docs page tells users to use
  `stream: true` for long recipes.
- **Nonblocking, recorded as accepted limits or follow-ups:**
  - A chat run does not pass through the IO gate, so a large recipe can send many gateway calls
    at one time. A Candidate Invocation of a Benchmark Case has the same shape today.
  - A caller at the limit of 24 runs pays one blob write and delete before each 429.
  - A result above the inline limit stays in the artifact store until its sweep (erd §1.2).
- **Not checked by any review (deploy checks for the PR body):**
  - Whether the hosted Envoy security policy covers the path `/v1/chat/completions`. If it
    does not, each hosted request gets 401 (the route fails closed).
  - The time limit of the hosted edge for a plain (not streamed) request. An edge time-out
    has no `x-should-retry` header, so an SDK then runs the ensemble again.
  - That no deployed world file mounts something on `/v1/chat/completions`.

## U8 — Owner decisions of 2026-11-18, and the drain wiring

- **Owner answers (2026-11-18, spec ledger Q33–Q35).**
  1. *Community cache.* "community cache must be on by default". Reason of the owner: the
     product is for benchmarks and evaluations; for these, a shared cache is good for cost and
     for reproducibility. So the blocker of the final review is closed by decision, with no code
     change. The docs page now states the fact and the opt-out (limit `shared-cache`:
     each signed-in account can read the stored answers; `Cache-Control: no-store` keeps a
     request out). DOC-2 checks that sentence.
  2. *Drain in `cli.py`.* "make the edits". Built in this unit (see below).
  3. *Slow large body.* First answer: 60 s, not 30 s. The owner then went back to 30 s (Q36,
     see the PR-open section), so the limit of the first build stays.
  4. *Existing bug on main* (`wait_terminal_or_gone`): the owner asked for a Linear bug ticket,
     a parallel worker and a PR. That is a different unit with its own worktree
     (`.claude/worktrees/wait-helper-cancel-hang`) and its own ledger; it is not part of this
     branch. Result: Linear bug OME-1962 and PR #1933 (branch
     `OME-1962-wait-helper-cancel-hang`, opened 2026-11-18). When it is merged, the rebase of
     this branch gets the new helper.
  - The owner did not answer the point on `tests/unit/test_mount_routes.py`. It stays open.
- **Drain wiring (CC-S37, test CC-39).**
  - `cli.py`: new seam `_run_server(app, *, factory, host, port)`. `_serve` and `_serve_local`
    call it in place of `uvicorn.run`, with the same arguments. It builds a `uvicorn.Server`
    subclass. On a stop signal, `handle_exit` calls `request_all_drains()` and then the handler
    of uvicorn. Each other server setting keeps the uvicorn default (the WS ping defaults of
    OME-890 have a test). A server that does not start gives exit code 3, as `uvicorn.run`.
  - **Existing tests that changed (owner-approved, Q34):**
    `tests/unit/test_app_factory.py::test_prod_cli_serves_the_env_wired_factory`,
    `tests/unit/test_cli_local_mode.py::test_local_resolves_the_real_local_app_factory` and
    `::test_the_real_local_server_binds_the_requested_port`. Each one now replaces
    `cli._run_server` and not `uvicorn.run`. No assertion changed.
  - **New tests.** `tests/unit/test_cli_server_drain.py` (5 tests: arguments and uvicorn
    defaults; the signal requests each live drain and then the normal shutdown; a second SIGINT
    forces the exit; exit code 3; a keyboard interrupt is a clean exit).
    `tests/integration/test_chat_drain_signal.py` (CC-39) with the helper
    `tests/unit/_chat_drain_server.py`: a server process started through `cli._run_server`, one plain and
    one streamed request that wait, a real SIGTERM. The plain request gets 503
    `server_restarting` with `x-should-retry: true` and `Retry-After: 5`; the stream gets the
    error event and no `[DONE]`; the process ends.
  - **RED evidence.** With the call of `request_all_drains()` removed, CC-39 failed with
    `TimeoutError` at the 20 s limit of the plain request (the request waited for its run).
    With the call, it passes in about 2 s.
  - **Design review (Opus): accept with fixes; no blocker, no major, 7 minor.** Applied: the
    handler of uvicorn runs also when the drain raises (`try`/`finally`, with a test); the unit
    tests use their own drain set, so they do not drain an App of another test module; the
    server of CC-39 binds port 0 and the test reads the port from the start line; the output
    pipe is closed; the docs sentence says that an answer can quote its prompt. The reviewer
    confirmed these facts: `_run_server` equals `uvicorn.run` for the two call sites (uvicorn
    0.52.3); uvicorn sends a response in flight before it closes the connection; the docs
    sentence on the cache is true (`GET /v1/cache/entries` of the gateway is not admin-gated;
    its rows have `response_json` and `prompt_hash`, no prompt text).
  - **Effect of the 60 s body limit on a rollout (for the owner).** The shutdown grace of the
    App pod is 45 s, with 5 s of preStop. A slow large upload can now take 65 s, so a rollout
    can cut it with a connection reset, not a 408. No run exists then, so it costs nothing. The
    comment in `deploy/helm/values.yaml` now names this case. Not changed:
    `terminationGracePeriodSeconds`.
  - **Commit:** `ce4abe5eb`. Gates after the last edit: Engine and repo stacks ALL GATES GREEN
    (with `--skip-append-only`); `public-docs` lint and build pass.
  - **Limit of CC-39.** The test starts the seam with a test App factory, not the two real App
    factories (they need a gateway and a queue). The unit tests prove that both start paths go
    through the seam.

## PR-open (2026-11-18)

- **Owner answers (spec ledger Q36–Q38).** The limit for a slow large body goes back to 30 s
  (commit "keep the 30 s limit"; the Helm values comment now says that the body read fits in
  the shutdown grace). The edit to `tests/unit/test_mount_routes.py` is approved. The parent
  epic is `OME-1297` (E8).
- **Rebase.** The branch moved from `07b49059f` to origin/main `033915757` (22 commits), with
  no conflict: no file of the branch changed on main. The Engine gates after the rebase: ALL
  GATES GREEN. The Engine Pipeline Atlas artifact was checked against the same range (owner
  rule): the range has nothing that the atlas covers, so only its meta line changed.
- **Linear.** A search of all 1,841 issues of the team found no ticket for this feature. Two open
  epics fit, and neither had sub-issues: `OME-1297` (E8, the endpoint) and `OME-1298` (E9, an
  IDE that uses it). The owner chose `OME-1297`, so no new epic was made. Filed under it,
  assigned to the owner's account, in the state In Progress: `OME-1963` (Engine),
  `OME-1964` (public docs, label `client-sf`), `OME-1965` (repo scripts and CI filter).
  The Linear MCP connector was not signed in; the owner chose the Linear CLI for this session.
- **Branch:** renamed to `OME-1963-engine-openai-chat-endpoint`.
- **Approval record:** `.claude/test-change-approvals/OME-1963.json` pins the 40 existing
  test files that changed (base blob and approved blob for each). With it, the gates run with
  no skip.
- **Mirrors:** three files in `docs/tasks/` (`2026-11-18-OME-1963-…`, `OME-1964`,
  `OME-1965`).
- **Now committed:** the spec, the plan and this ledger.
- **Not done:** stop point S4 (the manual run with pi and opencode), and the deploy checks
  (the PR body lists them).

## Outcome (state on 2026-11-18: the PR is open; the work is NOT closed)

- **Actual files:** 174 files against origin/main `07b49059f`: 64 under
  `apps/screamingface-engine/src` (new package `chat/`, new modules `rest/chat_*.py`,
  `world/gateway_transport.py`, `world/chat_turn.py`, `world/chat_final.py`,
  `world/chat_marker.py`, `artifacts/chat_inputs.py`, and edits listed in each unit section),
  111 under `apps/screamingface-engine/tests`, the docs page and snippets in `public-docs`,
  `CONTEXT.md`, the Engine README, one CI path filter, one line in
  `.claude/scripts/check_layering.py`, `pyproject.toml` and `uv.lock` (`openai==2.54.0`, dev).
- **Commits (local branch `engine-openai-chat-endpoint`, not pushed):** `3030845cf`,
  `d616e3993`, `962dfea65` (U1); `c5d5630dc` (U2); `92a612347` (U3); `b8f022ba1` (U4);
  `0386fe2f2` (U5); `aa185c48d` (U6); `8dbaa605b` (U7); `fa373a248` (final review fixes);
  `ce4abe5eb` (U8: the drain at the stop signal, the 60 s body limit, the cache note).
  The spec, the plan and this ledger are not committed (owner choice at the spec stage).
- **Gates:** after each unit and after the last commit:
  `run_gates.py screamingface-engine --base origin/main --skip-append-only` and
  `run_gates.py repo --base origin/main --skip-append-only` → ALL GATES GREEN; `public-docs`:
  `npm ci`, `oxlint`, `eslint`, `npm run build` pass. NOT run yet: the gates with no skip
  (they need the approval record of PR-open), and CI.
- **Deviations:** see each unit section. In short: U1 as a scripted move; 35 and then 43
  pre-existing test files changed (lists above); `openai` 2.54.0 and not 3.x; seeded generators
  and not `hypothesis`; the drain wiring in `cli.py` (CC-39) came last, as U8, after the owner
  answer; origin/main moved (21 commits on 2026-11-18), so a rebase is due before PR-open.
- **Open with the owner (in order):**
  1. CLOSED 2026-11-18 (Q33): the community cache stays on by default.
  2. CLOSED 2026-11-18 (Q34): built as U8.
  3. CLOSED 2026-11-18 (Q37): the edit to `tests/unit/test_mount_routes.py` is approved.
  4. The 408 limit is 30 s again (Q36). The owner saw the other added rules and did not object:
     usage 0/0/0 with null cost when a run has no cost-usage frame; `Retry-After: 5` on the
     retryable 503 answers; the refusal of a final step that is not unique.
  5. Follow-ups, not filed: a public SDK accessor for the Candidate URL4; picture admission for
     the final step; the IO gate for chat runs. The cancel weakness of the shared
     `wait_terminal_or_gone` helper on main is now its own unit (bug ticket and PR, by owner
     order).
  6. Stop point S4 (manual run with pi and opencode) and S5 (epic, Linear issue and sub-issues,
     branch rename, task mirror, approval record, PR).

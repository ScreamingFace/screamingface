# Plan: OpenAI-compatible chat endpoint on the Engine

Spec: [docs/spec/2026-11-17-engine-openai-chat-endpoint/](../spec/2026-11-17-engine-openai-chat-endpoint/00-overview.md)
Ledger: [docs/work/2026-11-17-engine-openai-chat-endpoint.md](../work/2026-11-17-engine-openai-chat-endpoint.md)

**Status:** approved by the owner on 2026-11-17 ("Plan approved"; S1 = option A; S3 = allowed
with the OpenRouter key and a cheap model). The build is in progress; see the ledger. The spec passed four design review rounds; its decisions P1–P40 and P42 are approved.

## 1. Approach

- **Base.** Branch `engine-openai-chat-endpoint`, worktree
  `.claude/worktrees/engine-openai-chat-endpoint`, on origin/main `8530a9d75`. Rebase on
  `origin/main` before the pull request opens.
- **One pull request** (spec ans:Q22). The seven units are separate commits in the order of §2.
  Unit U1 (the move) has no feature code in its commits, so a reviewer can read it alone.
- **Per-unit cycle.** Each unit follows the `sdlc-python` loop: ledger entry, RED tests that fail
  for the right reason, minimal GREEN code, refactor, gates, review, ledger outcome, commit.
  Test ids are the ids of the spec (`GT-`, `CR-`, `CC-`, `ST-`, `TC-`, `DOC-`).
- **Who builds.** The tiered build of the owner: the main session plans and reviews each unit,
  implementer agents write the code from a complete unit spec, and an independent design review
  checks each unit against the spec before the next unit starts. U1 is done in the main session,
  because it is a move that needs a line-by-line check.
- **Offline only.** No test and no build step calls a provider. Integration tests use a fake
  gateway. The two checks that need a live provider are stop point S3.
- **Gates.** After each unit:
  `timeout 1500 uv run --script .claude/scripts/run_gates.py screamingface-engine --base origin/main`.
  Units that touch `.claude/scripts/` also run the `repo` stack. U7 runs the docs gate.
- **Existing tests.** Only the tests named in §2 change, and each change is in the approval
  record (stop point S1). No other existing test is edited.
- **Deploy order** (spec P19): workers first, then the App. This goes in the PR body.

### 1.1 Plan decisions (they complete the spec; none changes an owner decision)

| D | Decision | Reason |
|---|---|---|
| D1 | The four "E2E" tests of the spec (CC-22, TC-21, ST-10, DOC-1) are Engine integration tests: the local in-process App, a fake gateway, and the `openai` SDK as the client. They do not use the SDK replay lane | A new scenario in the replay lane needs a paid recording by the owner first. These tests must run with no money |
| D2 | `openai` becomes a dev dependency of the Engine (`uv add --dev openai`) | It is in no `pyproject.toml` today. It is the client that the feature must satisfy |
| D3 | The local blob store is set in the Engine: `create_local_app` uses a filesystem blob store when none is configured | One place covers `serve --local` and `screamingface up`. No SDK package change |
| D4 | A gateway model id becomes the recipe `(model_1:0.0:/<route id>($input)!'')!'$model_1'` | An empty quoted intent parses, and the model endpoint then adds no system message. CC-5 pins this; if it fails, the unit stops and reports |
| D5 | The names that both the moved code and the remaining code use (`_headers`, `_GatewayRefusal`, `_capture_target`, `_GATEWAY_RESPONSE_MARGIN_S`) move too, and `connector.py` reads them from the new module. The new module makes its logger with the same logger name | The new module must not import `connector`. Log names stay the same |
| D6 | The exact list of existing test files for U1 is made by a script at the start of U1 and written into the approval record | Three counts exist (21, 26, and 18 plus 5 helper patches). The script is the authority |
| D7 | `tests/unit/test_url4_executor.py` gets two allow-list entries: `world/gateway_transport.py` (U1) and `chat/recipe.py` (U2). Owner decision of 2026-11-17 ("Add allow-list entries") | That test lets only named files import the url4 engine. The moved code and the recipe check must import it (spec contract C11) |
| D7a | The same rule as D7 for a new world adapter of this feature that registers a route on the node: `world/chat_turn.py` (U3) and `world/chat_final.py` (U6) get one allow-list entry each | `world/combine.py` and `world/branch.py` have such entries today; the owner chose the allow-list way for this feature |
| D8 | TC-5, TC-6 and TC-34 are loops over a fixed number of cases from a seeded `random.Random`, not `hypothesis` tests. Owner decision of 2026-11-17 ("No new dependency") | The Engine has no `hypothesis` dev dependency. The repo used seeded loops before (OME-890) |

## 2. Units

| # | Unit | Spec tests | Count | Main files | Stacks |
|---|---|---|---|---|---|
| U1 | Shared gateway round trip (move) | GT-1 … GT-8 | 8 | new `world/gateway_transport.py`; `world/connector.py`; `world/classification.py`; existing tests (patch targets) | screamingface-engine |
| U2 | Chat leaf: records, wire models, recipe check, re-point, views | CR-1, CR-2, TC-1 … TC-8, TC-29, TC-31 … TC-34 | 15 | new package `chat/`; `.claude/scripts/check_layering.py` | screamingface-engine, repo |
| U3 | Run shape, chat-input store, handler | CR-3 … CR-29 | 27 | `job_env.py`, `ports.py`, `runner_queue.py`, `adapters/inprocess.py`, `runner/main.py`, `runner/executor.py`, `artifacts/`, `local.py`, new `world/chat_turn.py`, `world/factory.py`, `world/serving.py`, `error_text.py` | screamingface-engine, repo |
| U4 | REST route, not streamed | CC-1 … CC-48 | 48 | new `rest/chat_completions.py`; `app.py`; `cli.py`; `metrics.py` | screamingface-engine |
| U5 | Streamed response | ST-1 … ST-9, ST-11 … ST-13 | 12 | new `chat/sse.py`; `rest/chat_completions.py` | screamingface-engine |
| U6 | Final-step endpoint and tools | TC-9 … TC-28, TC-30, TC-35, TC-36, ST-10 | 24 | new `world/chat_final.py`; `world/chat_turn.py`; `world/factory.py`; `rest/chat_completions.py` | screamingface-engine |
| U7 | Docs | DOC-1, DOC-2 | 2 | `public-docs` page; Engine `README.md`; `CONTEXT.md` | public-docs, screamingface-engine |
| | **Total** | | **136** | | |

Paths are under
`apps/screamingface-engine/src/screamingface_engine/` unless they start with another root.

### U1 — Shared gateway round trip (move, no behaviour change)

Spec: [prd/gateway-transport.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/gateway-transport.md).

1. **List.** Run a script that finds each test file which refers to a name in the move set
   through the `connector` module, and each source file that imports one. Expected: 18 test files
   for functions and constants, about 5 more for helper names that only moved code uses
   (`current_usage_sink`, `current_log_sink`, `retained_operation_accounting`,
   `signal_accounting_from_aigw`, `reply_logprobs`), and `world/classification.py`. Write the
   list into the ledger.
2. **Characterization tests first** (GT-1, GT-2, GT-3, GT-4, GT-7). They pass on the code of
   today. Commit them alone. They are the safety net of the move.
3. **Move.** About 1,170 lines leave `connector.py` (2,096 lines today):
   - the round trip: `_logged_round_trip`, `_observed_round_trip`, `_in_flight_heartbeat`;
   - capture, replay and the normal call: `_recorded_completion`, `_CaptureProbe`,
     `_fetch_replay` and its helpers, `_capture_target`;
   - cache and retries: `_fetch_completion`, `_post_answered`, `_post_completion`,
     `_post_attempt`, the retry, back-off and deadline helpers and their constants;
   - reports and accounting: `_report_response`, `_report_usage`, `_report_unpriced_call`,
     `_report_served_from_cache`, the `_retain_*` helpers, the reply-logprobs helpers,
     `_raise_if_unusable_with_accounting`;
   - headers and errors: `_headers`, `_json_or_raise`, `_GatewayRefusal`, `_raise_for_status`
     and their helpers.
   Function bodies do not change. Names keep their spelling, so a diff tool shows a pure move.
4. **One extraction.** The two time-out headers that the loop builds today become one function
   in the new module that takes two plain numbers. The header bytes do not change (GT-1).
5. **Imports.** `connector.py` and `classification.py` use `gateway_transport.<name>`. No
   `from … import <name>` for a moved name (GT-6, GT-8).
6. **Patch targets.** In each listed test file, change the patch target from `connector` to
   `gateway_transport`. Change nothing else in those files. A patch of a module object (`time`,
   `httpx`) stays as it is.
7. **Exit.** GT-1 … GT-8 green; the full Engine gate green; the golden bytes of GT-1, GT-2 and
   GT-7 are the same before and after step 3.

### U2 — Chat leaf (pure code, no I/O)

Spec: [erd.md](../spec/2026-11-17-engine-openai-chat-endpoint/erd.md) §2,
[prd/tool-calls.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/tool-calls.md) §3.

New package `chat/`, a shared leaf (no FastAPI, no `runner`, no `rest` import):

| Module | Content | Tests |
|---|---|---|
| `chat/input.py` | the CHAT_INPUT record, canonical encoding, the size rule | CR-1, CR-2 |
| `chat/result.py` | the CHAT_RESULT record, the `finish_reason` rule | used from U3 |
| `chat/wire.py` | the OpenAI request and response models; tolerant of extra fields | used from U4 |
| `chat/recipe.py` | model value rule (URL4 or model id, D4); final positions; refusals (reducer, Cascade, unknown form, internal route prefix, corrective loop); the re-point by binding name, with Gate bodies parsed and rendered again | TC-1 … TC-4, TC-29, TC-31, TC-32, TC-33 |
| `chat/views.py` | the text view (rule 0 to rule 6); the native messages of the final step | TC-5 … TC-8, TC-34 |

- The table tests of TC-1 use the recipes in
  `packages/screamingface/tests/data/surface_parity.json` and
  `apps/screamingface-engine/tests/unit/data/gate_contract/*.url4`.
- TC-5, TC-6 and TC-34 are generator tests with a seeded `random.Random` (decision D8): each
  text view must pass `parse_candidate_input`.
- Add `chat` to the shared-leaf list of `.claude/scripts/check_layering.py` (CR-15 completes in
  U3, when the world modules exist).

### U3 — Run shape, chat-input store, handler

Spec: [prd/chat-run.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/chat-run.md).

Order inside the unit:

1. **Run shape.** `RunShape` gets `chat`; the pair rule with `URL4_CLOUD_CHAT_INPUT`; the new
   keyword `chat_input` on the schedule port, on `_schedule`, on the queue codec, on the
   in-process adapter and on each test fake; the 5 s stream grace and the run deadline for
   `chat` (CR-3, CR-4, CR-5, CR-21).
2. **Blob store.** `delete` on the objects protocol and on each backend (CR-26); a content-check
   hook on the policy; one factory for the chat-input store that the App and the Runner both use
   (CR-19, CR-20, CR-23); the filesystem default in the local App (D3).
3. **Routes in the world.** `build_world` installs the combine, branch and chat routes in each
   gateway world, right after the direct-mount snapshot (CR-25). The App filters its mount table
   by the direct-mount set (CR-29).
4. **Handler.** `world/chat_turn.py`: read the input, build the text view, call
   `evaluate_candidate_recipe` inside the Candidate answering scope, build the CHAT_RESULT
   (CR-6, CR-7, CR-8, CR-10, CR-11, CR-12, CR-13, CR-22, CR-28). It fails closed outside a chat
   run (CR-24).
5. **Executor.** One new branch for the `chat` shape: build the target (context = blob ref,
   intent = Candidate URL4, CR-27), bind the chat-run marker, dispatch the turn route as one
   observed node (CR-9, CR-18). Stop, large result and parallel runs: CR-14, CR-16, CR-17.
6. **Codes.** Add `chat_input_unavailable`, `chat_input_invalid` and `final_step_ambiguous` to
   the Engine error code set.
7. **Existing tests that change** (approval record):
   - `tests/unit/test_terminal_error_detail.py`: the hand-pinned code list gets the three codes.
   - `tests/unit/test_combine_wiring.py`: `test_a_world_without_benchmarks_has_no_combine_route`
     is replaced by CR-25.
   - `tests/unit/test_job_env_contract.py` and `tests/unit/test_schedule_time_admission_rest.py`
     pin the run shape values. If they pin the full set, they get the new value.
8. **Pre-check before step 3.** Search the tests for another pin of the route set or of
   `/openapi.json` for a world with no Benchmarks. If one exists, stop and report.

### U4 — REST route, not streamed

Spec: [prd/chat-completion.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/chat-completion.md).

`rest/chat_completions.py`, one handler with these stages in order:

1. Content type check (415), identity (401), drain check (503) — CC-1, CC-2, CC-34, CC-42, CC-48.
2. Body read with a running cap and the limit of 4 large parses (413, 429) — CC-3, CC-33, CC-35.
3. Validation into the wire model, with no declared body parameter — CC-4, CC-15, CC-16, CC-24,
   CC-25.
4. Model resolution and recipe check: catalogue lookup with a 60 s keep, 404, 503 — CC-5, CC-6,
   CC-7, CC-8, CC-9, CC-32, CC-40, CC-43.
5. Input encode and ingest, then schedule with shape `chat` — CC-10, CC-11, CC-26, CC-46, CC-47.
6. Wait: an own scan of the topic that keeps the result frame, the root cost-usage frame and the
   terminal frame; time limit; disconnect — CC-18, CC-19, CC-41.
7. Answer: the terminal table, the OpenAI envelope, `x-should-retry`, usage and cost from the
   root frame — CC-12, CC-13, CC-14, CC-17, CC-20, CC-21, CC-27, CC-28, CC-36, CC-37, CC-38,
   CC-44, CC-45.
8. Drain: a server subclass in `cli.py` for both start paths sets the drain event on the stop
   signal — CC-39 (subprocess test).
9. Integration on the local in-process App with a fake gateway and the `openai` SDK (D1, D2) —
   CC-22, CC-23, CC-29, CC-30, CC-31.

### U5 — Streamed response

Spec: [prd/streaming.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/streaming.md).

- `chat/sse.py`: pure frame functions (ST-1, ST-2, ST-3, ST-12, ST-13) and the conformance test
  with the `openai` SDK types (ST-4).
- The route: streaming response, keep-alive timer, headers, error event, shielded cleanup
  (ST-5, ST-6, ST-7, ST-9, ST-11).
- ST-8 runs a real server and sends a real disconnect.

### U6 — Final-step endpoint and tools

Spec: [prd/tool-calls.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/tool-calls.md).
Stop point S3 comes before this unit.

1. `world/chat_final.py`: one request through the shared round trip, with the native messages
   and the client tools; its own search flag rule; records; the collector (TC-9, TC-10, TC-11,
   TC-17, TC-22, TC-25, TC-27, TC-28, TC-30, TC-35, TC-36).
2. Registration in the chat installer, for each declared model, with the gateway world (TC-12).
3. Handler: when the request has tools, re-point the final model steps and read the collector
   (TC-13, TC-14, TC-15, TC-16, TC-20, TC-24, TC-26).
4. Route: the tools rules, the tool-support check from the catalogue, the tool-call response
   (TC-18, TC-19, TC-23).
5. Integration with the `openai` SDK: a two-turn tool loop, plain and streamed (TC-21, ST-10).

### U7 — Docs

Spec: [prd/docs.md](../spec/2026-11-17-engine-openai-chat-endpoint/prd/docs.md).

- A page in `public-docs` with each limit of the spec, and examples for the OpenAI Python SDK,
  pi and opencode (DOC-1, DOC-2).
- A section in the Engine `README.md` (route, records, deploy order).
- `CONTEXT.md`: the new terms (chat request, chat run, final step, text view).

## 3. Stop points for the owner

| S | When | What I need |
|---|---|---|
| S0 | now | Approval of this plan in plain words. No code before it |
| S1 | before U1 | The approval record for edits to existing tests. The record needs an issue id and the final branch name, but the repo files the issue at PR-open. Option A (my proposal): I run the unit gates with `--skip-append-only`, write that in the ledger, and at PR-open I write the record and run the full gates with no skip. Option B: you name the epic now, and I file the issue before U1 |
| S2 | after U1 | A look at the move commit, if you want one before the feature code goes on top |
| S3 | before U6 | A small paid check of two provider behaviours that no reviewer could verify: the message layout of the final step on an Anthropic model, and provider search together with client tools. It costs real money (a few calls). I do not run it without your word |
| S4 | after U6 | A manual run with pi and opencode against the local stack. It needs a provider key on this machine |
| S5 | PR-open | The parent epic; the Linear issue and its sub-issues (the work touches the Engine, `public-docs` and the repo scripts); the branch rename; the task mirror; the final approval record |

## 4. Risks of the build

| Risk | Control |
|---|---|
| The move changes behaviour by accident | Golden-byte tests are committed before the move; function bodies do not change; the import rule makes a stale test patch fail loudly |
| One pull request is large (about 1,200 moved lines, about 2,500 new lines, 136 tests) | Units are ordered commits; each unit passes the full gate; the PR body lists the commits to read in order |
| The route is always on (spec ans:Q21) | The feature arrives complete in one deploy; workers deploy first |
| A rule of the spec meets a case that no review found | The unit stops and reports. It does not invent a rule |

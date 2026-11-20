# PRD: the chat run (run shape `chat` and its handler)

**Source:** ans:Q6, ans:Q8, ans:Q11 · **Priority:** P1 (all flows use it)
**Lifecycle:** planned · **Owner:** unassigned

## 1. Summary and the flows it serves

This component is the dedicated run-side path of the feature. It serves three flows:
[chat-completion](chat-completion.md), [tool-calls](tool-calls.md) and [streaming](streaming.md).
The owner asked for "a second and lean / opnionated endpoint specifically for this feature"
`[stated ans:Q6]`. The component runs the recipe of the user as the user built it
`[stated ans:Q8]` and returns one CHAT_RESULT record ([erd](../erd.md) §2.4).

## 2. Background and constraints

- "instead of adapting the existing engine runner endpoint logic ... i`d prefer to have a second
  and lean / opnionated endpoint specifically for this feature." `[stated ans:Q6]`
- "the user must be able to build their own ensemble in whatever way they decide to"
  `[stated ans:Q8]`
- The child selects its work by run shape. The values today are `expression` and `direct`
  `[existing E/job_env.py:232]`, and the branch is in the executor
  `[existing E/runner/executor.py:1167]`.
- The shape travels in the env of the run spec `[existing E/child_protocol.py:62]`. No module in
  `E/worker/` has a branch on the shape `[implied]`.
- Each shape gets the event bridge, the run summary, the memory guard, the identity scope and
  tracing `[existing E/runner/main.py:731]` `[existing E/runner/main.py:85]`.
- Cost and usage frames exist only for an **observed** run. `Url4Node.evaluate` starts a run with
  no observer `[existing packages/url4/src/url4/peer/server.py:238]`, and then the usage reports
  of the model endpoint go nowhere. A direct run is observed because the executor dispatches its
  one handler with the bridge as observer `[existing E/runner/executor.py:1192]`.
- Thus the handler is an internal endpoint, and the executor dispatches it as a direct run
  dispatches a mount `[proposed — review 1]`. The Candidate route works the same way today: it
  evaluates the recipe inside an observed outer node `[existing E/world/candidate_adapter.py:37]`.
- The combine and branch routes read the operation-call records of the current scope. A Gate
  raises an error when a record is absent `[existing E/world/branch.py:617]`. Thus each step
  before the final model step must run on the existing model endpoint `[implied]`.
- `evaluate_candidate_recipe` binds those recorders, binds the input to `$input` and returns the
  Candidate Invocation envelope `[existing E/benchmarks/invocation.py:60]`
  `[existing E/benchmarks/invocation.py:68]`.
- The control plane never evaluates an expression `[existing .claude/scripts/check_layering.py:48]`.
  Thus the handler is in the run half.
- A warm child builds its world before it knows the run `[existing E/runner/main.py:682]`. The
  handler uses that world. It builds no second world `[implied]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**CR-S1 A chat run answers with a CHAT_RESULT.** `[stated ans:Q6]`
- Given a run spec with shape `chat`, a Candidate URL4 and a CHAT_INPUT blob ref
- When the child runs it
- Then the executor dispatches the internal route `/ensemble/chat/v1/turn` as one observed node,
  with the bridge as observer `[proposed — review 1]`. The target has the blob ref as context
  and the Candidate URL4 as intent ([erd](../erd.md) §2.2)
- And the handler reads the blob with the run-scoped reader of the chat-input store
  `[existing E/artifacts/blobs.py:240]`
- And it builds the TEXT_VIEW and binds it to `$input`
- And it calls `evaluate_candidate_recipe` inside the Candidate answering scope
  `[existing E/candidate_scope.py:35]`
- And it publishes one result frame with a `screamingface.chat-result.v1` body and the media type
  `application/vnd.screamingface.chat-result+json`
- And it publishes the terminal frame.

**CR-S2 The recipe runs as built.** `[stated ans:Q8]`
- Given a recipe with reducers, signals, a Gate, a Cascade or a budget
- When the chat run evaluates it with no client tools
- Then each model call uses the existing model endpoint with the same request bytes that a
  benchmark Case with the same input gives
- And the handler changes no route of the expression.

**CR-S3 The run reports the usage of the whole ensemble.** `[stated ans:Q13]`
- Given a run that made N model calls, two of them on the same route with the same parameters
- Then each call reports its usage to the one span of the turn handler, because the inner
  evaluation binds no new sinks `[existing packages/url4/src/url4/dag/executor.py:177]`
- And the executor adds them on that span `[existing E/runner/executor.py:549]`
- And the topic stream has one cost-usage frame with `scope: self` and one root frame with
  `scope: subtree`, published before the result frame
  `[existing packages/url4/src/url4/streaming/lifecycle.py:275]`
- And the token counts and the cost of the root frame are the sums over the N calls.
- The handler does not sum from operation attribution, which drops the accounting of two
  bindings with one fingerprint `[existing E/benchmarks/operation_outputs.py:193]`.
- A call served from the cache reports 0 tokens `[existing E/world/connector.py:853]`, so the
  sums count the calls that really ran `[stated ans:Q26]`.

### 3.2 Error paths

**CR-S4 Abstain is a result, not an error.** `[stated ans:Q10]`
- Given a recipe whose final operation abstains `[existing E/benchmarks/operation_outputs.py:118]`
- When the handler builds the result
- Then `status` is `abstained`, `content` is empty, `tool_calls` is empty, `finish_reason` is
  `stop` and `abstain_reason` holds the Engine reason.

**CR-S5 A failed recipe ends the run with an error frame.** `[stated ans:Q10]`
- Given a recipe that fails (for example `fail_closed`, `quorum_not_met`, `signal_missing` or a
  permanent model error)
- When the evaluation raises
- Then the run publishes no result frame
- And the terminal frame carries the Engine failure code.

**CR-S6 A provider refusal is a result.** `[implied]`
- Given the evaluation returns a `refused` invocation `[existing E/benchmarks/invocation.py:69]`
- Then `status` is `refused`, `finish_reason` is `content_filter` and `refusal` holds the text.

### 3.3 Derived scenarios

**CR-S7 The input blob is absent or damaged.** `[proposed — gap §per-connection/data]` H×L
- Given the blob ref finds nothing, or the store reports corruption (digest or media type)
- Then the run fails with code `chat_input_unavailable` before a model call.
- A storage failure during the read (for example an object-store outage) gives the same code,
  with the failure marked as not permanent `[proposed — build review of U3]`.

**CR-S8 The input has an unknown schema.** `[proposed — gap §per-element/store]` M×L
- Given the blob holds a `schema` that is not `screamingface.chat-input.v1`
- Then the run fails with code `chat_input_invalid` before a model call.

**CR-S9 The shape and the input key disagree.** `[proposed — gap §per-flow/state]` M×L
- Given shape `chat` with no `URL4_CLOUD_CHAT_INPUT`, or the key with a different shape
- Then the child refuses the run spec before it builds anything.

**CR-S10 The run is stopped.** `[implied — gap §per-flow/cancel]` H×M
- Given the App stops the topic (time limit or client disconnect)
- Then the child stops its model calls as each run does today, and it publishes no result frame.

**CR-S11 A redelivered queue message.** `[implied — gap §per-connection/async]` M×L
- Given the queue delivers the same message again
- Then the existing ownership and redelivery gates decide `[existing E/worker/supervisor.py:415]`.
  The chat shape adds no rule.

**CR-S12 The result is larger than the inline cap.** `[proposed — gap §per-flow/boundary]` L×L
- Given a result body above 524,288 bytes
- Then the run parks it in the artifact store as each run does `[existing E/runner/executor.py:660]`,
  and the App reads it from there.

**CR-S13 Local mode.** `[stated ans:Q1]`
- Given `serve --local`
- Then the in-process runner runs the same handler `[existing E/adapters/inprocess.py:282]` with
  the same records.

**CR-S14 Two requests at the same time.** `[implied — gap §per-flow/concurrent]` M×M
- Given two chat runs of one caller
- Then they share no state. Each has its own topic, blob scope and recorders.

**CR-S15 The run deadline bounds each model call.** `[proposed — review 1]` H×M
- Given a chat run with a deadline of the time limit plus 5 s
- Then no gateway attempt starts after the deadline, as for a direct run
  `[existing E/runner/main.py:118]`.

**CR-S16 Web search follows the model route.** `[stated ans:Q30]` H×M
- Each model route declares if it can search the web, and the default is yes
  `[existing E/world/config.py:175]`. A step with no `web_search` parameter does what its route
  declares `[existing E/world/request_parameters.py:54]`.
- The handler binds no retrieval policy. Thus, in a chat request, a step searches when its route
  can search, unless the recipe sets `web_search=false` for that step. What "can search" means
  `[proposed — review 4]`:

  | Route and Engine | Step with no `web_search` parameter | Step with `web_search=true` |
  |---|---|---|
  | the provider does the search itself (OpenRouter routes) | searches | searches |
  | the Engine runs the search tools, and the Engine has a search key | searches (tool loop) | searches (tool loop) |
  | the Engine runs the search tools, and the Engine has no search key | does not search; no error `[existing E/world/web_tools.py:241]` | the run fails with the permanent code `web_retrieval_unavailable` `[existing E/world/web_tools.py:247]` |

  The search key is optional in the chart `[existing apps/screamingface-engine/deploy/helm/values.yaml:353]`.
- Known effect: a step that is not final gets the Engine search tools and also sees the client
  tools as text. A model can then try to call a client tool by name. The Engine answers
  "unknown tool", and the step can end at the limit of the tool loop
  `[existing E/world/web_tools.py:413]`. The docs state this.
- The owner chose this rule with its effects stated: the conversation text of each such step goes
  to the search provider, and each such step costs more and takes longer. The docs state it and
  show how to turn it off.
- No shared code changes for this. The recipe text is not changed either: Gates and combine steps
  find the records of their members by the exact text of the recipe
  `[existing E/world/branch.py:548]` `[existing E/combine/spec.py:620]`.
- Note: in a Benchmark, the Benchmark sets a policy for each Candidate call
  `[existing E/world/candidate_adapter.py:105]`. A chat run has no Benchmark, so a recipe can
  search here when it did not search in a Benchmark that forbids it.
- The final step with client tools has its own rule ([tool-calls](tool-calls.md) §3.2).

**CR-S18 The turn route works only in a chat run.** `[proposed — review 2]` H×M
- Given an expression in `GET /?q=`, or a client recipe, that names `/ensemble/chat/v1/turn`
- Then the handler fails with a permanent error before it reads a blob or calls a model. The
  executor binds a chat-run marker only for the `chat` shape, and the handler needs it.

**CR-S19 A world with no Benchmarks.** `[proposed — review 2]` H×M
- Today the Engine installs the combine and branch routes only when the world has Benchmarks
  `[existing E/world/factory.py:256]`. A local stack can have none.
- Then `build_world` installs the combine, branch and chat routes in each gateway world, right
  after the direct-mount snapshot `[existing E/world/factory.py:252]`. The Candidate and
  corrective routes stay as they are today. The combine and branch installers skip a route that
  exists already `[existing E/world/combine.py:53]`, so the Benchmark path is not changed.
- One existing test pins that a world with no Benchmarks has no combine route
  (`tests/unit/test_combine_wiring.py`, `test_a_world_without_benchmarks_has_no_combine_route`).
  CR-25 replaces it, and the change needs the approval record `[proposed — review 4]`.
- The App builds its public mount table from a world with no Benchmarks, and it lists each
  endpoint of that world `[existing E/world/serving.py:189]`. With the line above, it would
  publish the internal routes as GET mounts. Thus the App filters its mount table by the
  direct-mount set, as the local stack does `[existing E/local.py:407]`
  `[proposed — review 3]`. The public mounts and `/openapi.json` do not change.

**CR-S20 Concurrency of the inner evaluation.** `[proposed — review 2]` M×M
- The inner evaluation runs at the concurrency of the node, as an inner Candidate evaluation
  does today `[existing packages/url4/src/url4/peer/server.py:238]`. The per-run I/O budget and
  the local fair-share gate do not apply inside it. The per-provider limits of the gateway
  still apply. This is a known limit.

**CR-S17 The chat-input store is separate from attachments.** `[proposed — review 1]` H×M
- Given a `PUT /blob` request with the chat-input media type
- Then the public route refuses it
- And the Runner reads a record that the App wrote, with no corruption error.

## 4. Non-functional requirements

- **Overhead.** From the start of the handler to the first model call: ≤ 50 ms at p95 for an
  input of 1 MB, without the blob read `[proposed]`. Reason: the text view is one pass over the
  messages.
- **Memory.** The handler holds the input once as bytes and once as parsed objects. With the
  8 MB cap, the extra peak is ≤ 40 MB `[proposed]`, inside the child address-space limit.
- **Observability.** The run summary records the shape. A failed run logs its failure code and
  the digest of the input, never the content `[proposed]`.
- **Security.** The blob scope comes from the run env, never from the ref
  `[existing E/artifacts/blobs.py:17]`. The handler treats the blob as untrusted input and
  validates it again `[proposed]`.
- **Layering.** The handler is an endpoint, so it is in `E/world/chat_turn.py` and is registered
  beside the combine and branch routes `[existing E/world/factory.py:171]`. The executor gets one
  new branch for the `chat` shape. `E/chat/` is a shared leaf with no FastAPI import and no
  `runner` import. The layering gate lists the new modules `[proposed]`.

## 5. Out of scope

- A second, lighter world or worker pool for chat runs `[proposed]` (later work).
- Capture, replay, attempts, and Run registry rows `[proposed]`.
- Real token streaming from the run `[stated ans:Q4]`.

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: core-out. The records and the handler come before the REST route, because the route
depends on them. Tests are in `apps/screamingface-engine/tests/unit/`.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CR-1 | `chat_input_round_trips_canonical_json` | unit | [proposed] | H×M | pydantic model + canonical encoder in `E/chat/input.py` |
| CR-2 | `chat_input_refuses_unknown_schema_by_name` | unit | [proposed] | M×L | version check before any other field |
| CR-3 | `run_shape_accepts_chat_and_requires_input_key` | unit | [proposed] | H×M | widen `RunShape`; pair check in `job_env` |
| CR-4 | `run_shape_refuses_input_key_on_other_shapes` | unit | [proposed] | M×L | same check, other direction |
| CR-5 | `queue_and_inprocess_adapters_render_same_chat_env` | unit | [existing E/adapters/inprocess.py:282] | H×M | one codec for both adapters |
| CR-6 | `chat_run_binds_text_view_to_input_and_returns_chat_result` | integration | [stated ans:Q6] | H×H | `world/chat_turn.py` handler with a stub gateway |
| CR-7 | `chat_run_without_tools_sends_same_request_bytes_as_candidate_route` | integration | [stated ans:Q8] | H×H | compare gateway bodies with the Candidate route for the same input; the recipe sets `web_search=false` on each step, so the search rule is the same on both paths |
| CR-8 | `chat_run_runs_gate_recipe_and_skipped_branch_makes_zero_calls` | integration | [stated ans:Q8] | H×M | no change expected; proves recorders are bound |
| CR-9 | `chat_run_subtree_frame_sums_tokens_and_cost_of_every_model_call` | integration | [stated ans:Q13] | H×H | dispatch the handler as an observed node; two members on one route count twice in the sum |
| CR-10 | `abstain_gives_abstained_status_and_empty_content` | unit | [stated ans:Q10] | H×M | map invocation `abstained` |
| CR-11 | `failed_recipe_publishes_error_frame_and_no_result` | integration | [stated ans:Q10] | H×M | let the failure reach the executor |
| CR-12 | `refused_invocation_gives_refused_status_and_content_filter` | unit | [implied] | M×M | map invocation `refused` |
| CR-13 | `missing_or_corrupt_blob_fails_before_any_model_call` | integration | [proposed] | H×L | read first; typed error |
| CR-14 | `stopped_chat_run_publishes_no_result` | integration | [implied] | H×M | existing stop path |
| CR-15 | `layering_gate_lists_chat_leaf_and_chat_world_modules` | unit | [proposed] | M×M | update `check_layering.py` sets |
| CR-16 | `result_over_inline_cap_is_read_from_artifact_store` | integration | [proposed] | L×L | existing parcel path; the App reads the artifact |
| CR-17 | `two_parallel_chat_runs_share_no_state` | integration | [implied] | M×M | no module state; scoped recorders and collector |
| CR-18 | `chat_handler_runs_as_observed_node_and_run_summary_has_cost` | integration | [proposed] | H×H | `dispatch_direct` with the bridge; summary `cost_usd` is set |
| CR-19 | `public_put_refuses_chat_input_media_type` | unit | [proposed] | H×M | attachment policy unchanged |
| CR-20 | `runner_reads_chat_input_written_by_app_store` | integration | [proposed] | H×H | one shared store factory for both halves |
| CR-21 | `chat_run_starts_no_gateway_attempt_after_its_deadline` | unit | [proposed] | H×M | deadline rule of direct runs for `chat` |
| CR-22 | `step_follows_its_route_for_web_search_in_each_of_four_cases` | integration | [stated ans:Q30] | H×M | table: provider search; Engine tools with key; Engine tools without key (plain request, no error); recipe `false`. No policy bound |
| CR-23 | `chat_input_over_cap_after_encoding_is_refused_at_ingest` | unit | [proposed] | M×L | cap on the encoded record |
| CR-24 | `turn_route_outside_chat_run_fails_closed_before_any_work` | unit | [proposed] | H×M | chat-run marker bound by the executor only |
| CR-25 | `world_without_benchmarks_serves_chat_combine_and_branch_routes` | unit | [proposed] | H×M | installer runs in each world; routes are not direct mounts |
| CR-26 | `blob_delete_removes_data_and_metadata_on_each_backend` | unit | [stated ans:Q17] | H×M | protocol + filesystem + S3 + in-memory |
| CR-27 | `turn_target_round_trips_a_url4_with_quotes_and_special_characters` | unit (property) | [proposed] | H×M | build the target, decode it, compare the intent; 32,000 characters allowed |
| CR-28 | `budget_gate_and_cost_reducer_give_same_records_as_candidate_route` | integration | [proposed] | H×H | same recipe through both paths; same operation records and decisions |
| CR-29 | `app_mount_table_and_openapi_are_unchanged` | unit | [proposed] | H×M | filter by the direct-mount set |

Scenario without its own test: CR-S11 (redelivery). The chat shape adds no rule to the existing
gates, so the existing tests cover it.

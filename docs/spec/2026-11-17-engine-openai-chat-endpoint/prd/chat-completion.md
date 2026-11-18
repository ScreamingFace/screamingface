# PRD: chat completion without tools (`POST /v1/chat/completions`)

**Source:** prompt, ans:Q1–Q4, ans:Q7, ans:Q10, ans:Q13–Q16 · **Priority:** P1
**Lifecycle:** planned · **Owner:** unassigned

## 1. Summary and user story

As a developer with an OpenAI client (an SDK or a coding agent), I want to send a chat request to
the Engine with my ensemble as the `model`, so that I use the ensemble as one model with no
ScreamingFace client code. The prompt: "the engine offers OpenAI API compatiple API ... to use
their url4 model ensembles transparently" `[stated prompt]`.

## 2. Background and constraints

- Targets: "both ... compatibility with agents like opencode, claude code, pi, etc ... and well
  known sdks that expect this type of api from an LLM platform" `[stated ans:Q1]`.
- Authentication: "Same auth mechanism we use nowadays" and "it must use the same auth workflow
  we already have" `[stated ans:Q2]`.
- Path: "why not just v1/chat/completions" `[stated ans:Q7]`.
- The run-side work is in [chat-run](chat-run.md). This PRD owns the HTTP side.
- No Engine route uses `/v1/chat/completions` today `[implied]`. The `/v1` routes are catalogue,
  limits, connections and credits routes `[existing E/rest/catalog.py:115]`
  `[existing E/rest/limits.py:51]` `[existing E/rest/connections.py:167]`
  `[existing E/rest/credits.py:52]`. Mounts are exact GET paths `[existing E/rest/mounts.py:1]`.
- A longer literal path below `/v1/` does not collide with the local eval path `/v1`
  `[existing E/world/serving.py:248]`.
- `GET /v1/models` returns the gateway list `{"object":"list","data":[…]}` with `id`,
  `object` and `owned_by` in each row `[existing E/rest/catalog.py:115]`
  `[existing G/core/model_capabilities.py:72]` (`G/` = `apps/aigateway/src/aigateway/`). This
  feature does not change it.
- Hosted identity: the Envoy policy verifies the Cloudflare Access token and writes
  `X-User-Email` `[existing apps/screamingface-engine/deploy/helm/templates/securitypolicy.yaml:1]`.
  A mount call takes its identity from that header `[existing E/rest/mounts.py:12]`
  `[existing E/rest/mounts.py:304]`. This route does the same `[proposed]`.
- The SDK sends the Access token in the `Cf-Access-Token` header
  `[existing packages/screamingface/README.md:1638]`, and the docs give
  `cloudflared access token -app=<engine url>` as the way to get one
  `[existing packages/screamingface/README.md:1626]`.
- The Engine never forwards `Authorization` `[existing E/request_scope.py:362]`.
- Reusable helpers: `_schedule` `[existing E/rest/routes.py:353]`, `wait_terminal_or_gone`
  `[existing E/rest/routes.py:630]`, `new_topic` `[existing E/auth/token.py:13]`.
- These helpers raise `ProblemException`, which the App renders as `application/problem+json`.
  A mount handler catches it and writes its own envelope `[existing E/rest/mounts.py:374]`. This
  route must do the same `[proposed — review 1]`.
- A terminal error passes `_sanitized_error` before it crosses the HTTP boundary, because its
  code and message can hold provider text `[existing E/rest/routes.py:88]`.
- The existing wait helper keeps only the result frame and the terminal frame
  `[existing E/rest/routes.py:485]`. This route also needs the root cost-usage frame, so it gets
  its own scan of the topic `[proposed — review 2]`.
- The Engine has no general request-size guard. The App memory limit is 512 Mi, and its
  shutdown grace is 45 s, sized for the 30 s hold
  `[existing apps/screamingface-engine/deploy/helm/values.yaml:559]`.
- Per-caller in-flight cap: 24 runs `[existing E/runner_queue.py:127]`.
- The final forms of a Candidate URL4 are `$model_N`, `$synthesis_N`, `$gate_N_block` and
  `$loop_candidate` `[existing packages/screamingface/src/screamingface/_operation_bindings.py:22]`.
- A corrective loop needs the check surface of a Benchmark
  `[existing packages/screamingface/src/screamingface/_evaluation/candidate.py:139]`.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**CC-S1 A gateway model id is a one-model recipe.** `[stated ans:Q16]`
- Given `model` does not start with `(` after white space is removed
- And the model-parameters lookup of the catalogue port knows the id
  `[existing E/catalog/port.py:188]` (an id can contain `:`)
- When the client posts messages with no tools
- Then the Engine runs a one-model recipe with no added instruction
- And the model receives the client messages with no change.
- Rule: a value that starts with `(` is a URL4. Each other value is a model id
  `[proposed — review 1]`.
- The lookup is a call to the gateway. The route keeps each positive answer for 60 s for the
  same caller and id. A "not known" answer is not kept, because the user can connect a provider
  at any time. When the lookup fails, the answer is 503 `catalog_unavailable` with
  `Retry-After` `[proposed — review 2]`. The catalogue port has separate errors for the two
  cases `[existing E/catalog/port.py:188]`.

**CC-S2 A Candidate URL4 is the model.** `[stated ans:Q3]` `[stated ans:Q16]`
- Given `model` is a Candidate URL4 string (for example a Fusion with a synthesizer)
- When the client posts messages with no tools
- Then the Engine runs that recipe as built ([chat-run](chat-run.md) CR-S2)
- And the answer of the recipe is the assistant message.

**CC-S3 The response has the OpenAI shape.** `[stated prompt]`
- Then the body has `id` (`chatcmpl-…`), `object: "chat.completion"`, `created`, `model` (the
  request value, unchanged) and one `choices[0]` with `index: 0`,
  `message: {role: "assistant", content}` and `finish_reason`
- And `usage` is the sum over all model calls of the run `[stated ans:Q13]`. The App reads the
  token counts and the cost from the root cost-usage frame (`scope: subtree`) of the topic
  ([chat-run](chat-run.md) CR-S3) `[proposed — review 2]`
- And a call served from the shared cache counts 0 tokens, so a fully cached turn shows a
  `usage` of 0 `[stated ans:Q26]`
- And `cost_usd` is null when the run has a call with no price (the frame says `unpriced`). An
  unknown cost is never shown as 0 `[proposed — review 2]`
- And an extra `screamingface` object holds `status`, `cost_usd`, `final_step` and `trace_id`
  `[proposed]`. It has no call count: the run reports one usage record for the whole ensemble
  `[proposed — review 2]`.

**CC-S4 Hosted callers use the Access token.** `[stated ans:Q2]`
- Given a hosted Engine and a request with a valid `Cf-Access-Token` header
- Then the edge sets the identity and the Engine accepts the request
- And the model calls use the Provider Connections of that identity, as each run does.

**CC-S5 Local callers need no credential.** `[stated ans:Q1]`
- Given `serve --local`
- Then a request with no identity header is served `[existing E/rest/mounts.py:131]`.

**CC-S6 The shared cache is on by default.** `[stated ans:Q15]`
- Given two identical requests
- Then the model calls of the second request can come from the shared cache
- And a request with `Cache-Control: no-store` does not use the cache
  `[existing E/cache_intent.py:48]`.

**CC-S7 Sampling fields are accepted and ignored.** `[stated ans:Q14]`
- Given a request with `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`,
  `seed`, `response_format`, `reasoning_effort`, `presence_penalty` or `frequency_penalty`
- Then the Engine accepts the request
- And no model call of the run gets these values. The values in the recipe apply.

**CC-S8 Unknown client fields are tolerated.** `[proposed — gap §per-element/actor]`
- Given fields such as `store`, `metadata`, `user`, `prompt_cache_key`, `parallel_tool_calls` or
  `stream_options`
- Then the Engine accepts the request. Only `stream_options.include_usage` has an effect
  ([streaming](streaming.md)).

**CC-S9 Abstain gives an empty answer with a status.** `[stated ans:Q10]`
- Given a run with `status: abstained`
- Then the response is 200 with `content: ""`, `finish_reason: "stop"`,
  `screamingface.status: "abstained"` and `screamingface.abstain_reason`.

### 3.2 Error paths

All errors use the OpenAI envelope `{"error": {"message", "type", "param", "code"}}` `[proposed]`.

| # | Given | Then (status, `code`) | Source |
|---|---|---|---|
| CC-S10 | hosted request with no verified identity (`app.state.runs_require_identity` `[existing E/rest/runs_boundary.py:170]`). Note: with the hosted edge on, the edge refuses a request with no valid token before the Engine sees it, with its own body | 401 `identity_required` | [stated ans:Q2] |
| CC-S34 | the media type of `Content-Type` is not `application/json` (parameters such as `charset` are ignored) | 415 `unsupported_media_type`, before the body is read. This stops a cross-site "simple" POST from a web page | [proposed — review 1] |
| CC-S11 | body is not JSON, or a field has the wrong type, or `messages` is empty | 400 `invalid_request` with `param` | [proposed] |
| CC-S12 | `model` is not a URL4 and the model-parameters lookup does not know the id | 404 `model_not_found` | [stated ans:Q16] |
| CC-S13 | `model` starts as a URL4 and does not parse, or its final form is unknown: the root intent is not one of the final forms, or it names a binding that has no source in the recipe. This is the FORM of the root, with tools and with no tools. A root that names a real step which the check cannot classify is not this case: with no tools it runs as built, and with tools it is [tool-calls](tool-calls.md) TC-S9 `[proposed — build review of U2]` | 400 `recipe_invalid` | [implied] |
| CC-S14 | the recipe has a corrective loop (`$loop_candidate`), at the root or at any depth, Gate bodies included `[proposed — build review of U2]` | 400 `recipe_not_supported` | [implied] |
| CC-S15 | `model` is a benchmark-linked expression (it has an embedded `candidate` source) | 400 `recipe_invalid`, the message tells the user to send the Candidate URL4 | [proposed] |
| CC-S16 | `n` > 1, `logprobs: true` or an audio modality | 400 `unsupported_parameter` | [proposed] (overview P4) |
| CC-S17 | body larger than 8,000,000 bytes, or encoded input record larger than 8,000,000 bytes, or `model` longer than 32,000 characters | 413 `request_too_large` | [proposed] |
| CC-S18 | a picture or file part with a remote URL | 400 `unsupported_content` [proposed]; the envelope accepts only `data:` URIs | [existing E/benchmarks/candidate_input.py:371] |
| CC-S19 | the caller has 24 runs in flight (evaluation runs and chat requests share this limit `[stated ans:Q25]`), or the queue refuses | 429 `overloaded` with `Retry-After` | [existing E/runner_queue.py:127] |
| CC-S20 | no blob store is configured `[existing E/artifacts/blobs.py:11]` | 503 `chat_unavailable`, no `Retry-After`, `x-should-retry: false` (the cause is permanent) | [proposed] |
| CC-S38 | the queue is not available | 503 `queue_unavailable` with `Retry-After` | [proposed — review 2] |
| CC-S21 | the run does not end in `chat_max_wait_s` (600 s) | the run is stopped, then 504 `timeout` | [proposed] |
| CC-S22 | the recipe fails with `fail_closed` | 422 `fail_closed` | [stated ans:Q10] |
| CC-S23 | the recipe fails with another Engine failure code | 502 (see the table below) | [stated ans:Q10] |
| CC-S24 | the run breaks its memory budget or the worker is lost | 503 `run_failed` | [implied] |

**The terminal table** `[proposed — review 2]`. A run ends with one of four states: `succeeded`,
`failed`, `stopped`, `timed_out`
`[existing packages/url4/src/url4/streaming/protocol/signals.py:221]`. The route answers by this
table, keyed on the state and the raw code. The route does not reuse the status map of
`GET /?q=`, which gives 409 for `stopped`.

| State, raw code | HTTP | Body `code` | `x-should-retry` |
|---|---|---|---|
| succeeded, valid CHAT_RESULT | 200 | — | — |
| succeeded, no result frame, or an artifact that cannot be read | 502 | `result_unavailable` | false |
| succeeded, wrong media type or a record that fails validation | 502 | `result_invalid` | false |
| failed, `fail_closed` | 422 | `fail_closed` | false |
| failed, `chat_input_unavailable` or `chat_input_invalid` | 500 | the same code | false |
| failed, `final_step_ambiguous` | 502 | the same code | false |
| failed, another code that the Engine vouches for | 502 | the sanitized code | false when the failure is permanent |
| failed, a code that the Engine does not vouch for | 502 | `internal_error` | false |
| failed, `memory_budget_exceeded` | 503 | `run_failed` | false |
| failed, `oom_killed`, `killed` or `child_exited` | 503 | `run_failed` | true |
| stopped, `worker_draining` (a worker deploy) | 503 | `worker_draining` | true |
| stopped by this route at the time limit | 504 | `timeout` | false |
| stopped by this route at App shutdown (CC-S37) | 503 | `server_restarting` | true |
| stopped, any other code | 503 | `run_failed` | true |
| timed_out, any code | 504 | `timeout` | false |

Codes of the queue and the worker start (for example `queue_expired` and `spawn_failed`) use the
two generic "failed" rows. `quorum_not_met` and `signal_missing` reach the route as permanent
failures. `budget_refused` and the other abstain reasons are not failures: they give a 200
with the abstained status.

- The worker gives the codes `worker_draining`, `deadline_exceeded`, `oom_killed`, `killed`,
  `child_exited` and `memory_budget_exceeded` `[existing E/worker/supervisor.py:1155]`.
- `_sanitized_error` changes each code that is not in the Engine code sets into
  `internal_error` `[existing E/error_text.py:63]`. Thus the route takes the HTTP status from the
  raw code and the body `code` from this table. The `message` comes only from
  `_sanitized_error` `[existing E/rest/routes.py:88]`.
- The new codes `chat_input_unavailable`, `chat_input_invalid` and `final_step_ambiguous` are
  added to the Engine code set, so their messages are vouched for. One existing test pins that
  set by hand, so it changes too and needs the approval record ([test-plan](../test-plan.md) §1)
  `[proposed — review 3]`.

**No blind retries.** The `x-should-retry` header follows the table. Reason: OpenAI SDKs retry
408, 409, 429 and 5xx, and each retry runs the full ensemble again `[proposed — review 1]`.

**CC-S25 A provider refusal is a normal response.** `[implied]`
- Given a run with `status: refused`
- Then the response is 200 with `message.refusal`, `content: null` and
  `finish_reason: "content_filter"`.

### 3.3 Derived scenarios

**CC-S26 The client disconnects.** `[implied — gap §per-flow/cancel]` H×M
- Given the client closes the connection before the answer
- Then the Engine stops the run, as a mount call does `[existing E/rest/mounts.py:383]`
- And the input blob is deleted.
- The stop and the delete run in a shielded block, so a cancelled request cannot cancel its own
  cleanup `[proposed — review 1]`.

**CC-S35 The body is read with a running cap.** `[proposed — review 1]` H×M
- The route reads the body in pieces and stops at the cap, as the blob route does
  `[existing E/rest/blobs.py:132]`. It declares no body parameter, because the framework would
  read the full body first and answer with its own error shape.
- A parsed body needs several times its size in memory. Thus at most 4 requests with a body
  above 1 MB are in the read-and-parse phase at one time. One more waits, or gets 429 after 5 s
  `[proposed — review 2]`. The route keeps the parsed objects only until the blob is written.
- A body can come with no length header. Thus a request takes one of the 4 places when its
  running byte count passes 1 MB, and a request that waits for a place holds at most 1 MB
  `[proposed — review 3]`.

**CC-S36 Each helper error has the OpenAI shape.** `[proposed — review 1]` M×H
- Given `_schedule` or a dependency raises `ProblemException`
- Then the route answers with the OpenAI envelope. No `application/problem+json` body leaves
  this route.
- An admission refusal gives 429. A queue that is not available gives 503.

**CC-S37 The App shuts down with requests in flight.** `[proposed — review 1]` H×M
- Given a rollout while chat requests wait
- Then the drain starts when the App gets the stop signal, not in the shutdown hook of the
  framework. The server calls that hook only after each open request has ended, which is too
  late `[proposed — review 2]`.
- How: the Engine starts the server with a plain run call today `[existing E/cli.py:54]`. It
  changes to a server subclass, in the hosted and in the local start path. On the first stop
  signal, the subclass sets a drain event and then lets the server continue its normal
  shutdown. The signal handler is not on the event loop, so it sets the event through the
  thread-safe call of the loop `[proposed — review 3]`. Each waiting chat handler watches the
  event.
- A request that reaches the schedule step after the event is set gets 503
  `server_restarting` before it schedules a run.
- On the event, each handler stops its run and deletes its input blob in a shielded block, and
  answers 503 `server_restarting` (or the stream error event) with `x-should-retry: true`.
- The drain takes a few seconds, so it fits in the shutdown wait of today (5 s before the
  signal, 45 s in total) `[existing apps/screamingface-engine/deploy/helm/values.yaml:559]`.
- Reason: a chat run has no audience, so the orphan reaper never stops it
  `[existing E/reaper.py:190]`. Without the drain, the run pays until its deadline.
- Known limit: when the App crashes or is killed for memory, the runs in flight continue until
  their deadline, and their blobs wait for the sweep.

**CC-S27 The client sends the same request again.** `[proposed — gap §per-flow/repeat]` M×H
- Given an SDK retry after a time-out
- Then the Engine starts a new run. The endpoint has no idempotency key.
- And the shared cache serves the model calls that completed `[stated ans:Q15]`.

**CC-S28 The schedule step fails after the blob write.** `[proposed — gap §per-element/store]` M×L
- Then the Engine deletes the blob before it answers with the error.

**CC-S29 The `Authorization` header has any value.** `[stated ans:Q2]`
- Given a client that must send an API key
- Then the Engine ignores the header. It gives no identity and is never forwarded.

**CC-S30 The `developer` role and multi-turn text.** `[implied]`
- Given messages with roles `system`, `developer`, `user` and `assistant` and string content
- Then they pass to each model step as native messages
  `[existing E/benchmarks/contract.py:40]`.

**CC-S31 Pictures and PDFs.** `[implied]`
- Given a `user` message with `data:` picture or PDF parts
- Then the parts reach the model steps by the v2 envelope rules
  `[existing E/benchmarks/candidate_input.py:8]`.
- The route does not check before the run that each model can read pictures. A model that
  cannot gives a provider error, and the response is 502 with the sanitized code. This is a
  known limit `[proposed — review 2]`.

**CC-S32 The model list still works.** `[existing E/rest/catalog.py:115]`
- Given a client that calls `GET /v1/models` with base URL `…/v1`
- Then it gets the same list as today, and each `id` is a valid `model` value (CC-S1).

**CC-S33 A URL4 that is not a recipe.** `[implied — gap §security]` M×M
- Given a URL4 in `model` that calls other routes
- Then the same rules as `GET /?q=` apply: the same identity, the same source policy and no
  remote nodes `[existing packages/url4/src/url4/peer/server.py:257]`. The endpoint gives no new
  access. Review 1 checked the benchmark routes: they serve public Case text only, and the same
  caller can reach them through `GET /?q=` today.

### 3.4 Build decisions of U4 `[proposed — build of U4]`

The planner of U4 found cases that the scenarios above do not fix. The rules are:

- **Error `type`.** The error envelope uses the OpenAI names: 429 → `rate_limit_error`, each
  other 4xx → `invalid_request_error`, 5xx → `server_error`.
- **Errors outside the terminal table.**
  - 429 `overloaded`: `Retry-After` from the estimate of the runner (1 when it has none) and
    `x-should-retry: true`.
  - 503 `queue_unavailable` and 503 `catalog_unavailable` (the catalogue cannot be reached):
    `Retry-After: 5` and `x-should-retry: true`.
  - Each 4xx: `x-should-retry: false`.
  - Another problem from a shared helper (a 409 topic conflict, or a 503 when no job runner is
    configured): the same status, body code `internal_error`, a fixed message,
    `x-should-retry: false`.
- **Large-body parse limit (CC-S35 group).** A request that waits 5 s for one of the 4 places
  gets 429 `overloaded`, `Retry-After: 5`, `x-should-retry: true`.
- **Model id lookup.** When the App has no source of model parameters (no gateway is
  configured) and `model` is a model id: 503 `catalog_unavailable`, no `Retry-After`,
  `x-should-retry: false` (the cause is permanent, as in CC-S20). When the lookup answers with a
  status that is not 2xx: 404 `model_not_found`.
- **Recipe with no tools.** A URL4 value runs as built (ans:Q27). The route does not look up
  each route of the recipe in the catalogue. The check of a final step on a route that is not a
  model belongs to requests with tools ([tool-calls](tool-calls.md) TC-S10).
- **No cost-usage frame.** A run that succeeds with a valid result and no root cost-usage frame:
  see the ledger (owner question open on 2026-11-18; default until the answer: 200 with usage
  0/0/0, `cost_usd: null`, and a warning in the log with the trace id).
- **Metrics.** Two series: `screamingface_engine_chat_requests_total{outcome}` (the body code,
  or `ok`) and the histogram `screamingface_engine_chat_request_duration_seconds`.
- **OpenAPI.** A tag `Chat` whose description says that this path uses the OpenAI
  `{"error": …}` envelope, and one sentence in the API description.

## 4. Non-functional requirements

- **Overhead.** Time from request accept to the first model call on a hosted Engine with an idle
  warm child: p50 ≤ 500 ms, p95 ≤ 2.5 s `[proposed]`. The repo measured 350 ms and 1.6 s for a
  mount call `[existing apps/screamingface-engine/docs/plans/uniform-executor/measurements/parity-gate.md:200]`.
- **Time limit.** `chat_max_wait_s` = 600 s (a setting) `[proposed]`. The run deadline is the
  limit plus 5 s, as for a mount `[existing E/rest/mounts.py:372]`. The route time-out of the
  hosted edge is the job deadline `[existing apps/screamingface-engine/deploy/helm/templates/httproute.yaml:60]`.
- **Capacity.** One request holds one worker slot for its whole duration. A worker has 4 slots
  `[existing E/runner_queue.py:81]`. Chat runs and evaluation runs share one queue
  `[existing E/subjects.py:23]`.
- **Observability.** Metrics: a request counter by outcome and a duration histogram with the
  route label `/v1/chat/completions` `[proposed]`. Logs carry the trace id, the digest and the
  sizes, never message content `[proposed]`.
- **App memory.** With the body limits of CC-S35, the App stays inside its 512 Mi limit with 8
  concurrent requests of 8 MB `[proposed — review 1]`. The plan measures this.
- **Security.** Each request field is untrusted. The route validates types and sizes before the
  blob write `[proposed]`. The topic is never returned to the client `[proposed]`. The blob store
  treats the run id as a bearer secret `[existing E/artifacts/blobs.py:23]`. The response gives
  `trace_id`. Note: a mount call returns its topic in a response header today
  `[existing E/rest/mounts.py:396]`; the reviewer can choose that rule here.
- **Layering.** The route is in `E/rest/`. It parses the recipe and never evaluates it
  `[existing .claude/scripts/check_layering.py:48]`.

## 5. Out of scope

- API keys and Bearer authentication `[stated ans:Q2]`.
- Named recipe aliases and a recipe list in `/v1/models` `[stated ans:Q3]`.
- The Anthropic Messages format and the OpenAI Responses format `[stated ans:Q12]`.
- A budget field in the request. A `WithBudget` recipe keeps its own budget.
- `/v1/completions`, `/v1/embeddings` and audio.

## 6. Open questions

None. The blob retention question (overview OQ-1) is closed.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: outside-in for the HTTP contract, on a stub job runner. The tests that protect identity,
size limits and money come first.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| CC-1 | `hosted_request_without_identity_is_401_and_starts_no_run` | unit | [stated ans:Q2] | H×M | identity dependency of mounts |
| CC-2 | `authorization_header_gives_no_identity_and_is_not_forwarded` | unit | [stated ans:Q2] | H×M | no code reads it |
| CC-3 | `body_over_cap_is_413_before_blob_write` | unit | [proposed] | H×M | stream-length check |
| CC-4 | `invalid_shape_is_400_with_param_in_openai_envelope` | unit | [proposed] | M×H | validate the parsed bytes in the handler; no declared body parameter |
| CC-5 | `gateway_model_id_becomes_one_model_recipe_without_instruction` | unit | [stated ans:Q16] | H×M | resolver adapter 1 |
| CC-6 | `candidate_url4_is_used_unchanged` | unit | [stated ans:Q3] | H×M | resolver adapter 2 |
| CC-7 | `unknown_model_is_404_model_not_found` | unit | [stated ans:Q16] | M×M | catalogue port |
| CC-8 | `corrective_loop_recipe_is_400_recipe_not_supported` | unit | [implied] | M×M | recipe check in `E/chat/recipe.py` |
| CC-9 | `linked_expression_is_400_with_hint` | unit | [proposed] | L×M | detect embedded `candidate` |
| CC-10 | `request_schedules_chat_shape_with_blob_ref_and_deadline` | unit | [stated ans:Q6] | H×M | call `_schedule(shape="chat")` |
| CC-11 | `blob_is_written_before_schedule_and_deleted_on_schedule_failure` | unit | [proposed] | H×L | order + cleanup |
| CC-12 | `usage_and_cost_come_from_the_root_cost_usage_frame` | unit | [stated ans:Q13] | H×H | own scan of the topic; map the frame to `usage` and `cost_usd` |
| CC-13 | `abstained_result_is_200_empty_content_with_status` | unit | [stated ans:Q10] | H×M | translate |
| CC-14 | `each_row_of_the_terminal_table_gives_its_status_code_and_retry_header` | unit | [stated ans:Q10] | H×H | table test over (state, raw code) |
| CC-15 | `sampling_fields_are_accepted_and_not_stored_in_chat_input` | unit | [stated ans:Q14] | H×M | drop at validation |
| CC-16 | `n_above_one_and_logprobs_are_400_unsupported_parameter` | unit | [proposed] | M×M | explicit refuse list |
| CC-17 | `inflight_cap_is_429_with_retry_after` | unit | [existing E/runner_queue.py:127] | M×M | map 503 shed to 429 |
| CC-18 | `time_limit_stops_run_then_504` | unit | [proposed] | H×M | `wait_terminal_or_gone` bound |
| CC-19 | `client_disconnect_stops_run_and_deletes_blob` | unit | [implied] | H×M | `finally` block |
| CC-20 | `cache_participates_by_default_and_no_store_turns_it_off` | unit | [stated ans:Q15] | M×M | `_converge_cache`; assert both directions |
| CC-21 | `response_never_contains_the_topic` | unit | [proposed] | H×L | trace id only |
| CC-22 | `local_stack_fusion_answers_openai_sdk_request` | E2E | [stated ans:Q1] | H×M | replay lane with cached calls, no provider key |
| CC-23 | `get_v1_models_is_unchanged` | CHAR | [existing E/rest/catalog.py:115] | M×L | passes today |
| CC-24 | `unknown_client_fields_are_accepted_and_ignored` | unit | [proposed] | M×H | wire model allows extra keys and drops them |
| CC-25 | `remote_media_url_is_400_unsupported_content` | unit | [existing E/benchmarks/candidate_input.py:371] | M×M | `data:` check at validation |
| CC-26 | `missing_blob_store_is_503_chat_unavailable` | unit | [proposed] | M×L | fail closed before any work |
| CC-27 | `refused_result_maps_to_refusal_message_and_content_filter` | unit | [implied] | M×M | translate |
| CC-28 | `worker_loss_or_memory_breach_is_503_run_failed` | unit | [implied] | M×L | failure table |
| CC-29 | `multi_turn_text_and_developer_role_pass_as_native_messages` | integration | [implied] | H×M | stub gateway body equals the client messages |
| CC-30 | `picture_parts_reach_model_steps_as_v2_parts` | integration | [implied] | M×M | v2 envelope path |
| CC-31 | `remote_node_in_model_is_refused_as_on_get_q` | integration | [existing packages/url4/src/url4/peer/server.py:257] | H×L | existing guard; no new access |
| CC-32 | `unparsable_url4_is_400_recipe_invalid` | unit | [implied] | M×M | `url4.build` error → envelope |
| CC-33 | `model_over_32000_chars_is_413` | unit | [proposed] | M×L | length check before parse |
| CC-34 | `non_json_content_type_is_415_before_body_read` | unit | [proposed] | H×M | header check first |
| CC-35 | `body_read_stops_at_cap_and_large_parses_are_limited_to_four` | unit | [proposed] | H×M | running cap + a limit of 4 on bodies above 1 MB; worst-case shape of many small messages |
| CC-36 | `timeout_and_permanent_failures_send_x_should_retry_false` | unit | [proposed] | H×M | header table |
| CC-37 | `problem_exceptions_are_re_enveloped_in_openai_shape` | unit | [proposed] | M×H | catch at the route; shed → 429, queue down → 503 |
| CC-38 | `failure_code_and_message_come_from_sanitized_error` | unit | [existing E/rest/routes.py:88] | H×M | provider text never reaches the body |
| CC-39 | `stop_signal_drains_waiting_chat_requests_before_server_shutdown` | integration | [proposed] | H×H | run the server in a subprocess and send it the real stop signal; a direct call of a hook cannot fail for this reason |
| CC-40 | `model_id_with_colon_resolves_through_model_parameters_lookup` | unit | [proposed] | M×M | classification rule: starts with `(` or not |
| CC-41 | `cleanup_runs_when_the_request_task_is_cancelled` | unit | [proposed] | H×M | shielded stop and delete |
| CC-42 | `content_type_with_charset_parameter_is_accepted` | unit | [proposed] | M×H | compare the media type only |
| CC-43 | `catalog_lookup_failure_is_503_and_lookups_are_kept_60_s` | unit | [proposed] | M×M | catalogue port stub |
| CC-44 | `unpriced_run_reports_cost_null_not_zero` | unit | [proposed] | H×M | frame with `unpriced` |
| CC-45 | `fully_cached_turn_reports_zero_usage` | unit | [stated ans:Q26] | M×M | frame of a cached run |
| CC-46 | `missing_blob_store_is_permanent_and_queue_down_is_retryable` | unit | [proposed] | M×M | CC-S20 and CC-S38 |
| CC-47 | `encoded_record_over_cap_is_413` | unit | [proposed] | M×L | boundary on the encoded record, not only on the body |
| CC-48 | `request_after_drain_event_is_503_before_schedule` | unit | [proposed] | M×M | check the event before `_schedule` |

Scenario without its own test: CC-S27 (client retry). It has no behaviour beyond a new run.

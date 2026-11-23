# PRD — `sf.InferenceClient` and `chat.completions.create`

Tags as in `00-overview.md` §2. Contract references (C1, C2, ...) are sections of
`contracts.md`. Risk is given as likelihood × impact (H, M, L).

## 1. User story

As an SDK user, I make an ensemble with the SDK and I call it as I call a model with the OpenAI
SDK or LiteLLM: one object, `.chat.completions.create("prompt")`, and a reply with the field names that I
know `[stated ans:Q1]`.

## 2. Current behaviour

- The SDK runs a recipe only through `sf.evaluate`, which needs a benchmark
  `[existing S/client.py:405]`.
- The compiler turns a recipe into Candidate URL4 text with no benchmark; it is private
  `[existing S/_evaluation/candidate.py:136]`.
- A recipe with a reducer needs the operator catalogue; without it the compiler raises
  `ValueError` `[existing S/_evaluation/candidate.py:808]`. A corrective loop with no benchmark
  raises `PlanningError` with a text about a benchmark `[existing S/_evaluation/corrective.py:137]`.
- A paid single call of today, `sf.classify`, is never sent again by the client
  `[existing S/client.py:571]`.
- The Engine route of PR #1937 runs a Candidate URL4 or a gateway model id for chat messages
  `[existing E/rest/chat_completions.py]`.

## 3. Scenarios

### 3.1 Happy path

**MI-S1 One prompt, one reply.** `[stated ans:Q1]`
- Given `llm = sf.InferenceClient(sf.Model("openrouter/a"))` and a reachable Engine
- When `reply = llm.chat.completions.create("Hello")`
- Then the SDK sends one streamed request (C2.1) with the compiled recipe as `model` and one
  user message
- And `reply` is a `ChatCompletion`; `reply.text == reply.choices[0].message.content`
- And `reply.usage`, `reply.cost_usd` and `reply.trace_id` have the values of the Engine.

**MI-S2 An ensemble.** `[stated ans:Q1]`
- Given a Fusion, a Pipeline, a Gate or a Cascade made with the SDK
- Then `InferenceClient` compiles it to the same Candidate URL4 text that an evaluation of the
  same recipe uses as its candidate `[implied]`.

**MI-S3 Messages and tools.** `[stated ans:Q2]`
- When `llm.chat.completions.create(messages=[...], tools=[...])`
- Then the SDK sends both lists with no change, and `reply.tool_calls` has the calls of the
  final step, each with its full `arguments` text.

**MI-S4 Async.** `[stated ans:Q7]`
- Given `allm = sf.InferenceClient(ensemble, client=sf.AsyncClient())`
- When `reply = await allm.chat.completions.create("Hello")`
- Then the result is the same `ChatCompletion`, and no thread blocks.

**MI-S5 Chunks.** `[stated ans:Q2]`
- When `for chunk in llm.chat.completions.create("Hello", stream=True)`
- Then the caller gets the chunks of the Engine in order, with no keep-alive line; the last chunk
  with a choice has the `finish_reason`
- And with `stream_options={"include_usage": True}` one more chunk follows, with empty `choices`,
  `usage` and `screamingface` `[proposed P6]`.

**MI-S6 A model id or URL4 text.** `[proposed P1]`
- `sf.InferenceClient("openrouter/a")` sends the string as a gateway model id.
- `sf.InferenceClient("(model_1:0.0:...)!...")` or a `sf.Url4` with Candidate URL4 text sends the
  text with no change.

**MI-S6b An evaluation URL4.** `[proposed P14]`
- Given `sf.InferenceClient(report.candidates["x"].url4)` (the URL4 of an evaluation)
- Then the SDK takes the `candidate` source of the expression and sends that text
- And an evaluation URL4 with no `candidate` source gives `PlanningError` before a request.

### 3.2 Alternative paths

**MI-S7 A recipe with a reducer.** `[existing S/_evaluation/candidate.py:808]`
- Given a recipe with `sf.Vote()` (or another reducer)
- Then the constructor sends no request; it does the shape checks that need no catalogue
- And each `create` (or `endpoint`) compiles the recipe with the operator catalogue that the
  client keeps; in the max-age of the catalogue, only the first call sends the catalogue request
  `[proposed P2]`.

**MI-S8 An ignored parameter.** `[stated ans:Q3]`
- When `llm.chat.completions.create("Hello", temperature=0.2, max_tokens=50)`
- Then the call works, the request has neither parameter, and the SDK gives one
  `IgnoredParameterWarning` for each name; the text points to `sf.Model(params=...)`.
- And a keyword that is not a known OpenAI chat parameter (for example the typo `tool=[...]`)
  gives `TypeError`, so tools cannot be lost silently `[proposed P4]`.

**MI-S9 No cache.** `[existing E/cache_intent.py:78]`
- When `use_cache=False`, the request has `Cache-Control: no-store`. With the default, it has no
  such header.

**MI-S10 A reply that is not an answer.**
- When the run abstains or refuses, the reply is a normal `ChatCompletion` with
  `reply.screamingface.status` `abstained` or `refused`; `reply.text` can be `None`. No error is
  raised `[existing E/rest/chat_answer.py:172]`.

**MI-S11 The caller stops a stream early.**
- When the caller leaves the loop and calls `close()` (or leaves the `with` block)
- Then the SDK closes the connection, and the Engine stops the run `[proposed P6]`.

### 3.3 Errors and edges

**MI-S12 A wrong argument.** `[proposed P3]`
- No prompt and no messages, or both: `TypeError`. Empty messages or a blank model string:
  `ValueError`. A `model` or `client` of a wrong type: `TypeError`. No request is sent.

**MI-S13 A recipe that the route cannot run.** `[existing E/chat/recipe.py:167]`
- A recipe with a corrective loop gives `PlanningError`, code `recipe_not_supported`, from the
  constructor, with a text about the chat route and not about a benchmark `[proposed P17]`.
- A step with `over='benchmark'` gives the `ValueError` of the compiler; no chat request is sent
  `[existing S/_evaluation/answer_rule.py:84]` `[proposed P17]`.
- `n=2`, `logprobs=True`, `audio`: `PlanningError`, code `unsupported_parameter`, before a
  request `[proposed P4]`.
- A recipe that the Engine refuses (for example tools with a Cascade) gives `PlanningError` with
  the code of the Engine (`recipe_not_supported`, `final_step_not_model`, ...).

**MI-S14 The Engine refuses or fails before the run.** (C2.4)
- 429 `overloaded`: `ExecutionError`, `permanent` false, `details["retry_after"]`.
- 401 or 403: `AuthenticationError`. 404 `model_not_found`: `PlanningError`.
- An Engine with no chat route: `EngineCapabilityError` with a hint to upgrade the Engine.
- No connection: `EngineUnavailableError`.

**MI-S15 The run fails after the stream started.** `[stated ans:Q5]`
- Given an error event with `code: "server_restarting"`, `should_retry: true`, `retry_after: 5`
- Then `ExecutionError` with that code, `permanent` false and `details["retry_after"] == 5`
- And with `should_retry: false` (for example `timeout`), `permanent` is true.
- With `stream=True`, the error is raised by the iteration.
- An event with no `should_retry` key (an Engine of PR #1937 before this change) gives a
  permanent error `[proposed]`.

**MI-S16 The connection breaks or goes silent.** `[proposed P11]`
- When the connection ends before `[DONE]`, or 60 s pass with no byte
- Then `ExecutionError`, code `inference_outcome_unknown`; the SDK does not send the call again,
  also with `max_retries` above 0.

**MI-S17 The caller time limit.** `[proposed P11]`
- When `timeout=5` and no reply is complete in 5 s
- Then `ExecutionError`, code `client_timeout`, and the connection is closed.

**MI-S18 Retry is opt-in.** `[stated ans:Q4]`
- With the default, a retryable error is raised after one request.
- With `max_retries=2`, the SDK sends the call again only for an error that the Engine marked as
  safe; it waits for `Retry-After`; it stops at the third failure and raises the last error.

**MI-S19 A sign-in challenge.** `[proposed P15]` `[existing S/_access/auth.py:662]`
- When the edge of a hosted Engine answers the POST with a challenge (302, 401 or 403), the
  client signs in and sends the request one more time. No run exists at that point, because the
  answer for a scheduled run has the status 200.
- A 408, 429 or 5xx from the Engine is never sent again by the client layer
  `[existing S/client.py:92]`.

### 3.4 Concurrency

**MI-S20 Two calls at one time.** `[proposed]`
- Two threads (or two tasks) call `create` on one object with a reducer recipe at the same
  time. Each gets its reply. The object has no state that a call changes.

**MI-S20b The default client changes.** `[existing S/_default_client.py:173]`
- Given `llm = sf.InferenceClient(ensemble)` with no `client`
- When the user calls `sf.close()` or `sf.configure(...)` and then `llm.chat.completions.create(...)`
- Then the call uses the default client of that moment, as `sf.classify` does.
- An explicit client that is closed gives the `RuntimeError` of the client, before a request.

### 3.5 Privacy

**MI-S21 No content leaves through side channels.** `[proposed P9]`
- The SDK sends no analytics event for an inference call in this version
  `[existing apps/analytics/src/analytics_service/contract.py:33]`.
- The SDK writes no reply to disk. A log line of the SDK has no message text and no header value.

## 4. Out of scope

See `00-overview.md` §5.3.

## 5. TDD plan (risk first)

Each test is written first and must fail for the reason in the last column. Tests use
`httpx.MockTransport` through `http_transport=` `[existing packages/screamingface/tests/test_classify.py:59]`.

| # | Test | Level | Scenario | Risk | RED reason / GREEN note |
|---|---|---|---|---|---|
| MI-1 | `typed_overloads_give_exact_results_for_each_client_and_stream_value` (the six rows of C1.2, and the two constructor forms) | typing (pyright, `assert_type`) | MI-S4, C1.2 | H×H | the class does not exist; proves risk R3 before other work |
| MI-2 | `chat_post_is_not_sent_again_after_408_429_5xx` | unit | MI-S19 | M×H | pins the rule on the new POST seam |
| MI-3 | `chat_post_is_sent_once_more_after_a_sign_in_challenge` | unit | MI-S19 | M×H | RED: the seam has no replay-safe mark |
| MI-4 | `frames_build_the_reply_of_the_plain_route` (text, refusal, tool calls, no usage frame, abstained) | unit, pure | C2.3 | H×H | the frame reader does not exist; table of cases |
| MI-5 | `malformed_or_cut_stream_is_invalid_response` (not JSON, no `[DONE]`, wrong shape) | unit, pure | C2.3 | M×H | |
| MI-6 | `one_prompt_sends_one_streamed_request_and_gives_a_reply` | unit | MI-S1 | H×H | checks method, path, headers, body |
| MI-7 | `recipe_compiles_to_the_candidate_text_of_an_evaluation` (Model, Fusion, Pipeline, Gate, Cascade) | unit | MI-S2 | M×H | compare with `compile_candidate` |
| MI-8 | `model_string_rule_matches_the_engine` (`(` prefix, white space, id, `Url4`, blank) | unit | MI-S6, MI-S12 | M×M | |
| MI-9 | `constructor_uses_no_network`, `reducer_recipe_loads_the_catalogue_once_at_first_call` | unit | MI-S7 | M×M | count the requests |
| MI-10 | `corrective_loop_is_recipe_not_supported_from_the_constructor` (also inside `WithBudget`); `compiler_errors_keep_their_type` (`over='benchmark'`) | unit | MI-S13 | M×M | no chat request in each case |
| MI-11 | `error_map_before_the_stream` (each row of C2.4, table) | unit | MI-S14 | H×M | |
| MI-12 | `error_event_maps_should_retry_and_retry_after` | unit | MI-S15 | H×M | |
| MI-13 | `broken_or_silent_connection_is_outcome_unknown_and_is_not_retried` | unit | MI-S16 | M×H | |
| MI-14 | `caller_timeout_closes_the_connection` | unit | MI-S17 | M×M | |
| MI-15 | `no_retry_by_default`, `max_retries_obeys_the_engine_flag_and_retry_after` | unit | MI-S18 | M×H | fake clock |
| MI-16 | `known_parameter_warns_and_is_not_sent`; `refused_parameters_raise`; `unknown_keyword_is_a_type_error` | unit | MI-S8, MI-S13 | M×M | `pytest.warns` |
| MI-17 | `use_cache_false_sends_no_store`; `each_call_has_a_new_traceparent` | unit | MI-S9 | L×M | |
| MI-18 | `messages_and_tools_are_sent_unchanged`; `tool_calls_are_on_the_reply` | unit | MI-S3 | M×M | |
| MI-19 | `argument_errors` (table) | unit | MI-S12 | L×M | |
| MI-20 | `stream_true_gives_the_engine_chunks_in_order`; `include_usage_adds_the_last_chunk` | unit | MI-S5 | M×M | |
| MI-21 | `closing_a_stream_early_closes_the_connection`; `error_event_raises_from_the_iteration` | unit | MI-S11, MI-S15 | M×M | |
| MI-22 | `async_client_gives_the_same_reply`; `async_stream`; `async_errors_raise_at_the_await` | unit (asyncio) | MI-S4 | M×H | |
| MI-23 | `abstained_and_refused_are_replies` | unit | MI-S10 | L×M | |
| MI-24 | `two_calls_at_one_time_on_one_object` (threads; tasks) | unit | MI-S20 | L×M | |
| MI-25 | `no_analytics_event_is_sent`; `nothing_is_written_to_disk`; `log_lines_have_no_content` | unit | MI-S21 | L×H | |
| MI-26 | `reply_to_dict_has_the_openai_keys`; `reply_types_are_frozen` | unit | C1.3 | L×L | |
| MI-27 | `public_surface_has_the_new_names` (snapshot) | unit | C1.6 | L×M | regenerate the snapshot; changelog entry |
| MI-28 | `model_inference_with_the_real_local_engine` | integration (SDK e2e harness, fake gateway) | MI-S1, MI-S3, MI-S5 | M×H | one plain call, one tool call, one stream; no paid call |
| MI-29 | `default_client_is_taken_at_each_call`; `closed_client_raises_before_a_request` | unit | MI-S20b | M×M | |
| MI-30 | `evaluation_url4_sends_its_candidate_source`; `evaluation_url4_with_no_candidate_is_a_planning_error` | unit | MI-S6b | M×M | |
| MI-31 | `error_event_with_no_flag_is_permanent`; `max_retries_works_with_stream_true` | unit | MI-S15, MI-S18 | M×M | |

## 6. Open questions

None. Each product question is in the interview ledger. The proposals P1–P17 need your sign-off.

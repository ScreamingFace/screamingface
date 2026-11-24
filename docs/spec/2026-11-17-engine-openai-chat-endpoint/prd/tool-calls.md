# PRD: chat completion with tools (the last model step decides)

**Source:** ans:Q5, ans:Q6, ans:Q8, ans:Q9, ans:Q14 · **Priority:** P1 (agents need it)
**Lifecycle:** planned · **Owner:** unassigned

## 0. Tool calls are turned off for now (2026-11-24)

Team feedback through the owner (verbatim): "disable the tool usage feature for now. So we must
provide a proper error if someone tries to use / declare tools for now." Owner answers of
2026-11-24 (ledger of `docs/spec/2026-11-18-sdk-model-inference/00-overview.md` §5.7):
the Engine and the SDK refuse; declared tools and tool turns count; a fixed refusal with no
switch, and the tool code stays.

- **TC-S23** `[stated owner 2026-11-24]`. Given a request that declares or uses a tool, when the
  boundary checks it, then the answer is HTTP 400, code `tools_not_available`, type
  `invalid_request_error`, `x-should-retry: false`, with the fixed message, and `param` names
  the first place. No run starts, no blob is written and the model catalogue is not read. A
  request with `stream: true` gets the same JSON answer.
  - Tool use is: `tools` with at least one item (`param` `tools`); `functions` with at least
    one item (`functions`) `[proposed]`; a `tool` message (`messages[i]`); an assistant message
    with at least one item in `tool_calls` (`messages[i].tool_calls`).
  - Not tool use: `tools: []` or `null` (TC-S13), `functions: []`, `tool_calls: []` or `null`,
    `tool_choice`, `function_call`, `parallel_tool_calls`. They are accepted as before.
  - Order: `invalid_request` (a wrong shape) and `unsupported_parameter` come before this check.
- The check is fixed: `rest/chat_body.py::_tool_use`. No setting turns it off
  `[stated owner 2026-11-24]`.
- The tool code stays (the final-step route, the views, the recipe checks, the wire types), and
  no request can reach it. Its route tests run with the check removed by a test-only fixture
  (`tests/unit/_chat_tools_reachable.py`) `[proposed]`. The scenarios below (TC-S1 to TC-S22)
  describe that code; they do not describe the route of today.
- Test: TC-23, `tests/unit/test_chat_completions_tools_off.py`.
- To turn tool calls on again: remove the check and its test, remove the fixture, and put the
  docs sections back.

## 1. Summary and user story

As a coding agent, I send my tools with each request. I want the last model step of the ensemble
to decide the tool calls, so that the ensemble works in my agent loop. "tools are important to
support (for agentic workflows)" `[stated ans:Q5]`. "the last LLM inference step of that ensemble
might be able to make the required decisions" `[stated ans:Q8]`.

## 2. Background and constraints

- "deterministic reducers at the final step shouldn`t be supported in `with tools` scenarios."
  `[stated ans:Q9]`
- The base HTTP rules are in [chat-completion](chat-completion.md). The run is in
  [chat-run](chat-run.md). The transport is in [gateway-transport](gateway-transport.md).
- Today the Engine owns `tools`. An expression cannot set `tools`, `tool_choice` or `stream`
  `[existing E/world/request_parameters.py:30]`.
- The existing loop runs each tool call that a model returns. It is made for the Engine web tools
  `[existing E/world/connector.py:1653]`. This feature does not change it `[stated ans:Q6]`.
- The envelope refuses a `tool` role and an assistant message with `tool_calls`
  `[existing E/benchmarks/contract.py:40]` `[existing E/benchmarks/candidate_input.py:210]`.
- Each model call of a recipe is a URL4 source with a `binding=` parameter
  `[existing E/world/branch.py:800]`. The branch routes are pure routes over recorded calls
  `[existing E/world/branch.py:1]`, and the combine route is pure CPU work
  `[existing E/combine/endpoint.py:14]`. Thus the Engine can find the final model step before
  the run.
- Engine runtime routes are registered after the direct-mount snapshot, so they are never public
  mounts `[existing E/world/factory.py:171]` `[existing E/world/factory.py:252]`.
- The gateway forwards `tools` for OpenRouter and Hugging Face (cache-keyed), and for Anthropic,
  Gemini and Ollama (no cache) `[existing G/plugins/openrouter_provider/parameters.py:303]`
  `[existing G/plugins/anthropic_provider/parameters.py:150]`. Each model row lists
  `supported_parameters` `[existing G/core/model_capabilities.py:72]`.

## 3. Rules

### 3.1 Final positions

A **final position** is a place in the recipe whose output can be the answer of the recipe. The
recipe check finds all final positions from the parsed expression `[proposed]`.

| Root or branch ends in | Final position | With tools |
|---|---|---|
| `$model_N`, or `$synthesis_N` on a model route | that model step | allowed |
| `$synthesis_N` on `/ensemble/combine/v1` | a deterministic reducer | refused `[stated ans:Q9]` |
| `$gate_N_block` | each branch, by this table again | allowed only if no branch is a reducer `[implied]` |
| an outcome (`abstain`, `fail`) or a fixed word in a branch | no model step | allowed; that branch cannot call tools |
| `$loop_candidate` | a corrective loop | refused always ([chat-completion](chat-completion.md) CC-S14) |
| a form that the check cannot classify | unknown | refused (fail closed) `[proposed]` |

**Effect on Cascades and step Gates.** Each tier of an `sf.Cascade` ends in a reducer step. A
tier with one model becomes a one-member Vote
`[existing packages/screamingface/src/screamingface/_surface/cascade.py:205]`, and the Cascade
builds `Gate(then=step)` on it
`[existing packages/screamingface/src/screamingface/_surface/cascade.py:281]`. A Gate with
`then=<reducer step>` is the same case. Thus, with tools, each Cascade and each step Gate is
refused with `final_step_not_model` `[stated ans:Q9]`. The user can add a final model stage after
it (`cascade >> model`). Then the final position is that model, and the request is allowed.

**The `>> model` way runs as built** `[stated ans:Q27]`. When the Cascade abstains, its output is
empty text, and the final model stage still runs on it. The response is then a normal answer of
that model, not an abstain. The same recipe behaves this way in a Benchmark. The docs state it.

### 3.2 The final-step endpoint

- When the request has tools, the handler points each final model step to an internal route:
  `/ensemble/chat/v1/final/<route id>` `[proposed]`. The route id is the path form of the model
  (with `~` for `:`) `[existing E/world/models/registry.py:48]`. The change is in the run's copy
  of the expression only. The `model` value of the client is not changed.
- The re-point algorithm `[proposed — review 1]`:
  1. Find the final positions from the root intent and, for each Gate, from its gate spec and
     branch kinds.
  2. A Gate branch body is text inside the expression, not parsed nodes
     `[existing packages/url4/src/url4/core/nodes.py:238]`. Parse each body with the existing
     helper `[existing E/benchmarks/operation_outputs.py:302]` and recurse, at each depth.
  3. Select a source by its **binding name**, never by its path. A member and a synthesizer can
     use the same route with the same parameters.
  4. Change the path of each selected source, and add `binding=<name>` when the source has no
     such parameter, so the endpoint knows its binding.
  5. Render each changed body again. Check that parse and render round-trip, and that only the
     selected bindings changed.
- A recipe from a client must not name the final-route prefix. The recipe check refuses it at
  each depth, Gate bodies included `[proposed — review 1]`. The endpoint also fails closed with
  a permanent error when no chat turn is bound to the run.
- The route is registered for each declared model `[proposed]`. The endpoint needs the gateway
  HTTP client, the gateway config and the model routes. The function that installs the combine
  and branch routes gets only the node `[existing E/world/factory.py:171]`. Thus the chat routes
  have their own installer, which receives the gateway world. It runs after the direct-mount
  snapshot `[existing E/world/factory.py:252]`, and the App filters its mount table by that
  snapshot, so the routes are never public mounts. It runs also in a world with no Benchmarks
  ([chat-run](chat-run.md) CR-S19) `[proposed — review 2]` `[proposed — review 4]`.
- The endpoint makes exactly one request to the gateway. It has no loop and it runs no tool
  `[stated ans:Q6]`.
- The request body has: the model, the native messages (§3.5), the client `tools`, and the
  parameters that the recipe sets for that step `[proposed]`.
- The body has no `tool_choice` and no client sampling field `[stated ans:Q14]`.
- Web search on the final step with client tools `[proposed — effect of ans:Q30]`:
  - The endpoint has no tool loop, so it never offers the Engine web tools (the search and fetch
    tools that the Engine runs itself `[existing E/world/config.py:184]`). On a route that uses
    them, the final step does not search, also when the route default is on.
  - On a route where the provider does the search itself `[existing E/world/config.py:178]`, the
    endpoint keeps the route rule and sets the search flag as the existing endpoint does
    `[existing E/world/connector.py:1840]`.
  - The endpoint derives this itself: when `wants_web_search` is true and the route uses provider
    search, the body gets `"web_search": true` and the excluded domains of the step
    `[existing E/world/request_parameters.py:54]`. It does not call the request builder of the
    existing endpoint, because that builder adds the Engine tools and a forced tool choice
    `[existing E/world/connector.py:1846]` `[proposed — review 4]`.
  - A recipe that sets `web_search=true` on a final step whose route uses the Engine web tools
    is refused (TC-S11), because the recipe asks for a search that this step cannot do.
- The endpoint calls the shared round-trip function ([gateway-transport](gateway-transport.md))
  `[stated ans:Q11]`. Thus the final step has the same identity headers, cache policy, cache
  read-back, retries on 429 and 5xx, deadline, heartbeat and cost reports as each other step
  `[proposed — review 1]`.
- The endpoint changes a refusal into the same error form as the existing endpoint
  `[existing E/world/connector.py:557]`, so a refusal of the final step gives a `refused` result.
- The endpoint writes the model outcome and one operation-call record with the binding of the
  step `[existing E/operation_calls.py:150]` `[existing E/operation_calls.py:184]`. Thus
  attribution, abstain detection and the budget ledger work as for other steps `[implied]`.
- The endpoint returns the content text to the URL4 engine. It gives the tool calls to the
  handler through a run-scoped collector, bound as the blob reader is bound
  `[existing E/world/attachment_parts.py:91]`.
- The run uses the shared cache for this request as for other calls `[stated ans:Q15]`.

### 3.3 What each step sees

| Step | Conversation | Tools |
|---|---|---|
| each step that is not final (member, judge, signal source, selector, earlier stage) | the TEXT_VIEW (§3.4), on the existing model endpoint | the list as text; it cannot call them |
| the final model step, request with tools | the native messages (§3.5), on the final-step endpoint | the client `tools`, native |
| the final model step, request with no tools | the TEXT_VIEW, on the existing model endpoint | none |

### 3.4 The text view `[proposed]`

The text view is a valid candidate-input envelope ([erd](../erd.md) §2.3).

0. First, each message is rebuilt as `{role, content}` only. A content list with text parts only
   becomes one string; the parts join with a line feed, as the gateway joins text parts
   `[proposed — build review of U2]`. Empty text parts are dropped. Reason: the envelope refuses a part list
   on a v1 message, a part list with no picture, an empty text part, parts on a role other than
   `user`, and extra keys `[existing E/benchmarks/candidate_input.py:212]`
   `[existing E/benchmarks/candidate_input.py:237]` `[proposed — review 1]`.
1. `system`, `developer`, `user` and `assistant` messages with string content stay as they are.
2. An `assistant` message with tool calls becomes one `assistant` message. Its content is the
   original text, then one line for each call: `[tool_call id=<id> name=<name>] <arguments>`.
3. A `tool` message becomes a `user` message: `[tool_result id=<id>] <content>`. Tool messages
   in sequence join into one `user` message.
4. When the request has tools, the first message is a `system` message. It says that only the
   final step can call tools, and it lists each tool with its name, description and parameter
   schema as compact JSON.
5. Picture and PDF parts stay as parts on `user` messages.
6. The rendering is deterministic: the same input gives the same bytes, so the shared cache works.

### 3.5 The native messages of the final step `[proposed]`

1. One `system` message with the instruction of the step (the intent of its URL4 source), when
   it is not empty.
2. The client messages, with no change, with their tool calls and tool results. "No change"
   includes keys that the Engine does not know inside a message, a content part, a tool call or
   a tool definition (for example `reasoning_details` or `cache_control`): the request models
   keep them, and the final step sends them. Unknown keys at the top level of the request are
   ignored (ans:Q14). The text view never shows an unknown key `[proposed — build review of U2]`.
3. When the context of the step is not the bare input and is not empty, one last `user` message
   with that context (for example the member outputs). An empty context adds no message
   `[proposed — review 2]`. In it, the conversation is replaced by a short marker, as
   the Fusion context does for pictures today `[existing E/world/fusion_context.py:86]`.

### 3.6 Build decisions and known limits of U6 `[proposed — build of U6]`

- **Duplicate final binding.** With tools, a final model position whose binding name has more
  than one source at its scope is refused before the run with 400 `recipe_not_supported`. With
  no tools the recipe runs as built. The run-time code `final_step_ambiguous` stays as the last
  guard.
- **The App check and the run check of TC-S11 can differ.** The App (control plane) does not
  read the route table of the operator. It decides "this route uses the Engine web tools" from
  the model id with the default route rule. The final-step endpoint decides from the declared
  route. They differ only when an operator declares a route flag that is not the default. Then
  the run refuses, and the client gets 502 `internal_error` (the refusal codes of the run are
  not in the terminal table of [chat-completion](chat-completion.md)).
- **No picture admission for the final step.** The existing model endpoint checks, before any
  call of a run, that each model can read the files of the run (OME-1809). The re-pointed final
  step is not in that check. A request with pictures and tools whose final model cannot read
  pictures fails at the final step, after the earlier steps ran. The docs page states this limit.
- **No answer seed and no attempt field** on the final-step request. A chat run has none today.
- **Error translation.** The final-step endpoint repeats the block of the existing endpoint
  that changes a gateway refusal into a run error. A shared helper in `gateway_transport` is a
  follow-up, because this feature does not change `connector.py` after the move.

## 4. Scenarios and acceptance criteria

### 4.1 Happy path

**TC-S1 One model with tools.** `[stated ans:Q5]`
- Given `model` is a gateway model id and the request has tools
- When the model returns tool calls
- Then the response has `message.tool_calls` with `id`, `type: "function"`,
  `function.name` and `function.arguments`, with no change
- And `finish_reason` is `tool_calls` and `content` is the text of the model or null.

**TC-S2 A Fusion with a synthesizer.** `[stated ans:Q8]`
- Given a Fusion of two members and a model synthesizer, and a request with tools
- Then each member gets the text view on the existing endpoint and gets no native tools
- And the synthesizer gets the native messages, the member outputs and the tools on the
  final-step endpoint
- And its tool calls are the response.

**TC-S3 The next turn carries tool results.** `[stated ans:Q5]`
- Given a follow-up request with the assistant tool calls and the `tool` results
- Then the non-final steps see them as text (§3.4) and the final step sees them natively.

**TC-S4 A Gate with model branches.** `[stated ans:Q8]`
- Given a Gate whose two branches end in model steps
- Then both steps are final positions, only the chosen branch runs
  `[existing packages/screamingface/src/screamingface/_surface/gate.py:87]`, and its result is
  the response.

**TC-S5 The final step answers with text.** `[implied]`
- Given the final step returns no tool call
- Then the response has `content` and `finish_reason: "stop"`.

**TC-S6 Several tool calls in one answer.** `[implied]`
- Then all calls pass through in the order of the provider.

### 4.2 Error paths

| # | Given (request with tools) | Then | Source |
|---|---|---|---|
| TC-S7 | the recipe ends in a deterministic reducer | 400 `final_step_not_model`; the message tells the user to add a final model step | [stated ans:Q9] |
| TC-S8 | a Gate has one branch that ends in a reducer | 400 `final_step_not_model` | [implied] |
| TC-S9 | the check cannot classify a final form | 400 `recipe_not_supported` | [proposed] |
| TC-S10 | the model of a final step does not list `tools` in `supported_parameters` `[existing G/core/model_capabilities.py:76]` | 400 `model_does_not_support_tools` with the model id | [proposed] |
| TC-S11 | a final step sets `web_search=true` and its route uses the Engine web tools | 400 `recipe_not_supported`. A final step with no `web_search` parameter is not refused; it does not search on such a route (§3.2) | [proposed] |
| TC-S12 | a tool has no name, a name twice, or a type that is not `function` | 400 `invalid_request` with `param` | [proposed] |
| TC-S22 | the recipe is an `sf.Cascade` or ends in a step Gate (§3.1) | 400 `final_step_not_model`; the message gives the `>> model` hint | [stated ans:Q9] |
| TC-S23 | the recipe names the route prefix `/ensemble/chat/v1/` at any depth (with or without tools) | 400 `recipe_not_supported` | [proposed — review 1] |

### 4.3 Derived scenarios

**TC-S13 `tools: []` is no tools.** `[proposed — gap §per-flow/boundary]` M×H
- Then the request follows [chat-completion](chat-completion.md), and no route changes.

**TC-S14 Tool history with no tools.** `[proposed — gap §per-flow/alternative]` M×M
- Given messages with tool calls and results, and no `tools` field
- Then each step, the final step included, gets the text view on the existing endpoint.

**TC-S15 A Gate branch is an outcome.** `[implied]` M×M
- Given the chosen branch is `abstain` or `fail`
- Then the response follows the abstain and fail rules ([chat-completion](chat-completion.md)
  CC-S9, CC-S22). No final step ran.

**TC-S16 Two final steps ran.** `[proposed — gap §per-flow/state]` H×L
- Given the collector holds results from two final steps
- Then the run fails with `final_step_ambiguous` and the response is 502. The Engine never picks.

**TC-S17 Tool calls cut by the output limit.** `[proposed — gap §per-flow/boundary]` M×M
- Given the final step returns `finish_reason: "length"` or `"stop"` with tool calls
- Then the response passes both on with no change. The client decides.
- When the provider gives no finish reason and tool calls exist, the value is `tool_calls`
  ([erd](../erd.md) §2.4).

**TC-S18 `tool_choice` and sampling fields.** `[stated ans:Q14]`
- Given `tool_choice`, `parallel_tool_calls`, `max_tokens` or `temperature` in the request
- Then the final step request does not contain them.

**TC-S19 The provider refuses the tool request.** `[implied — gap §per-element/external]` M×M
- Given the gateway answers 400 for the final step
- Then the run fails with the gateway failure code and the response is 502 with that code.

**TC-S20 Content in tools and tool results is data.** `[proposed — gap §security]` H×M
- The Engine never runs a tool and never reads tool content as an instruction. It puts the
  content in messages only.

**TC-S24 The final step honours the cache policy and retries.** `[proposed — review 1]` H×M
- Given `Cache-Control: no-store` on the request
- Then the final step request carries the cache opt-out, as each other step does
- And a 429 from the gateway on the final step is retried by the same rule as other Candidate
  calls `[existing E/world/connector.py:1293]`
- And a cache hit on the final step is reported as a cache hit, not as fresh tokens.

**TC-S25 The final step is refused by the provider.** `[implied]` M×M
- Then the result has `status: refused` ([chat-completion](chat-completion.md) CC-S25).

**TC-S21 The final step and E4 records.** `[implied]` H×M
- Given a recipe with a budget or a later attribution step
- Then the operation-call record of the final step has the binding, the output, the finish reason
  and the accounting, and attribution names it as the final operation.

## 5. Non-functional requirements

- **Cost.** Each turn runs the full ensemble on the full conversation. The tool list is sent to
  each non-final step as text. The docs state this `[proposed]`.
- **Determinism.** The text view and the native messages are pure functions of CHAT_INPUT and the
  step request `[proposed]`.
- **Observability.** The run log names the final binding and the count of tool calls, never
  their content `[proposed]`.
- **Provider prompt caching.** No special handling in this version `[proposed]`.

## 6. Out of scope

- A forced `tool_choice` `[stated ans:Q14]`.
- Tool calls from a deterministic reducer, for example a vote over tool calls `[stated ans:Q9]`.
- The Engine as the runner of client tools `[stated ans:Q6]`.
- The return of model reasoning text to the client.
- A change to the envelope schemas or to `connector.py` beyond the transport move `[stated ans:Q6]`.

## 7. Open questions

None.

## 8. TDD plan (RED → GREEN → REFACTOR)

Order: core-out. The recipe check and the two views are pure and come first. Then the endpoint,
then the full run.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| TC-1 | `final_positions_of_model_fusion_pipeline_gate_cascade_are_found` | unit | [stated ans:Q8] | H×H | table test over `surface_parity.json` and `gate_contract/*.url4`; a Cascade gives reducer positions |
| TC-2 | `reducer_final_with_tools_is_refused` | unit | [stated ans:Q9] | H×H | check returns `final_step_not_model` |
| TC-3 | `gate_with_one_reducer_branch_with_tools_is_refused` | unit | [implied] | H×M | recursion over branches |
| TC-4 | `unclassified_final_form_with_tools_is_refused` | unit | [proposed] | H×M | fail closed default |
| TC-5 | `text_view_is_valid_v1_or_v2_envelope_for_any_tool_history` | unit (property) | [proposed] | H×M | hypothesis: `parse_candidate_input` accepts every output |
| TC-6 | `text_view_is_deterministic` | unit (property) | [proposed] | M×M | same input, same bytes |
| TC-7 | `text_view_without_tool_history_equals_plain_envelope` | unit | [implied] | H×M | no rendering when nothing to render |
| TC-8 | `native_messages_keep_client_messages_unchanged_between_intent_and_context` | unit | [proposed] | H×M | §3.5 layout |
| TC-9 | `final_endpoint_sends_one_request_with_client_tools_and_no_tool_choice` | unit | [stated ans:Q14] | H×H | stub gateway, inspect body |
| TC-10 | `final_endpoint_never_executes_a_tool_call` | unit | [stated ans:Q6] | H×M | one round trip; no dispatch |
| TC-11 | `final_endpoint_records_outcome_operation_and_usage` | unit | [implied] | H×M | recorders + transport report |
| TC-12 | `chat_routes_are_not_direct_mounts_and_have_gateway_state` | unit | [existing E/world/factory.py:252] | H×L | own installer after the snapshot, with the gateway world |
| TC-13 | `repoint_changes_only_final_model_sources` | unit | [proposed] | H×M | AST transform; `render` round trip |
| TC-14 | `fusion_with_tools_members_get_text_view_and_synthesizer_gets_tools` | integration | [stated ans:Q8] | H×H | stub gateway records each body |
| TC-15 | `gate_with_tools_only_chosen_branch_calls_final_endpoint` | integration | [stated ans:Q8] | H×M | zero calls on the other branch |
| TC-16 | `tool_calls_reach_response_unchanged_with_finish_reason_tool_calls` | integration | [stated ans:Q5] | H×M | collector → CHAT_RESULT → translate |
| TC-17 | `two_final_results_fail_with_final_step_ambiguous` | unit | [proposed] | H×L | collector guard |
| TC-18 | `model_without_tool_support_is_400_before_the_run` | unit | [proposed] | M×M | catalogue check at the route |
| TC-19 | `empty_tools_list_follows_no_tools_path` | unit | [proposed] | M×H | normalise at validation |
| TC-20 | `attribution_names_final_step_with_its_output_and_accounting` | integration | [implied] | H×M | the operation record of the final step is the attributed final operation |
| TC-21 | `agent_two_turn_tool_loop_on_local_stack` | E2E | [stated ans:Q1] | H×M | OpenAI SDK, cached calls, one tool round trip |
| TC-22 | `final_step_with_explicit_web_search_on_engine_tool_route_is_refused_and_default_is_not` | unit | [proposed] | H×M | route config + `web_search` parameter; the default case runs with client tools only |
| TC-23 | `malformed_tools_are_400_with_param` | unit | [proposed] | M×H | wire model rules |
| TC-24 | `tool_history_without_tools_uses_text_view_for_final_step` | integration | [proposed] | M×M | no re-point when `tools` is absent |
| TC-25 | `length_finish_with_tool_calls_passes_through` | unit | [proposed] | M×M | no repair, no drop |
| TC-26 | `gateway_400_on_final_step_is_502_with_code` | integration | [implied] | M×M | transport error → failure table |
| TC-27 | `final_step_honours_no_store_and_reports_cache_hit` | integration | [proposed] | H×M | shared round trip with the run cache policy |
| TC-28 | `final_step_retries_429_like_other_candidate_calls` | integration | [proposed] | H×M | shared round trip inside the answering scope |
| TC-29 | `recipe_naming_final_route_prefix_is_refused_at_any_depth` | unit | [proposed] | H×M | recipe check walks Gate bodies |
| TC-30 | `final_endpoint_without_bound_chat_turn_fails_closed` | unit | [proposed] | H×M | permanent error, no gateway call |
| TC-31 | `repoint_inside_nested_gate_bodies_round_trips` | unit | [proposed] | H×H | `d1_keyword_router.url4`: a Gate inside a Gate body |
| TC-32 | `member_and_synthesizer_on_one_route_only_synthesizer_is_repointed` | unit | [proposed] | H×H | select by binding name |
| TC-33 | `cascade_with_tools_is_refused_and_cascade_then_model_is_allowed` | unit | [stated ans:Q9] | H×M | §3.1 effect |
| TC-34 | `text_view_joins_text_part_lists_and_drops_empty_parts` | unit (property) | [proposed] | H×H | TC-5 generator includes part lists on each role |
| TC-35 | `refused_final_step_gives_refused_result` | integration | [implied] | M×M | error form of the existing endpoint |
| TC-36 | `empty_step_context_adds_no_last_user_message` | unit | [proposed] | M×M | `cascade >> model` after an abstain |

Scenario without its own test: TC-S15 (a Gate branch is an outcome). CR-10, CC-13 and CC-14 cover
the abstain and fail rules.

# PRD: streamed response (`stream: true`, buffered)

**Source:** ans:Q1, ans:Q4 · **Priority:** P1 (agents always stream)
**Lifecycle:** planned · **Owner:** unassigned

## 1. Summary and user story

As an agent or SDK that sets `stream: true`, I want a valid OpenAI event stream, so that my
client works. The owner accepted a buffered stream: the full answer comes in one piece after the
ensemble ends `[stated ans:Q4]`.

## 2. Background and constraints

- The run publishes whole results, not token deltas
  `[existing E/schemas/protocol_schemas.py:37]`.
- A long ensemble gives no bytes for a long time. Clients and proxies close idle connections.
  Keep-alive lines prevent this `[proposed]`.
- The WebSocket heartbeat interval is 15 s `[existing E/config.py:218]`.
- The base rules are in [chat-completion](chat-completion.md) and [tool-calls](tool-calls.md).
  This PRD owns the framing only.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

**ST-S1 A text answer.** `[stated ans:Q4]`
- Given a valid request with `stream: true`
- Then the Engine answers 200 with `Content-Type: text/event-stream` before the run ends
- And it sends the comment line `: keep-alive` each 15 s while it waits
- And then it sends, in order: one chunk with `delta: {role: "assistant", content: <full text>}`,
  one chunk with an empty `delta` and the `finish_reason`, and the line `data: [DONE]`
- And each chunk has the same `id`, `object: "chat.completion.chunk"`, `created` and `model`.

**ST-S2 Tool calls.** `[stated ans:Q5]`
- Given a result with tool calls
- Then the first chunk has `delta.role` and `delta.content` (when not empty)
- And one chunk has `delta.tool_calls`, where each item has `index`, `id`, `type: "function"`,
  `function.name` and the full `function.arguments` string
- And the last chunk has `finish_reason: "tool_calls"`.

**ST-S3 Usage in the stream.** `[proposed — client contract]`
- Given `stream_options.include_usage: true`
- Then one more chunk comes before `[DONE]`, with `choices: []` and the `usage` object
  `[stated ans:Q13]` and the `screamingface` object.

**ST-S4 Abstain.** `[stated ans:Q10]`
- Then the stream has an empty content chunk, `finish_reason: "stop"`, and the `screamingface`
  object with `status: "abstained"` in the last chunk before `[DONE]`.

### 3.2 Error paths

**ST-S5 An error before the stream starts.** `[implied]`
- Given a request that fails validation, identity, size or admission
- Then the answer is the normal JSON error with its status. No stream starts.

**ST-S6 An error after the stream starts.** `[proposed — gap §per-flow/failure]` H×M
- Given the run fails after the 200 status
- Then the Engine sends one line `data: {"error": {"message", "type", "code"}}` and closes the
  stream with no `[DONE]`.

**ST-S7 The time limit.** `[proposed]` H×M
- Given the run does not end in `chat_max_wait_s`
- Then the Engine stops the run and sends the error event with `code: "timeout"`.

### 3.3 Derived scenarios

**ST-S8 The client disconnects.** `[implied — gap §per-flow/cancel]` H×H
- Then the Engine stops the run and deletes the input blob. No model call continues.
- On a disconnect, the server cancels the scope around the body generator, and an `await` in its
  `finally` block is cancelled again. Thus the stop and the delete run in a shielded block, or in
  a task that the generator does not own `[proposed — review 1]`.

**ST-S12 The App shuts down during a stream.** `[proposed — review 1]` H×M
- Then the stream gets the error event with `code: "server_restarting"` when the drain event is
  set ([chat-completion](chat-completion.md) CC-S37).

**ST-S9 Proxy buffering.** `[proposed — gap §per-connection/sync]` M×M
- The response has `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and each write is
  flushed.

**ST-S10 Keep-alive stops at the result.** `[proposed]` L×M
- No comment line comes after the first data chunk.

**ST-S11 A refusal.** `[implied]` M×L
- Then one chunk has `delta.refusal` and the last chunk has `finish_reason: "content_filter"`.

## 4. Non-functional requirements

- **First byte.** The status line and headers leave ≤ 1 s after the run is scheduled
  `[proposed]`.
- **Keep-alive interval.** `chat_keepalive_s` = 15 (a setting) `[proposed]`. It is below the idle
  limits of the known clients (5 minutes or more) and of common proxies (about 100 s).
- **Advice in docs.** For an ensemble that can run longer than 60 s, use `stream: true`
  `[proposed]`.

## 5. Out of scope

- Token-by-token streaming `[stated ans:Q4]`.
- Progress events of the ensemble in the stream.

## 6. Open questions

None.

## 7. TDD plan (RED → GREEN → REFACTOR)

Order: the framing functions are pure and come first, then the route.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| ST-1 | `text_result_frames_as_role_content_chunk_finish_chunk_done` | unit | [stated ans:Q4] | H×H | pure `frames(result)` in `E/chat/sse.py` |
| ST-2 | `tool_calls_frame_with_index_id_name_and_full_arguments` | unit | [stated ans:Q5] | H×H | one fragment for each call |
| ST-3 | `include_usage_adds_usage_chunk_with_empty_choices` | unit | [proposed] | H×M | optional last chunk |
| ST-4 | `openai_sdk_stream_parser_accepts_every_frame_sequence` | unit | [stated ans:Q1] | H×M | parse with the `openai` SDK types in tests |
| ST-5 | `stream_sends_keep_alive_comments_until_result` | unit | [proposed] | H×M | fake clock |
| ST-6 | `validation_error_with_stream_true_is_json_error_not_stream` | unit | [implied] | M×M | validate before the response starts |
| ST-7 | `failure_after_start_sends_error_event_and_no_done` | unit | [proposed] | H×M | error frame |
| ST-8 | `real_asgi_disconnect_during_stream_stops_run_and_deletes_blob` | integration | [implied] | H×H | send `http.disconnect` through the streaming response; a fake disconnect flag cannot fail for this reason |
| ST-9 | `response_headers_disable_proxy_buffering` | unit | [proposed] | M×M | fixed header set |
| ST-10 | `agent_stream_on_local_stack_with_tool_call` | E2E | [stated ans:Q1] | H×M | same lane as TC-21 with `stream: true`; built in unit U6, because it needs tools |
| ST-11 | `no_keep_alive_after_first_data_chunk` | unit | [proposed] | L×M | stop the timer at the result |
| ST-12 | `refusal_frames_with_delta_refusal_and_content_filter` | unit | [implied] | M×L | frames(result) |
| ST-13 | `abstained_result_frames_with_status_in_last_chunk` | unit | [stated ans:Q10] | M×M | frames(result) |

# OpenAI-compatible chat endpoint: contracts

One section for each connection. Path prefixes: `E/` =
`apps/screamingface-engine/src/screamingface_engine/`, `G/` = `apps/aigateway/src/aigateway/`.
Test numbers refer to the TDD plans of the PRDs.

## C1 Chat request — client → Engine App, sync, HTTP

- Shape (request): `POST /v1/chat/completions`, `Content-Type: application/json`.

```json
{
  "model": "<Candidate URL4 | gateway model id>",
  "messages": [{"role": "system|developer|user|assistant|tool", "content": "… | [parts]",
                "tool_calls": [], "tool_call_id": "…"}],
  "tools": [{"type": "function", "function": {"name": "…", "description": "…", "parameters": {}}}],
  "stream": false,
  "stream_options": {"include_usage": false}
}
```

- Fields with an effect: `model`, `messages`, `tools`, `stream`,
  `stream_options.include_usage` `[stated ans:Q14]` `[proposed]`.
- Refused fields: `n` > 1, `logprobs: true`, audio modalities `[proposed]`.
- Each other field is accepted and ignored `[stated ans:Q14]`.
- Headers with an effect: `Cache-Control: no-store` `[stated ans:Q15]`; hosted identity comes
  from the edge after `Cf-Access-Token` `[stated ans:Q2]`. `Authorization` has no effect.
- Shape (response, 200):

```json
{
  "id": "chatcmpl-<id>", "object": "chat.completion", "created": 0, "model": "<request value>",
  "choices": [{"index": 0, "finish_reason": "stop|tool_calls|length|content_filter",
               "message": {"role": "assistant", "content": "…", "tool_calls": [], "refusal": null}}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "screamingface": {"status": "answered|abstained|refused", "abstain_reason": null,
                    "cost_usd": "0.0123", "trace_id": "…",
                    "final_step": {"binding": "synthesis_1", "model": "…",
                                   "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}}
}
```

- Shape (error): `{"error": {"message": "…", "type": "…", "param": null, "code": "…"}}` with the
  status table of [chat-completion](prd/chat-completion.md) §3.2 `[proposed]`.
- Policies: the media type of `Content-Type` must be `application/json` (else 415); the body is
  read with a running cap of 8,000,000 bytes; at most 4 large bodies are parsed at one time;
  time limit `chat_max_wait_s` 600 s; no server retry; no idempotency key. The status, the body
  code, `Retry-After` and `x-should-retry` follow the terminal table of
  [chat-completion](prd/chat-completion.md) §3.2 `[proposed]` `[proposed — review 2]`.
- `usage` and `screamingface.cost_usd` come from the root cost-usage frame of the run (C9), not
  from the run result. `cost_usd` is null for an unpriced run. A cached call counts 0 tokens
  `[proposed — review 2]` `[stated ans:Q26]`.
- Failure behavior, client side: a client retry starts a new run. Server side: on each exit
  without a result, the App stops the run and deletes the input blob.
- Contract tests: CC-1, CC-3, CC-4, CC-12, CC-13, CC-14, CC-16, CC-17, CC-21, CC-22.

## C2 Streamed response — Engine App → client, sync, SSE

- Shape: `text/event-stream`; comment lines `: keep-alive`; `data:` lines with
  `chat.completion.chunk` objects; last line `data: [DONE]`
  ([streaming](prd/streaming.md) §3.1) `[stated ans:Q4]`.
- Policies: keep-alive each `chat_keepalive_s` (15 s); flush after each write; headers
  `Cache-Control: no-cache` and `X-Accel-Buffering: no` `[proposed]`.
- Failure behavior: before the first byte, a JSON error (C1). After it, one error event and a
  close with no `[DONE]` `[proposed]`.
- Contract tests: ST-1, ST-2, ST-3, ST-4, ST-7, ST-10.

## C3 Model list — client → Engine App, sync, HTTP (existing, unchanged)

- Shape: `GET /v1/models` returns `{"object": "list", "data": [{"id", "object": "model",
  "owned_by", …}]}` `[existing E/rest/catalog.py:115]` `[existing G/core/model_capabilities.py:72]`.
- Rule: each `id` is a valid `model` value for C1 `[stated ans:Q16]`.
- Contract tests: CC-23, CC-5.

## C4 Input write — Engine App → run blob store, data

- Shape: one CHAT_INPUT record ([erd](erd.md) §2.1), ingested into the **chat-input store**
  ([erd](erd.md) §1.1) under the scope `(tenant of the caller, topic of the request)` with
  `BlobStore.ingest` `[existing E/artifacts/blobs.py:94]`.
- Policies: write before schedule; delete at request end with the new `delete` operation (new
  on the objects protocol and on each backend); the store sweep is the safety net `[proposed]`.
- Failure behavior: store absent or full → 503 `chat_unavailable`, no run. Schedule failure after
  the write → delete, then the error.
- The chat-input store has its own policy: one media type, a schema check in place of the
  signature check. The public `PUT /blob/…` route keeps the attachment store and refuses the
  chat media type `[proposed — review 1]`.
- Contract tests: CC-3, CC-11, CC-19, CR-13, CR-19, CR-20, CR-23.

## C5 Schedule — Engine App → run queue, async, JetStream

- Shape: `JobRunner.schedule(topic, url4, deadline_s, …, shape="chat", chat_input=<blob ref>)`.
  The keyword `chat_input` is new on the port `[existing E/ports.py:80]`, on `_schedule`
  `[existing E/rest/routes.py:353]`, on the queue codec `[existing E/runner_queue.py:225]`, on
  the in-process adapter `[existing E/adapters/inprocess.py:282]` and on each test fake
  `[proposed — review 1]`. The env mapping gets `URL4_CLOUD_RUN_SHAPE=chat` and
  `URL4_CLOUD_CHAT_INPUT` ([erd](erd.md) §2.2). The `url4` value is the Candidate URL4 as the
  client sent it, or the one-model recipe.
- Policies: one message for each request, deduplicated by topic
  `[existing E/runner_queue.py:590]`. Deadline = time limit + 5 s `[proposed]`, the rule of a
  mount call `[existing E/rest/mounts.py:372]`. Per-caller in-flight cap 24
  `[existing E/runner_queue.py:127]`. Model admission as for each run
  `[existing E/rest/routes.py:353]`.
- Failure behavior: admission refused → 429; queue not available → 503. A message that an old
  worker reads fails with an unknown-shape error `[existing E/job_env.py:235]`.
- Contract tests: CC-10, CC-17, CR-3, CR-5.

## C6 Input read — chat handler → run blob store, data

- Shape: `ScopedBlobReader.read(digest)` with the scope from the run env
  `[existing E/artifacts/blobs.py:240]`.
- Failure behavior: not found or digest mismatch → the run fails with
  `chat_input_unavailable`; unknown schema → `chat_input_invalid`. No model call happens.
- Contract tests: CR-6, CR-13, CR-2.

## C7 Recipe evaluation — chat handler → existing Engine world, dependency

- Rule: the executor dispatches the internal route `/ensemble/chat/v1/turn` with
  `dispatch_direct` and the bridge as observer, as it dispatches a mount
  `[existing E/runner/executor.py:1192]`. Without an observer, the run gives no cost or usage
  frames `[proposed — review 1]`. The chat shape does not use the mount check of a direct run;
  it accepts only this one internal route.
- Shape of the target: context = the blob ref, intent = the Candidate URL4, built with the url4
  builders ([erd](erd.md) §2.2) `[proposed — review 2]`.
- Rule: the executor binds a chat-run marker for the `chat` shape. The turn handler and the
  final-step endpoint fail closed without it `[proposed — review 2]`.
- Rule: the handler binds no retrieval policy and does not change the parameters in the recipe
  text. Each step follows its model route for web search ([chat-run](prd/chat-run.md) CR-S16)
  `[stated ans:Q30]`.
- Rule: the App filters its mount table by the direct-mount set, so no internal route is a public
  mount ([chat-run](prd/chat-run.md) CR-S19) `[proposed — review 3]`.
- Rule: the inner evaluation runs at the concurrency of the node
  ([chat-run](prd/chat-run.md) CR-S20).
- Rule: the handler calls `evaluate_candidate_recipe(node, expression, input_text, …)`
  `[existing E/benchmarks/invocation.py:48]` inside `candidate_invocation_scope()`
  `[existing E/candidate_scope.py:35]`. It does not change that function.
- Rule: with no tools, the expression is unchanged. With tools, only the final model sources are
  pointed to C8 ([tool-calls](prd/tool-calls.md) §3.2).
- Rule: the handler reads the returned Candidate Invocation envelope with
  `decode_candidate_invocation_record` `[existing E/benchmarks/contract.py:852]`.
- Enforcement: CR-7 compares request bytes with the Candidate route. The layering gate keeps
  `world/chat_turn.py` out of the control plane (CR-15).

## C8 Final step — final-step endpoint → AI gateway, sync, HTTP

- Shape: `POST /v1/chat/completions` on the gateway `[existing E/world/connector.py:141]` with
  `{"model", "messages", "tools", <recipe parameters of the step>, <cache policy field>}`. No
  `tool_choice`, no `stream`, no client sampling field `[stated ans:Q14]`.
- Policies: the endpoint calls the shared round-trip function `[stated ans:Q11]`. It gives the
  identity and time-out headers, the cache policy and read-back, the transport retry, the
  Candidate retry on 429 and 5xx, the deadline, the heartbeat and the cost reports
  `[proposed — review 1]`. Exactly one logical request; no tool loop.
- Response: the endpoint reads `content`, `tool_calls`, `finish_reason` and `refusal` with
  `parse_choice` `[existing E/world/model_response.py:25]` and the usage block.
- Failure behavior: gateway 4xx or 5xx → the Engine error code of the transport; the run fails;
  the client gets 502 with that code. A refusal follows the refusal path.
- The response is untrusted input: the endpoint validates the shape of each tool call (id, name,
  arguments string) and passes the values on as data `[proposed]`.
- Contract tests: TC-9, TC-10, TC-11, TC-27, TC-28, TC-30, GT-5.

## C9 Result — chat run → Engine App, async, events stream

- Shape: one cost-usage frame with `scope: self` for the span of the turn handler and one root
  frame with `scope: subtree` `[existing packages/url4/src/url4/streaming/protocol/signals.py:150]`
  `[existing packages/url4/src/url4/streaming/lifecycle.py:275]`, then one result frame with a
  CHAT_RESULT body ([erd](erd.md) §2.4) and its media type, then the terminal frame
  `[existing E/rest/routes.py:504]`.
- The App reads `usage` and `cost_usd` from the root frame, with its own scan of the topic. It
  selects the frame with `scope == "subtree"`. The mapping `[proposed — review 3]`:
  `prompt_tokens` = the input token count of the frame (it includes cache reads of the
  provider); `completion_tokens` = the output token count (it includes reasoning tokens);
  `total_tokens` = their sum; `cost_usd` = the total of the frame, or null when its pricing
  version is `unpriced` `[existing E/runner/executor.py:722]`.
- A result above the inline cap is in the artifact store. The App reads it through the artifact
  reader port, not through the HTTP response helper `[proposed — review 1]`.
- Policies: the App reads from the start of the topic subject, bounded by the time limit
  `[existing E/rest/routes.py:630]`. The run deletes its subject 5 s after the terminal frame
  `[proposed]`, the grace of a direct run `[existing E/job_env.py:222]`.
- Failure behavior: each terminal state has a row in the terminal table of
  [chat-completion](prd/chat-completion.md) §3.2, also "succeeded with no result frame" and
  "result with the wrong media type". No terminal frame in time → stop, then 504.
- Contract tests: CR-6, CR-9, CR-11, CR-16, CR-18, CC-12, CC-18.

## C10 Shared round trip — existing endpoint and final-step endpoint → `world/gateway_transport`, dependency

- Rule: one definition of the full round trip (all the code below the tool loop)
  `[stated ans:Q11]` `[proposed — review 1]`. `connector.py` and `world/chat_final.py` import it.
- Rule: `connector.py` imports the module, not the names, so a stale test patch fails (GT-8).
- Enforcement: GT-1 to GT-4 and GT-7 pin today's bytes; GT-6 fails if `connector.py` keeps a copy.

## C11 Layering — dependency

| Module | Half | May import |
|---|---|---|
| `E/rest/chat_completions.py` | control plane | `E/chat/`, rest helpers, ports |
| `E/chat/` (wire models, input, result, recipe check, views, SSE frames) | shared leaf | `url4` core, pydantic; no FastAPI, no `runner`, no `rest` |
| `E/world/chat_turn.py` (the handler, an internal endpoint) | world | `E/chat/`, world modules, `benchmarks.invocation`; neither half |
| `E/world/chat_final.py`, `E/world/gateway_transport.py` | world | `E/chat/`, world modules; neither half |

- Enforcement: `.claude/scripts/check_layering.py` lists the new modules (CR-15, GT-5)
  `[existing .claude/scripts/check_layering.py:19]`.

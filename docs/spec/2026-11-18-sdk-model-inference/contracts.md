# SDK model inference — contracts

One section for each connection of the inventory. Tags as in `00-overview.md` §2.

## C1 — caller → `sf.ModelInference` (Python API)

### C1.1 Constructor

```python
class ModelInference[ClientT: (Client, AsyncClient)]:
    @overload
    def __init__(self: "ModelInference[Client]", model: Recipe | Url4 | str, *, client: Client | None = None) -> None: ...
    @overload
    def __init__(self: "ModelInference[AsyncClient]", model: Recipe | Url4 | str, *, client: AsyncClient) -> None: ...
    chat: Chat[ClientT]
    def endpoint(self): ...   # InferenceEndpoint, or an awaitable of it with an AsyncClient
```

- `model` `[proposed P1]`:
  - a `Recipe` (`sf.Model`, a Fusion, a Pipeline, a Gate, a Cascade, ...) `[stated ans:Q1]`;
  - a `sf.Url4`, or a string that starts with `(` after white space: URL4 text. Candidate URL4
    text is sent with no change. From an evaluation URL4 the SDK takes the `candidate` source
    `[proposed P14]`; an evaluation URL4 with no such source gives `PlanningError`;
  - each other string: a gateway model id, sent with no change.
  - Each other type: `TypeError`. An empty or blank string: `ValueError`.
- `client`: with no value, the object uses the default client of the SDK (sync). It takes
  `default_client()` at each call, as `sf.classify` does, so `sf.configure()` and `sf.close()`
  work as for each other module call `[existing S/_default_client.py:173]`. An `AsyncClient`
  selects the async mode `[stated ans:Q7]`. Each other type: `TypeError`.
- The constructor sends no request `[proposed P2]`.
  - A recipe that needs no operator catalogue is compiled in the constructor and the text is
    kept (it cannot change).
  - A recipe with a reducer: the constructor does the shape checks that need no catalogue; the
    text is compiled at each call with the catalogue that the client keeps
    `[existing S/_engine/catalog.py:402]`. So the object has no state that a call changes.
- Recipe errors `[proposed P17]`: a corrective loop (`CorrectiveLoop`, `SelfCorrective`, also
  inside `WithBudget`) gives `PlanningError`, code `recipe_not_supported`, from the SDK. Each
  other compiler error keeps its type of today (`ValueError` or `PlanningError`), as in
  `sf.evaluate` `[existing S/_evaluation/candidate.py:808]`.
- The object keeps no conversation. More than one thread or task can use it at one time. An
  `AsyncClient` belongs to one event loop `[implied]`.

### C1.2 `chat.complete`

```python
def complete(
    self,
    prompt: str | None = None,
    *,
    messages: Sequence[Mapping[str, Any]] | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    stream: bool = False,
    stream_options: Mapping[str, Any] | None = None,
    use_cache: bool = True,
    max_retries: int = 0,
    timeout: float | None = None,
    **other: Any,
): ...
```

| Client | `stream` | Result |
|---|---|---|
| `Client` | literal `False` (default) | `ChatCompletion` |
| `Client` | literal `True` | `ChatStream` (iterable of `ChatCompletionChunk`) |
| `Client` | a `bool` that is not a literal | `ChatCompletion \| ChatStream` |
| `AsyncClient` | literal `False` (default) | awaitable of `ChatCompletion` |
| `AsyncClient` | literal `True` | awaitable of `AsyncChatStream` |
| `AsyncClient` | a `bool` that is not a literal | awaitable of `ChatCompletion \| AsyncChatStream` |

The rows are typed overloads on the client type and on the value of `stream`
`[stated ans:Q7]` `[proposed]`. At run time there is one method; with an `AsyncClient` it
returns a coroutine.

Rules:

- `prompt` is the same as `messages=[{"role": "user", "content": prompt}]` `[stated ans:Q1]`.
- Exactly one of `prompt` and `messages`; if not, `TypeError` `[proposed P3]`. `messages` must
  not be empty (`ValueError`).
- The SDK sends `messages` and `tools` with no change. The Engine is the authority for their
  shape, and for pictures and files `[existing E/chat/wire.py:115]`.
- `stream_options` has an effect only with `stream=True` `[existing E/rest/chat_body.py:243]`.
- `use_cache=False` sends `Cache-Control: no-store` `[existing E/cache_intent.py:78]`. The default
  uses the shared cache (owner decision of PR #1937).
- `max_retries`: an integer of 0 or more; the default is 0 `[stated ans:Q4]`. See C2.5.
- `timeout`: seconds for the full call, more than 0; `None` means that only the limit of the Engine
  applies `[proposed P11]`.
- `**other` `[stated ans:Q3]` `[proposed P4]`:
  - A name of the fixed list of known OpenAI chat parameters (`temperature`, `max_tokens`,
    `max_completion_tokens`, `top_p`, `stop`, `seed`, `response_format`, `tool_choice`,
    `parallel_tool_calls`, `presence_penalty`, `frequency_penalty`, `logit_bias`, `top_logprobs`,
    `reasoning_effort`, `user`, `metadata`, `store`, `service_tier`, and `n=1`,
    `logprobs=False`) is accepted, is not sent, and gives an `IgnoredParameterWarning` that
    names the parameter and points to `sf.Model(params=...)`. The SDK issues the warning in each
    call; Python shows a repeated warning one time for each code location by default.
  - `n` above 1, `logprobs=True`, `audio` with a value, `modalities` with `"audio"`:
    `PlanningError`, code `unsupported_parameter`, because the Engine refuses them
    `[existing E/rest/chat_body.py:256]`.
  - Each other name: `TypeError` (an unexpected keyword).
- An argument error is raised by the call itself in both modes. A network or Engine error is
  raised by the call (sync) or by the `await` (async) `[proposed]`.
- A client that is closed gives the `RuntimeError` of the client before a request
  `[existing S/client.py:567]`.

### C1.3 Reply types

Frozen dataclasses with slots `[proposed P5]` `[existing S/answer.py:83]`. The field names are
those of the OpenAI objects `[stated ans:Q2]`.

| Type | Fields |
|---|---|
| `ChatCompletion` | `id: str`, `object: str` (`"chat.completion"`), `created: int`, `model: str`, `choices: tuple[ChatChoice, ...]` (one item), `usage: ChatUsage`, `screamingface: InferenceInfo` |
| `ChatChoice` | `index: int`, `message: ChatMessage`, `finish_reason: str` |
| `ChatMessage` | `role: str`, `content: str \| None`, `tool_calls: tuple[ChatToolCall, ...] \| None`, `refusal: str \| None` |
| `ChatToolCall` | `id: str`, `type: str`, `function: ChatFunctionCall` |
| `ChatFunctionCall` | `name: str`, `arguments: str` (JSON text, as in OpenAI) |
| `ChatUsage` | `prompt_tokens: int`, `completion_tokens: int`, `total_tokens: int` |
| `InferenceInfo` | `status: str` (`answered`, `abstained`, `refused`), `abstain_reason: str \| None`, `cost_usd: Decimal \| None`, `trace_id: str \| None`, `final_step: FinalStep \| None` |
| `FinalStep` | `binding: str`, `model: str`, `usage: ChatUsage \| None` |
| `ChatCompletionChunk` | `id`, `object` (`"chat.completion.chunk"`), `created`, `model`, `choices: tuple[ChatChunkChoice, ...]` (can be empty), `usage: ChatUsage \| None`, `screamingface: InferenceInfo \| None` |
| `ChatChunkChoice` | `index: int`, `delta: ChatDelta`, `finish_reason: str \| None` |
| `ChatDelta` | `role: str \| None`, `content: str \| None`, `tool_calls: tuple[ChatDeltaToolCall, ...] \| None`, `refusal: str \| None` |
| `ChatDeltaToolCall` | `index: int`, `id: str`, `type: str`, `function: ChatFunctionCall` (OpenAI loops that collect tool calls read `index`) `[existing E/chat/sse.py:111]` |

Short forms `[proposed P5]`: `ChatCompletion.text` (the content of the first choice, or `None`),
`.tool_calls`, `.cost_usd`, `.trace_id`, `.to_dict()` (a JSON-ready dict with the OpenAI key
names; `cost_usd` as a decimal string). `ChatCompletionChunk.text` (the delta content, or `""`
when the chunk has no choice or no content).

Notes:

- A reply with the status `abstained` or `refused` is a normal reply, not an error
  `[existing E/rest/chat_answer.py:172]`.
- `cost_usd` is `None` when one call of the run has no price. `usage` is 0/0/0 when the run gave
  no cost record `[existing E/rest/chat_answer.py:190]`.
- `model` is the text that was sent. For a recipe it is the full Candidate URL4 (about 1,000
  characters for a small Fusion) `[existing E/rest/chat_answer.py:183]`.
- A reply with tool calls and no text has `content` `None` `[proposed P13]`.

### C1.4 Stream objects

`ChatStream` `[proposed P6]`: `__iter__` gives each `ChatCompletionChunk` in the order of the
Engine; `close()` releases the connection; it is a context manager; a stream that the caller
reads to the end closes itself. `AsyncChatStream` is the same with `__aiter__`, `aclose()` and
an async context manager. Keep-alive lines are not given to the caller. An error event raises
the mapped error from the iteration (C2.4).

The stream is buffered `[existing E/chat/sse.py:3]`: the first chunk comes when the run has
ended, and then all chunks come at one time. It is not a token stream. The docs say this.

### C1.5 `endpoint()`

`InferenceEndpoint` (frozen dataclass) `[proposed P7]`: `base_url: str` (the Engine URL with
`/v1`), `model: str` (the Candidate URL4 text or the model id), `headers: Mapping[str, str]`
(the auth headers that the client sends now; empty for a local Engine). Its `repr` shows the
header names and hides each value. With an `AsyncClient` the method returns an awaitable.

On an `https` Engine the method calls the sign-in of the client first (`Client.login()`, which
returns at once when a usable token exists), then reads the headers from the auth object of the
client `[existing S/client.py:204]` `[existing S/_access/base.py:23]`.

### C1.6 New public names

`ModelInference`, `ChatCompletion`, `ChatChoice`, `ChatMessage`, `ChatToolCall`,
`ChatFunctionCall`, `ChatUsage`, `ChatCompletionChunk`, `ChatChunkChoice`, `ChatDelta`,
`ChatDeltaToolCall`, `ChatStream`, `AsyncChatStream`, `InferenceInfo`, `FinalStep`,
`InferenceEndpoint`, `IgnoredParameterWarning`. Each goes into `__all__` and into the public
surface snapshot `[existing packages/screamingface/tests/test_public_surface.py]`.

## C2 — `ModelInference` → Engine: `POST /v1/chat/completions`

### C2.1 Request

- Method and path: `POST {engine_url}/v1/chat/completions` `[existing E/rest/chat_completions.py]`,
  through a new streamed POST seam of the client, next to `_engine_get`
  `[existing S/client.py:571]`.
- Headers: `Content-Type: application/json`; `Accept: text/event-stream`; a new `traceparent`
  for each call, from the trace helper of the SDK `[proposed P8]` `[existing S/_engine/trace.py]`;
  `Cache-Control: no-store` only with `use_cache=False`; the auth of the client
  (`Cf-Access-Token` on a hosted Engine) `[existing S/_access/auth.py:409]`. A local Engine needs
  no identity header `[existing E/runs/wiring.py:297]`.
- Body: `{"model", "messages", "tools"?, "stream": true, "stream_options": {"include_usage": true}}`
  `[stated ans:Q5]`. `tools` is sent only when the caller gave a list that is not empty.
  For a caller with `stream=True`, `stream_options` is the value of the caller (default: none),
  so the chunks are those that an OpenAI client gets `[proposed P6]`.
- The SDK does not send an ignored parameter `[stated ans:Q3]`.
- The time limits of this request replace the default of the HTTP client (30 s)
  `[existing S/client.py:95]`: connect 10 s; 60 s between bytes `[proposed P11]`.

### C2.2 Answer before the stream starts

The Engine answers with a plain HTTP error, with the OpenAI error envelope and the headers
`x-should-retry` and (some codes) `Retry-After`, for each failure before the run is scheduled
`[existing E/rest/chat_errors.py:90]`. The map is in C2.4.

### C2.3 The stream

Status 200, `text/event-stream`. Frames `[existing E/chat/sse.py]`:

1. `: keep-alive` comment lines while the run works (each 15 s by default). The SDK drops them.
2. First chunk: `delta` with `role` and `content` (or `refusal`). With tool calls and no text,
   the `delta` has no `content` key.
3. Tool-call chunk (only with tool calls): each call with its `index` and its full `arguments`.
4. Finish chunk: empty `delta`, `finish_reason`; with no usage chunk it has `screamingface`.
5. Usage chunk (only with `include_usage`): empty `choices`, `usage`, `screamingface`.
6. `data: [DONE]`.

An error after the start is one event `data: {"error": {...}}` and then the stream ends with no
`[DONE]`. The stream is buffered, so an error event always comes before the first chunk.

**Reply built by the SDK (caller with `stream=False`)** `[stated ans:Q5]`: `id`, `created` and
`model` from the chunks; `object` is `"chat.completion"`; `message.content` (a missing key is
`None`), `refusal` and `tool_calls` (without `index`) from the deltas; `finish_reason` from the
finish chunk; `usage` and `screamingface` from the usage chunk.

INVARIANT: for one run result, this reply is equal to the plain reply of the Engine in `choices`,
`usage` and `screamingface`. `id` and `created` are made for each answer and are not part of
the comparison `[proposed P13 — risk R4]`.

A stream that ends with no `[DONE]` and no error event, a line that is not JSON, or a chunk
with a wrong shape gives `ExecutionError` (code `invalid_response`) `[proposed]`.

### C2.4 Error map

The SDK error classes are those of today `[existing S/errors.py:13]`. The exemplar for the map
is the classify transport `[existing S/_engine/classification.py:248]`. Each error has `code`,
`status`, `permanent`, `trace_id` and, when the Engine gave one, `details["param"]` and
`details["retry_after"]`.

| Case | SDK error | `permanent` |
|---|---|---|
| the request was never sent (no connection, no pool place) | `EngineUnavailableError` | false |
| 404 or 405 with no OpenAI error envelope (an Engine with no chat route) | `EngineCapabilityError`, with a hint to upgrade the Engine | true |
| 401, 403 from the Engine (after the sign-in of the client) | `AuthenticationError` | true |
| 400, 404 with an envelope, 413, 415 | `PlanningError` (the code of the Engine) | true |
| 408, 422, 429, each 5xx | `ExecutionError` (the code of the Engine) | `x-should-retry` is not `true` |
| stream error event | `ExecutionError` (the code of the event) | `should_retry` is not `true`; an event with no such key (an Engine before this change) is permanent |
| the connection breaks, or 60 s pass with no byte, after the request was sent | `ExecutionError`, code `inference_outcome_unknown` | true (the run can have a cost; the SDK does not send it again) |
| the `timeout` of the caller passes | `ExecutionError`, code `client_timeout` | true |
| a stream with a wrong form | `ExecutionError`, code `invalid_response` | true |

When the SDK stops to read (time limit, `close()`, an error), it closes the connection. The
Engine then stops the run `[existing E/rest/chat_stream.py]`.

### C2.5 Resend and retry

- **The client layer never sends this request again after a 408, 429 or 5xx.** The HTTP client
  of `Client` has no retry layer `[existing S/client.py:92]` `[existing S/_engine/transport.py:170]`.
- **After a sign-in challenge of the hosted edge, the client signs in and sends the request one
  more time** (the request has the replay-safe mark) `[proposed P15]`
  `[existing S/_access/auth.py:662]`. Reason: on this route, a 302, 401 or 403 answer always
  comes before a run exists; the answer for a scheduled run has the status 200. This is
  different from `sf.classify`, which raises `access_reauthenticated` and sends nothing again
  `[existing S/_engine/classification.py:248]`.
- **Default: no retry** `[stated ans:Q4]`.
- **With `max_retries=N`** `[proposed]`: the SDK sends the call again only when the Engine said
  that a retry is safe (`x-should-retry: true`, or `should_retry: true` in the error event). It
  waits for `Retry-After` (or `retry_after`), else 1 s, 2 s, 4 s, ... with a maximum of 30 s. It
  does not retry `inference_outcome_unknown`, `client_timeout` or `invalid_response`. The total
  `timeout` covers all tries. The same rule applies with `stream=True`: the stream is buffered,
  so an error always comes before the first chunk reaches the caller.

### C2.6 Limits that the SDK does not check

The body limit (8,000,000 bytes), the length of `model` (32,000 characters), the recipe rules
for tools, and the picture rules stay with the Engine. Its error becomes the SDK error of C2.4
`[proposed]`.

## C3 — `ModelInference` → Engine: `GET /v1/operators`

Only for a recipe with a reducer `[existing S/_evaluation/runner.py:291]`. The client already
keeps the catalogue for its max-age `[existing S/_engine/catalog.py:402]`, so a call in that
time sends no catalogue request. A failure gives the error of the catalogue loader of today.
The request is replay-safe.

## C4 — Engine changes

### C4.1 Stream error event

Today: `data: {"error": {"message", "type", "code"}}` `[existing E/chat/sse.py:44]`.

New `[stated ans:Q5]` `[proposed P10]`: the `error` object also has `should_retry` (bool) and
`retry_after` (integer seconds, only when the plain answer for the same failure has a
`Retry-After` header). The values are those that the Engine already holds for the failure
`[existing E/rest/chat_errors.py:66]`. An OpenAI client ignores keys that it does not know. The
SDK also accepts an event with no `should_retry` (C2.4).

### C4.2 Plain reply with tool calls and no text

Today the plain reply has `"content": ""` `[existing E/rest/chat_answer.py:178]`
`[existing E/chat/result.py:63]`, and the stream has no `content` key
`[existing E/chat/sse.py:101]`. New `[proposed P13]`: the plain reply has `"content": null` in
that case, as OpenAI does. A reply with text does not change.

## C5 — caller → other library (`endpoint()`)

```python
e = sf.ModelInference(ensemble).endpoint()
client = OpenAI(base_url=e.base_url, api_key="unused", default_headers=dict(e.headers))
client.chat.completions.create(model=e.model, messages=[...])
```

The values are a snapshot. On a hosted Engine the token in `headers` expires; the user then calls
`endpoint()` again `[proposed P7]`. The docs say this next to the example.

# SDK model inference — contracts

One section for each connection of the inventory. Tags as in `00-overview.md` §2.

## C1 — caller → `recipe.chat`, `client.chat` and `sf.chat` (Python API)

Rewritten on 2026-11-23 for D13 to D17 (overview §5.5). There is no `sf.InferenceClient`.
C1.7 (2026-11-24, D18 to D25) adds the OpenAI client form; where it changes C1.2 or C1.3, C1.7
is the authority. C1.8 (2026-11-24, D26 to D30) turns tool calls off; where C1.2 or C1.7 says
that `tools` is sent or that `functions` is refused with `unsupported_parameter`, C1.8 is the
authority.

### C1.1 The three surfaces

```python
# S/inference.py: the namespaces of the clients. They are not top-level names of the package.
class Completions:                                   # sf.Client().chat.completions
    def create(self, prompt: str | None = None, *, model: Recipe | Url4 | str, ...): ...   # C1.2
class Chat:                                          # sf.Client().chat
    completions: Completions
    def endpoint(self, model: Recipe | Url4 | str) -> InferenceEndpoint: ...               # C1.5
class AsyncCompletions:                              # sf.AsyncClient().chat.completions
    def create(self, prompt: str | None = None, *, model: Recipe | Url4 | str, ...): ...   # a coroutine
class AsyncChat:                                     # sf.AsyncClient().chat
    completions: AsyncCompletions
    def endpoint(self, model: Recipe | Url4 | str): ...                                    # a coroutine

# recipe.chat: bound to one recipe, through the default client (sync)
class RecipeCompletions:
    def create(self, prompt: str | None = None, *, messages=None, tools=None, ...): ...    # no model
class RecipeChat:
    completions: RecipeCompletions
    def endpoint(self) -> InferenceEndpoint: ...

class Recipe(_Chainable, ABC):                       # S/recipe.py
    @property
    def chat(self) -> RecipeChat: ...

# S/chat.py: the module twin, sf.chat
completions                                          # .create(prompt=None, *, model, ...) as Completions
def endpoint(model: Recipe | Url4 | str) -> InferenceEndpoint: ...
```

- **`client.chat`** `[stated D13]`. `sf.Client` and `sf.AsyncClient` set the attribute `chat` in
  their constructor, next to `models` and `benchmarks` `[existing S/client.py:115]`. The
  namespace keeps its client and no other state. More than one thread or task can use it at one
  time. An `AsyncClient` belongs to one event loop `[implied]`.
- **`recipe.chat`** `[stated D14]`. A property of `Recipe`, so each recipe type has it
  (`sf.Model`, a Fusion, a Pipeline, a Gate, a Cascade, `WithBudget`, the corrective loops).
  - Each access gives a new small object that keeps only the recipe. The access compiles
    nothing, sends no request and raises nothing.
  - Each call takes `default_client()` at that time, as `sf.classify` does, so `sf.configure()`
    and `sf.close()` work as for each other module call `[existing S/_default_client.py:75]`.
  - It is sync only. For async, use `aclient.chat.completions.create(model=recipe, ...)`.
  - A step that is not a recipe (`sf.Fanout([...])` alone, `sf.Synthesize(...)` alone) has no
    `chat`. `sf.Url4` has no `chat` `[stated D17]`.
- **`sf.chat`** `[stated D15]`. A module, as `sf.models` `[existing S/models.py]`. Each call
  takes `default_client()` at that time and uses the implementation of `client.chat`. It is
  sync only.
- **`model`** `[proposed P1]`. A required keyword of `create` on `client.chat` and `sf.chat`
  (Python raises `TypeError` when it is missing), and the argument of `endpoint`. On
  `recipe.chat` the model is the recipe. The rules, checked at each call before a request and
  before a coroutine exists:
  - a `Recipe` (`sf.Model`, a Fusion, a Pipeline, a Gate, a Cascade, ...) `[stated ans:Q1]`;
  - a `sf.Url4`, or a string that starts with `(` after white space: URL4 text. Candidate URL4
    text is sent with no change. From an evaluation URL4 the SDK takes the `candidate` source
    `[proposed P14]`; an evaluation URL4 with no such source gives `PlanningError`;
  - each other string: a gateway model id, sent with no change.
  - Each other type: `TypeError`. An empty or blank string: `ValueError`.
- No surface sends a request before `create` or `endpoint` is called `[proposed P2]`. A recipe
  is compiled at each call. A recipe with a reducer is compiled with the operator catalogue that
  the client keeps `[existing S/_engine/catalog.py:402]`.
- Recipe errors `[proposed P17]`: a corrective loop (`CorrectiveLoop`, `SelfCorrective`, also
  inside `WithBudget`) gives `PlanningError`, code `recipe_not_supported`, from `create` and
  from `endpoint`. The property `recipe.chat` exists on such a recipe. Each other compiler
  error keeps its type of today (`ValueError` or `PlanningError`), as in `sf.evaluate`
  `[existing S/_evaluation/candidate.py:808]`.
- No surface keeps a conversation.
- Import rule: `S/recipe.py` loads the chat code inside the property, as it loads its other
  helpers `[existing S/recipe.py:97]`. The client module must not get an import cycle with
  `S/_inference/request.py`, which imports a helper from `S/client.py`.

### C1.2 `chat.completions.create`

```python
def create(
    self,
    prompt: str | None = None,
    *,
    model: Recipe | Url4 | str,                 # D13: required on client.chat and sf.chat; absent on recipe.chat
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

| Surface | `stream` | Result |
|---|---|---|
| `sf.Client().chat`, `recipe.chat`, `sf.chat` | literal `False` (default) | `ChatCompletion` |
| the same | literal `True` | `ChatStream` (iterable of `ChatCompletionChunk`) |
| the same | a `bool` variable | `ChatCompletion \| ChatStream` |
| `sf.AsyncClient().chat` | literal `False` (default) | awaitable of `ChatCompletion` |
| `sf.AsyncClient().chat` | literal `True` | awaitable of `AsyncChatStream` |
| `sf.AsyncClient().chat` | a `bool` variable | awaitable of `ChatCompletion \| AsyncChatStream` |

Each surface has three typed overloads on the value of `stream` `[stated ans:Q7]` `[stated D13]`.
The method name is the same on each surface. `AsyncCompletions.create` is a plain `def` that
returns a coroutine, so an argument error is raised by the call itself (the rule below).

The four `create` methods share one implementation of the checks and of the send. The
`IgnoredParameterWarning` names the line of the caller on each surface. `recipe.chat` and
`sf.chat` call this shared implementation directly with the default client; they do not go
through the attribute `chat` of that client. So an argument error makes no default client.

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
header names and hides each value. The method is `client.chat.endpoint(model)`,
`recipe.chat.endpoint()` and `sf.chat.endpoint(model)` `[stated D13 to D15]`. On
`sf.AsyncClient().chat` it returns an awaitable. The model rules are those of C1.1.

On an `https` Engine the method calls the sign-in of the client first (`Client.login()`, which
returns at once when a usable token exists), then reads the headers from the auth object of the
client `[existing S/client.py:204]` `[existing S/_access/base.py:23]`.

### C1.6 New public names

`ChatCompletion`, `ChatChoice`, `ChatMessage`, `ChatToolCall`,
`ChatFunctionCall`, `ChatUsage`, `ChatCompletionChunk`, `ChatChunkChoice`, `ChatDelta`,
`ChatDeltaToolCall`, `ChatStream`, `AsyncChatStream`, `InferenceInfo`, `FinalStep`,
`InferenceEndpoint`, `IgnoredParameterWarning` (16 names), and the module `chat` (as
`models`). Each goes into `__all__` and into the public surface snapshot
`[existing packages/screamingface/tests/test_public_surface.py]`. `InferenceClient` is not a
name of the package `[stated D16]`. The namespace classes (`Chat`, `Completions`, `AsyncChat`,
`AsyncCompletions`, `RecipeChat`, `RecipeCompletions`) are not top-level names; a caller who
needs them for a type annotation imports them from `screamingface.inference`. The snapshot also
gets the new member `chat` of `Client`, `AsyncClient` and each recipe class.

### C1.7 The OpenAI client form (D18 to D25, overview §5.6)

```python
class Client:                                        # the same on AsyncClient
    def __init__(
        self,
        *,
        engine_url: str = DEFAULT_ENGINE_URL,
        ...,                                         # the parameters of today, no change
        base_url: str | httpx.URL | None = None,     # D20
        api_key: object = None,                      # D19
        timeout: float | httpx.Timeout | None = None,  # D21
        max_retries: int = 0,                        # D21
        **openai_options: Any,                       # D22
    ) -> None: ...
```

- **`base_url`** `[stated ans:Q9]`. A string or an `httpx.URL`. The SDK removes white space at
  the two ends, each `/` at the end, and then one path `/v1`. The result must be an HTTP(S)
  origin with no credentials, no other path, no query and no fragment; if not, `ValueError`.
  Another type: `TypeError`. `base_url` together with an `engine_url` that is not the default:
  `TypeError`. `client.engine_url` is the origin.
- **`api_key`** `[stated ans:Q9]`. Each value is accepted. INVARIANT: the value is in no
  attribute of the client, in no request (URL, header, body), in no warning text and in no
  `repr`. A callable is not called. `None` gives no warning.
- **`timeout`, `max_retries`** `[proposed D21]`. The same checks as on the call (C1.2). They
  apply only to the chat calls of this client; each other call of the client keeps its limits.
  From an `httpx.Timeout` the SDK takes `read` (`None` means no limit of the SDK).
- **`**openai_options`** `[proposed D22]`. The fixed list of D22. A name that is not in the
  list: `TypeError` with the text of Python (`... got an unexpected keyword argument 'x'`).
- Order: the SDK raises each argument error of the constructor (also for `engine_url` and
  `scoreboard_url`) before it makes a connection pool and before it gives a warning. Each warning is an `IgnoredParameterWarning` that names the option and the line of
  the caller.

Changes to `create` (C1.2), on each of the four surfaces:

- `messages: Iterable[Mapping[str, Any] | ChatMessage] | None`, `tools: Iterable[Mapping[str, Any]] | None`
  `[proposed D23]`. A string, bytes or a mapping is not a list of messages (`TypeError`). A
  `ChatMessage` item is sent as the OpenAI SDK sends its message object: `role` and `content`
  always, `tool_calls` only when it has an item, `refusal` only when it is not `None`.
- `max_retries: int | None = None` and `timeout: float | httpx.Timeout | None = None`. `None`
  means the value of the client (D21).
- `**other` `[proposed D25]`: the list of C1.2 gets the 11 ignored names of D25, and
  `functions` and `function_call`, which are refused when their value is not `None`. The warning
  of these 13 names does not point to `sf.Model(params=...)`, because they are not model
  parameters of a recipe. As for each name of C1.2, a keyword with the value `None` also gives
  the warning (the constructor options of D22 do not: there `None` is the OpenAI default).

Changes to the reply types (C1.3) `[proposed D24]`:

- Class attributes with the value `None` (they are not dataclass fields, so the constructor,
  the equality and `to_dict()` do not change): `ChatCompletion.system_fingerprint`,
  `.service_tier`, `.moderation`; `ChatChoice.logprobs`; `ChatMessage.function_call`, `.audio`,
  `.annotations`; `ChatUsage.prompt_tokens_details`, `.completion_tokens_details`;
  `ChatCompletionChunk.system_fingerprint`, `.service_tier`, `.moderation`; `ChatChunkChoice.logprobs`;
  `ChatDelta.function_call`.
- Each reply type gets `model_dump(*, exclude_none=False)` (the dict of `to_dict()`; with
  `exclude_none=True`, no key with the value `None` at each depth),
  `model_dump_json(*, indent=None, exclude_none=False)` and `to_json(*, indent=2)` (JSON text
  of that dict, not ASCII-escaped).

### C1.8 Tool calls are turned off (D26 to D30, overview §5.7)

Each of the four surfaces applies this check in the shared implementation, after the argument
checks of C1.2 and before the warnings of `**other`:

| Call | Result |
|---|---|
| `tools` with at least one item | `PlanningError`, code `tools_not_available`, `details == {"param": "tools"}` |
| `functions` with at least one item `[proposed D29]` | the same, `param` `functions` |
| `messages[i]` has the role `tool` | the same, `param` `messages[i]` |
| `messages[i]` is an assistant message with at least one tool call (a dict, or a `ChatMessage`) | the same, `param` `messages[i].tool_calls` |
| `tools=[]`, `tools=None`, an empty iterable; `tool_calls` `None` or empty | accepted; `tools` is not sent |
| `tool_choice`, `function_call`, `parallel_tool_calls`, `functions=[]` or `None` | accepted, not sent, one `IgnoredParameterWarning` each |

- The error is permanent. Its text starts with "Tool calls are not available yet." and names the
  argument to remove.
- It is an argument error in the sense of C1.2: the call itself raises it, also in async mode; no
  default client is made; no request is sent; no warning is given.
- The check is fixed `[stated ans:Q14]`. The SDK has no switch for it.
- The Engine has the same check (HTTP 400 `tools_not_available`). If the SDK check and the
  Engine check differ, the caller gets the Engine answer as `PlanningError` with the same code
  (C2.4).
- The reply types and the stream types do not change. `reply.tool_calls` is `None` for each
  reply of an Engine with the check.

## C2 — SDK chat call → Engine: `POST /v1/chat/completions`

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

## C3 — SDK chat call → Engine: `GET /v1/operators`

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
e = ensemble.chat.endpoint()          # or client.chat.endpoint(ensemble)
client = OpenAI(base_url=e.base_url, api_key="unused", default_headers=dict(e.headers))
client.chat.completions.create(model=e.model, messages=[...])
```

The values are a snapshot. On a hosted Engine the token in `headers` expires; the user then calls
`endpoint()` again `[proposed P7]`. The docs say this next to the example.

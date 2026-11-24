# SDK model inference — `recipe.chat` and `client.chat` — overview

Status: APPROVED by the owner on 2026-11-18 ("spec approved"), after one independent review (§8).
Amended on 2026-11-23 after the team review: the class name and the call path (§5.4, D11, D12).
Amended again on 2026-11-23 by the owner: no new class; `chat` is on each recipe and on each client (§5.5, D13 to D17). §5.5 replaces D12. Base branch: PR #1937
(`OME-1963-engine-openai-chat-endpoint`); work branch: `engine-openai-chat-endpoint-variant`.
Parent epic: `OME-1297` (E8). The Linear issue is filed at PR-open.

## 1. Summary

A user of the ScreamingFace SDK (`packages/screamingface`) calls an ensemble as a chat model, with
the call path of the OpenAI SDK, and makes no new object for it (§5.5). Each recipe (a `Model`, a
Fusion, a Pipeline, a Gate, a Cascade) has `.chat.completions.create(...)`. Each client
(`sf.Client`, `sf.AsyncClient`) has the same path with `model=`, and the module `sf.chat` is its
twin for the default client. The call goes to the Engine route `POST /v1/chat/completions` of
PR #1937 and gives a reply with the field names of the OpenAI chat-completion object.

```python
import screamingface as sf

ensemble = sf.Fanout(["openrouter/a", "openrouter/b"]) >> sf.Synthesize("openrouter/c")

# 1. On the ensemble (the default client, sync)
reply = ensemble.chat.completions.create("What is the capital of France?")
reply.text                              # short form
reply.choices[0].message.content        # OpenAI field names
reply.usage.prompt_tokens, reply.cost_usd
for chunk in ensemble.chat.completions.create("...", stream=True): ...
endpoint = ensemble.chat.endpoint()     # base_url, model, headers for the OpenAI client or LiteLLM

# 2. On a client: the OpenAI form, and the async form
client = sf.Client()                    # before: openai.OpenAI()
reply = client.chat.completions.create(model=ensemble, messages=[...], tools=[...])
aclient = sf.AsyncClient()              # before: openai.AsyncOpenAI()
reply = await aclient.chat.completions.create(model=ensemble, messages=[...])

# 3. The module twin of the default client
reply = sf.chat.completions.create(model="openrouter/a", messages=[...])
```

## 2. Source tags

`[stated prompt]`, `[stated ans:Qn]`, `[existing <path>:<line>]`, `[implied]`, `[proposed]`, as
in the prompt-planner skill. Paths with the prefix `S/` are under
`packages/screamingface/src/screamingface/`; paths with `E/` are under
`apps/screamingface-engine/src/screamingface_engine/`.

## 3. Interview ledger (owner answers, verbatim)

| Id | Question | Answer |
|---|---|---|
| Q1 | the idea | "ideally we`d like some type of LLM compatible sdk interface where users can just put their ensembles (made with the screaminface sdk tools like fusions, gates, etc) and then use the common \".chat.complete(“prompt”, <maybe other stuff>)\" like libs / dependencies like the openai sdk or litellm, etc." |
| Q2 | the proposed shape (one object that holds the ensemble; reply with OpenAI field names and our extras; sync, async and streaming in the first version; a bridge for other libraries) | "I like that, but instead of sf.LLM let`s rename it to sf.ModelInference(ensemble)" |
| Q3 | a per-call sampling parameter (temperature, max_tokens, ...), which the Engine ignores | "Accept, warn, ignore" (NR: my recommendation was to refuse) |
| Q4 | automatic retry (each retry runs the full ensemble again) | "No retry by default (Recommended)" |
| Q5 | how a call that is not streamed travels | "Always streamed on the wire (Recommended)" |
| Q6 | the form of the async call | "One class, .chat.acomplete()" (NR), then replaced by Q7 |
| Q7 | the same | "instead of acomplete, couldn`t we just overload the complete() method having one sync and another async declarations?" |

**Reading of Q7 (to confirm in this review).** Python cannot bind a sync and an async function to
one name on one object. So the mode follows the client that the object holds: with a `Client`
(the default), `create` returns the reply; with an `AsyncClient`, `create` returns an
awaitable. Typed overloads on the client type give exact types. There is no `acomplete` and no
second public class.

The answers Q8 to Q11 (2026-11-24) are in §5.6. The answers Q12 to Q14 (2026-11-24) are in §5.7.

## 4. Inventory

| Kind | Item | State | Tag |
|---|---|---|---|
| actor | SDK user (a script, a notebook, an agent harness) | existing | [stated ans:Q1] |
| component | `sf.InferenceClient` and its `chat` namespace | planned | [stated ans:Q2] |
| component | reply types (`ChatCompletion`, `ChatCompletionChunk`, ...) | planned | [stated ans:Q2] |
| component | stream frame reader (SSE lines to chunks, chunks to one reply) | planned | [implied — ans:Q5] |
| component | recipe compiler `compile_candidate` | existing | [existing S/_evaluation/candidate.py:136] |
| component | `Client`, `AsyncClient` with the Engine login | existing | [existing S/client.py:49] |
| component | Engine chat route | existing (PR #1937) | [existing E/rest/chat_completions.py] |
| component | Engine stream error event | existing, changes | [implied — ans:Q5] |
| external | operator catalogue `GET /v1/operators` | existing | [existing S/_engine/catalog.py:40] |
| store | none: the SDK stores no prompt, no reply | — | [proposed] |
| external | analytics service: not used by this feature in this version | — | [proposed P9] |

Connections (each one is a contract in `contracts.md`): caller → `InferenceClient` (Python API);
`InferenceClient` → Engine (`POST /v1/chat/completions`, always streamed); `InferenceClient` →
Engine (`GET /v1/operators`, only for a recipe with a reducer); caller → other library
(`endpoint()` values).

There is no data model, so this spec has no `erd.md`.

## 5. Decisions

### 5.1 Stated by the owner

| Id | Decision | Tag |
|---|---|---|
| D1 | The class is `sf.ModelInference(ensemble)`; the call is `.chat.complete(...)`. **Replaced by D11 and D12** (§5.4) | [stated ans:Q1] [stated ans:Q2] |
| D2 | The reply has the OpenAI field names, plus the ScreamingFace extras | [stated ans:Q2] |
| D3 | The first version has sync, async and streaming | [stated ans:Q2] |
| D4 | A sampling parameter is accepted, gives one warning, and is not sent | [stated ans:Q3] |
| D5 | No automatic retry by default; `max_retries` is opt-in | [stated ans:Q4] |
| D6 | Each call is streamed on the wire; the SDK builds the full reply for a caller that did not ask for chunks | [stated ans:Q5] |
| D7 | One class and one method name for sync and async; the mode follows the client | [stated ans:Q7], mechanism [proposed] |
| D8 | The Engine stream error event gets a retry flag (D6 needs it) | [stated ans:Q5] (the option text named this change) |

### 5.2 Proposed by me (each needs your sign-off; none is in scope until then)

| Id | Proposal | Why |
|---|---|---|
| P1 | `InferenceClient(model, *, client=None)`: `model` is a recipe, a `sf.Url4`, or a string. A string that starts with `(` is URL4 text; each other string is a gateway model id. This is the rule of the Engine | one rule on both sides [existing E/chat/recipe.py:99] |
| P2 | The constructor sends no request. It compiles a recipe that needs no operator catalogue, so a recipe error shows where the user wrote it. A recipe with a reducer is compiled at each call, with the catalogue that the client keeps; the constructor does the shape checks that need no catalogue | fast errors; the text follows the catalogue, as an evaluation does |
| P3 | `create(prompt=None, *, model=None, messages=None, tools=None, stream=False, stream_options=None, use_cache=True, max_retries=0, timeout=None, **other)`. Exactly one of `prompt` and `messages` | small surface |
| P4 | "Accept, warn, ignore" (D4) applies to a fixed list of the known OpenAI chat parameters. A keyword that is not in the list (for example the typo `tool=`) gives `TypeError`, as in the OpenAI SDK. `n` above 1, `logprobs=True`, `audio` and audio `modalities` give `PlanningError`, because the Engine refuses them | a typo must not drop the tools silently [existing E/rest/chat_body.py:256] |
| P5 | Reply types are frozen dataclasses (the SDK convention), with `to_dict()`. Short forms: `reply.text`, `reply.tool_calls`, `reply.cost_usd`, `reply.trace_id` | [existing S/answer.py:83] |
| P6 | `stream=True` gives a stream object (iterable, context manager, `close()`); with an async client, an async stream object. `stream_options={"include_usage": True}` works as in OpenAI: one last chunk with empty `choices`. The stream is buffered: the first chunk comes when the run has ended | copied OpenAI loops work [existing E/chat/sse.py:3] |
| P7 | `endpoint()` gives `base_url`, `model` and `headers` for other libraries. It is a method, not a property: on a hosted Engine it signs in first (`Client.login()`), and a reducer recipe needs the catalogue. Its text form hides the header values | the token is a credential |
| P8 | The SDK sends a new W3C `traceparent` with each call (the trace helper of today), so a reply and an error have a `trace_id` | support [existing S/_engine/trace.py] |
| P9 | No analytics event for this feature in this version, and no reply on disk. The analytics service accepts only four event names today, and the SDK tells users that it sends exactly four | [existing apps/analytics/src/analytics_service/contract.py:33] |
| P10 | Stream error event of the Engine: the `error` object gets `should_retry` (bool) and, when the Engine has one, `retry_after` (seconds) | D6, D8 |
| P11 | Read time limit of 60 s between bytes (the Engine sends a keep-alive each 15 s by default). `timeout=` is a total limit for one call; by default the Engine limit (600 s) applies | no silent hang |
| P12 | Docs: a new API page for `InferenceClient`; the OpenAI guide page gets the SDK way to get the Candidate URL4 (`endpoint().model`), so the "run an evaluation first" step is only an alternative; README section; changelog entry | closes the follow-up of PR #1937 |
| P13 | Engine, plain route: a reply with tool calls and no text has `content: null` (today it has `""`; the stream has no `content` key; OpenAI sends null). Then the reply that the SDK builds from the stream is equal to the plain reply | one answer shape [existing E/rest/chat_answer.py:178] [existing E/chat/sse.py:101] |
| P14 | URL4 text that is an evaluation URL4 (the value of `report.candidates[...].url4`): the SDK takes its `candidate` source and sends that. The Engine refuses the linked text | `sf.InferenceClient(report.candidates["x"].url4)` works [existing E/chat/recipe.py:149] |
| P15 | After a sign-in challenge of the hosted edge, the client sends the chat request one more time. This is different from `sf.classify`, which raises and lets the user retry. Reason: on this route, a 302, 401 or 403 answer always comes before a run exists (the status of a scheduled run is 200) | a token that expired must not fail an agent loop [existing S/client.py:571] |
| P16 | `openai==2.54.0` as a dev dependency of the SDK (the version of the Engine tests), so a test runs the docs example of `endpoint()` with the real OpenAI client. A new dependency needs your word; without it, a test with plain `httpx` covers the three values and the docs example is not run | tested docs |
| P17 | A recipe error of the compiler keeps its type of today (`ValueError` or `PlanningError`), as in `sf.evaluate`. A corrective loop gives `PlanningError`, code `recipe_not_supported`, from the SDK | one behaviour for one recipe error [existing S/_evaluation/candidate.py:808] |

### 5.4 Team review (2026-11-23): the class name and the call path

Two items of feedback came from the team, through the owner. The owner told me to examine them and to
apply the items that are correct.

- F1 (verbatim): "I am not feeling ModelInference object to be intuitive, since we're wrapping
  already a model and inference is an action. Can we name it Endpoint ... If there's any concern
  (although I don't see why), another option could be InferenceSession or InferenceClient?"
- F2 (Andrew, through the owner): mirror an existing API (OpenAI or the HF inference API) as
  closely as possible, so that the SDK is a near drop-in replacement. "the ModelInference object
  would become, maybe, a Client object and then ... chat.complete would need to be
  chat.completions, etc."

| Id | Decision | Tag |
|---|---|---|
| D11 | The call path is `client.chat.completions.create(...)`, the path of the OpenAI SDK (and of the OpenAI alias of the HF `InferenceClient`). There is no `chat.complete` and no alias: the class is not released yet | [stated F2] |
| D12 | **Replaced by D13 to D16 (§5.5).** The class is `sf.InferenceClient(model=None, *, client=None)`. `model` is optional. `create(model=...)` and `endpoint(model=...)` take a model for one call, which replaces the model of the client for that call. With no model on the call and none on the client, the call raises `TypeError` before a request. So OpenAI code needs a change only in the line that makes the client | [stated F1] [stated F2], mechanism [proposed] |

Why `InferenceClient`, and not the other names:

- `Client`: the SDK has `sf.Client` and `sf.AsyncClient` already (the Engine connection, which
  this class takes as `client=`). A second class with that name is not possible.
- `Endpoint`: the class has an `endpoint()` method, which gives an `InferenceEndpoint` (the
  URL, the model text and the headers for another client). `sf.Endpoint(x).endpoint()` is not
  clear. Also, in the HF and cloud vocabulary an "endpoint" is a deployed server with a lifetime
  and a cost; this object deploys nothing. With D12 the object also calls more than one model, so
  it is not the endpoint of one ensemble.
- `InferenceSession`: a "session" has state, for example a conversation. This object keeps no
  conversation (C1.1).
- `InferenceClient`: one of the names of F1, and the "Client object" of F2. HF uses this name
  with the same meaning: a client with an optional default model and the OpenAI call path.

Kept as they are (each is already OpenAI-shaped, or it is an addition that OpenAI code never
uses, so it does not stop a drop-in change):

- The reply and chunk types have the OpenAI field names (D2), and `stream=True` gives an
  iterable stream (P6).
- `prompt` (a positional short form of one user message), `use_cache` and `max_retries` on
  the call are additions. OpenAI code does not use them.
- The async mode follows the client (D7): `sf.InferenceClient(client=sf.AsyncClient())`. OpenAI
  and HF have a second class (`AsyncOpenAI`, `AsyncInferenceClient`). A second class is a
  possible later addition; it is not in this change.
- Not in this change (possible later): `timeout` and `max_retries` on the constructor, as on the
  OpenAI client; `extra_headers`, `extra_query` and `extra_body` on the call (today they give
  `TypeError`, because the parameter list of P4 is the list of the Engine).

### 5.5 Owner change (2026-11-23): no new class, `chat` on the recipe and on the client

After D11 and D12 were built, the owner asked for a simpler use (verbatim): "What if, instead of
creating new Objects explicitly. What if any model/ensemble already had the `.chat.completions`
method embedded as a method in the screamingface sdk, in a way which the user doesn`t need to
create new objects or handle new varaibles by himself, and just use the method in a very
transparent way." I examined the code and proposed the design below. The owner answered: "let`s do
exactly as you recommend".

Facts of the code that the design uses:

- Each ensemble type is a subclass of one base class `[existing S/recipe.py:35]`. The subclasses are
  frozen dataclasses with slots, so a property on the base needs no storage.
- The SDK has one pattern for a capability: a namespace on the client (`client.models`,
  `client.benchmarks`, ...) with an async twin on `sf.AsyncClient`
  `[existing S/client.py:115]`, and a module twin that calls the default client
  `[existing S/models.py]`. `sf.InferenceClient` was outside this pattern: a third object that
  used four private members of the client.
- A value object that makes calls exists already: `Run.refresh()` and `Run.wait()`
  `[existing S/runs.py:102]`.

| Id | Decision | Tag |
|---|---|---|
| D13 | `sf.Client` and `sf.AsyncClient` get the namespace `chat`: `client.chat.completions.create(model=..., ...)` and `client.chat.endpoint(model)`. `model` is a required keyword of `create`. The sync namespace and the async namespace are two plain classes, as `Models` and `AsyncModels`. The mode follows the client, as in D7 | [stated owner 2026-11-23] |
| D14 | Each recipe has the property `chat`: `recipe.chat.completions.create(...)` (no `model` parameter) and `recipe.chat.endpoint()`. It uses the default client at each call, so it is sync only, as `sf.evaluate`. An async caller uses `aclient.chat.completions.create(model=recipe, ...)` | [stated owner 2026-11-23] |
| D15 | The module `sf.chat` is the twin of `client.chat` for the default client: `sf.chat.completions.create(model=..., ...)` and `sf.chat.endpoint(model)` | [stated owner 2026-11-23] |
| D16 | `sf.InferenceClient` is removed with no alias (it was not released). D12 is replaced. D11 (the call path `chat.completions.create`) stays. The reply types, the stream types, `InferenceEndpoint`, the errors, the warning, the wire contract C2 and the Engine do not change | [stated owner 2026-11-23] |
| D17 | `sf.Url4` gets no `chat` property in this change. URL4 text and a gateway model id go through `client.chat` or `sf.chat` as `model=` | [stated owner 2026-11-23] |

Trade-offs that the owner accepted:

- A recipe is no longer only a description: `recipe.chat` makes a paid call through the default
  client.
- A recipe that the chat route cannot run (a corrective loop) is refused by `create()`, not by a
  constructor. This is still before a request.
- A step that is not a recipe (`sf.Fanout([...])` alone) has no `chat`.
- `sf.Model("id").chat` runs the Candidate recipe of that model (with the default Candidate
  prompt). `client.chat.completions.create(model="id")` sends the id with no change.

The contracts are in `contracts.md` C1 (rewritten). The tests are MI-36 to MI-39 in `test-plan.md`.

### 5.6 Team feedback (2026-11-24): the one-line change from the OpenAI SDK

F3 (a colleague, through the owner, verbatim): "Andrew’s ideal is minimum friction such that
someone using another library, like the OpenAI library, could make a 1 line change
(openai.OpenAI(…) --> screamingface.Client(…)) and their code would keep working as is". The owner
asked me to add this approach.

I ran normal OpenAI SDK code against `sf.Client` with only the client line changed (a mock
Engine; `openai==2.54.0` for the comparison). These lines failed:

| OpenAI code | Result before this change |
|---|---|
| `Client(api_key=...)`, `base_url=`, `timeout=`, `max_retries=`, `organization=`, `project=`, `default_headers=`, `http_client=` | `TypeError` |
| `messages.append(reply.choices[0].message)` (the tool loop of the OpenAI docs) | `TypeError` |
| `messages=` as a generator | `TypeError` |
| `reply.model_dump()`, `.model_dump_json()`, `.to_json()` | `AttributeError` |
| `usage.prompt_tokens_details`, `choice.logprobs`, `message.function_call`, `reply.system_fingerprint` and 4 more | `AttributeError` |
| `extra_headers=`, `extra_query=`, `extra_body=`, `timeout=httpx.Timeout(...)` and 10 more call keywords | `TypeError` |

Owner answers (2026-11-24):

| Id | Question | Answer (verbatim option) |
|---|---|---|
| Q8 | A model name that is not a ScreamingFace id (`model="gpt-4o"`) | "No mapping": the name is sent as it is; the user changes each `model=` value |
| Q9 | The constructor arguments `api_key=` and `base_url=` | "Key ignored, base_url = Engine": `api_key` is accepted, never sent, one warning; `base_url` is the Engine URL in the OpenAI form (with `/v1`) |
| Q10 | OpenAI error classes (`openai.RateLimitError` and so on) | "Nothing now": the errors stay as they are; no docs table |
| Q11 | `client.responses`, `client.embeddings`, `completions.parse()`, `with_raw_response` | "Chat completions only": the docs list the surfaces that do not exist |

| Id | Decision | Tag |
|---|---|---|
| D18 | The criterion: for code that uses chat completions, the line that makes the client is the only line that changes (`openai.OpenAI(...)` to `screamingface.Client(...)`, `openai.AsyncOpenAI(...)` to `screamingface.AsyncClient(...)`). A test runs one program with the two clients and compares the results. Limits: the model name (Q8), the error classes (Q10), the other APIs (Q11) | [stated F3] [stated ans:Q8] [stated ans:Q10] [stated ans:Q11] |
| D19 | `sf.Client` and `sf.AsyncClient` accept `api_key=`. The client does not keep the value, does not send it, does not call it and does not show it. A value that is not `None` gives one `IgnoredParameterWarning`. The SDK does not read `OPENAI_API_KEY` | [stated ans:Q9] |
| D20 | `base_url=` is the Engine URL in the OpenAI form: an origin, with or without the path `/v1`. It is the value that `endpoint().base_url` gives. `base_url` together with an `engine_url` that is not the default gives `TypeError`. A URL with another path gives `ValueError` | [stated ans:Q9], rules [proposed] |
| D21 | `timeout=` and `max_retries=` on the constructor are the defaults of the chat calls of that client. A value on the call replaces the default for that call. The defaults of the SDK stay: no retry (D5) and no limit of the SDK. `timeout` is also accepted as an `httpx.Timeout`; the SDK uses its `read` value as the limit of the full call | [proposed] |
| D22 | Each other public option of the OpenAI constructor (`organization`, `project`, `webhook_secret`, `websocket_base_url`, `default_headers`, `default_query`, `http_client`, `admin_api_key`, `workload_identity`, `provider`) is accepted, is not used, and gives one `IgnoredParameterWarning` when its value is not `None`. Each other keyword is a `TypeError`, as today. This is the rule of D4 for the constructor | [proposed] |
| D23 | `messages` accepts a reply message object (`ChatMessage`) as an item, and `messages` and `tools` accept each iterable. So the tool loop of the OpenAI docs runs with no change | [proposed] |
| D24 | The reply types get the OpenAI attributes that the Engine never sets, with the value `None`, and the methods `model_dump()`, `model_dump_json()` and `to_json()` | [proposed] |
| D25 | `create` accepts each keyword of the OpenAI `chat.completions.create` of `openai==2.54.0`. The 11 new names (`extra_headers`, `extra_query`, `extra_body`, `prediction`, `web_search_options`, `prompt_cache_key`, `prompt_cache_options`, `prompt_cache_retention`, `safety_identifier`, `verbosity`, `moderation`) follow D4: accepted, not sent, one warning. `functions` and `function_call` with a value give `PlanningError`, code `unsupported_parameter`: a call must not lose its tools with only a warning (P4). The user changes them to `tools` | [proposed] |

Two tests compare the SDK with the installed `openai` package (the dev dependency of P16): each
public parameter of the OpenAI constructor and of the OpenAI `create` is accepted by the SDK,
and each field of the OpenAI reply objects is an attribute of the SDK reply objects. A later
`openai` version that adds a name makes these tests fail, so the gap is seen.

Not in this change:

- A map from OpenAI model names to ScreamingFace models `[stated ans:Q8]`.
- OpenAI error classes, and a `status_code` on the SDK errors `[stated ans:Q10]`.
- `client.responses`, `client.embeddings`, `client.completions`, `completions.parse()`,
  `completions.stream()`, `with_raw_response`, `with_streaming_response`,
  `client.with_options()`, `client.api_key` `[stated ans:Q11]`.
- The OpenAI options on `sf.configure()`. The criterion is about the client line.

The contract is `contracts.md` C1.7. The tests are MI-40 to MI-46 in `test-plan.md`.

### 5.7 Team feedback (2026-11-24): tool calls are turned off for now

F4 (through the owner, verbatim): "Another feedback that I got was to disable the tool usage
feature for now. So we must provide a proper error if someone tries to use / declare tools for
now."

Facts of the code: the Engine route of PR #1937 has a full tool-call feature (the final-step
route; 16 test files), and the SDK sends `tools` to it. The docs of the two show tools.

Owner answers (2026-11-24):

| Id | Question | Answer (verbatim option) |
|---|---|---|
| Q12 | Where must tools be refused? | "Engine and SDK": the Engine answers HTTP 400 before a run; the SDK raises the same error before it sends a request |
| Q13 | Which requests count as tool use? | "Declared tools and tool turns": `tools=` with at least one item, and a conversation that has a tool message or an assistant message with `tool_calls`. `tools=[]` stays accepted. `tool_choice` stays ignored |
| Q14 | How must the feature be turned off? | "Fixed refusal, no switch": the request is always refused. The tool code stays but nothing can reach it; its tests call the inner functions or are removed |

| Id | Decision | Tag |
|---|---|---|
| D26 | A chat call that declares or uses a tool raises `PlanningError`, code `tools_not_available`, permanent, with `details["param"]`. It comes from the call itself, before a default client is made, before a request and before a warning. The Engine answers HTTP 400 with the same code for each other client (Engine PRD `tool-calls.md` §0, TC-S23) | [stated ans:Q12] |
| D27 | Tool use is: `tools` with at least one item; a `tool` message; an assistant message (a dict or a `ChatMessage`) with at least one tool call. `tools=[]`, `tools=None` and an empty iterable are not tool use | [stated ans:Q13] |
| D28 | The refusal is fixed. No setting, argument or environment variable turns it off. The tool code stays: the `tools` parameter, the reply types and the stream chunks. A reply with a tool call is still read | [stated ans:Q14] |
| D29 | `functions` with at least one item is refused in the same way (it is the old OpenAI keyword that declares tools). `function_call` is a choice keyword, as `tool_choice`: accepted, not sent, one warning. This replaces the `functions` and `function_call` rule of D25 | [proposed] |
| D30 | A test that sent tools through a call now uses the inner function (the body builder, the message helper), or it has no `tools=` and the mock Engine gives the tool call. The docs show no tools example: the snippet `tools.py` is removed and `openai_one_line.py` has a conversation with no tool | [stated ans:Q14], detail [proposed] |

Effect on §5.6: the criterion D18 still holds for code with no tools. The tool loop of the OpenAI
docs is now one of the parts that need a change by hand; the test MI-40 runs a conversation with
no tool, and MI-47 pins the error.

The contract is `contracts.md` C1.8. The tests are MI-47 to MI-50 in `test-plan.md`.

### 5.3 Not in this work

- The name `screamingface/<recipe-name>` and the pull of a published recipe (text of the epic) `[proposed]`.
- A module function `sf.chat(...)`, a `system=` short form, conversation memory, a tool runner `[proposed]`.
- Sampling parameters that have an effect (an Engine feature) `[stated ans:Q3]`.
- A dependency on the `openai` package, or adapters for LangChain or LiteLLM (the `endpoint()` values are sufficient) `[proposed]`.
- A notebook example `[proposed]`.
- An analytics event for an inference call (it needs a change to the analytics service, to its
  contract and to the notice that users read) `[proposed P9]`.

## 6. Documents

| File | Content |
|---|---|
| `prd/model-inference.md` | the object, `chat.completions.create`, sync and async, the stream |
| `prd/endpoint-bridge.md` | `endpoint()` for other libraries |
| `prd/stream-error-retry-flag.md` | the Engine change (P10) |
| `contracts.md` | the Python API, the wire contract, the error map |
| `test-plan.md` | test strategy, the TDD order, the gates |

Reading order: this file, `contracts.md`, then the PRDs.

## 7. Risks for the plan stage

| Id | Risk | State |
|---|---|---|
| R1 | Resend of a paid call | Resolved as fact: the HTTP client of `Client` has no retry layer, so a 408, 429 or 5xx is never sent again by the client. The replay-safe mark controls only the resend after a sign-in challenge (P15). The plan adds a streamed POST seam next to `_engine_get` |
| R2 | Recipes that the compiler refuses | Resolved as fact: a reducer with no catalogue, and `over='benchmark'` with no benchmark, raise `ValueError`; a corrective loop raises `PlanningError` with a text about a benchmark, so the SDK checks it first (P17) |
| R3 | Typed overloads | The SDK uses pyright in basic mode. Overloads on the client type are valid; the constructor needs its own overloads, and `create` needs one more overload for a `stream` value that is not a literal. A typing test comes first |
| R4 | The reply that the SDK builds must equal the plain reply | Open until P13 and test SE-5. `id` and `created` are not part of the comparison |
| R5 | Auth headers for `endpoint()` | Resolved as fact: the auth object already gives them; the token is usable only after `Client.login()` named the audience |
| R6 | Docs snippets for the SDK | Run in SDK tests; both path blocks of the SDK test workflow get the snippet path; `public-docs/CLAUDE.md` names the new files |
| R7 | The Engine setting `chat_keepalive_s` above 60 makes the read limit of P11 fail a healthy call | The Engine README states the limit; a larger keep-alive is not supported with this SDK version |

## 8. Review

One independent review (Opus, read-only, 2026-11-18) compared this spec with the code.
Verdict: approve with fixes; 1 blocker, 7 major, 13 minor. All are applied in this text. It
confirmed by execution that the text that the SDK compiles for a Model, a Fusion, a Pipeline and
a Fanout with a Vote passes the recipe check of the Engine, and that an evaluation uses the same
candidate text.

| Finding | Change |
|---|---|
| The analytics service refuses a new event name (blocker) | P9: no analytics event |
| The compiler raises `ValueError` for most recipe errors | P17, risk R2 |
| A tool-call reply with no text differs between the stream and the plain route | P13; a chunk tool call has an `index` |
| The client has no retry layer; the resend rule after a challenge was not stated | P15, risk R1 |
| A kept default client breaks after `sf.close()` | the default client is taken at each call |
| `endpoint()` gets no token before a sign-in | P7 |
| The URL4 that users hold is an evaluation URL4 | P14 |
| Retry with `stream=True`, an Engine with no flag, the buffered stream | contracts C2.3–C2.5 |
| `**ignored` hides typos | P4 |

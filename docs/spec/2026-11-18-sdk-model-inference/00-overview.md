# SDK model inference — `sf.ModelInference` — overview

Status: APPROVED by the owner on 2026-11-18 ("spec approved"), after one independent review (§8). Base branch: PR #1937
(`OME-1963-engine-openai-chat-endpoint`); work branch: `engine-openai-chat-endpoint-variant`.
Parent epic: `OME-1297` (E8). The Linear issue is filed at PR-open.

## 1. Summary

The ScreamingFace SDK (`packages/screamingface`) gets one public class, `sf.ModelInference`. A
user gives it an ensemble that was made with the SDK (a `Model`, a Fusion, a Pipeline, a Gate, a
Cascade), and then calls `.chat.complete(...)`, as with the OpenAI SDK or LiteLLM. The call goes
to the Engine route `POST /v1/chat/completions` of PR #1937 and gives a reply with the field
names of the OpenAI chat-completion object.

```python
import screamingface as sf

ensemble = sf.Fanout(["openrouter/a", "openrouter/b"]) >> sf.Synthesize("openrouter/c")

llm = sf.ModelInference(ensemble)
reply = llm.chat.complete("What is the capital of France?")
reply.text                              # short form
reply.choices[0].message.content        # OpenAI field names
reply.usage.prompt_tokens, reply.cost_usd

reply = llm.chat.complete(messages=[...], tools=[...])
for chunk in llm.chat.complete("...", stream=True): ...

allm = sf.ModelInference(ensemble, client=sf.AsyncClient())
reply = await allm.chat.complete("Hello")

endpoint = llm.endpoint()               # base_url, model, headers for the OpenAI client or LiteLLM
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
(the default), `complete` returns the reply; with an `AsyncClient`, `complete` returns an
awaitable. Typed overloads on the client type give exact types. There is no `acomplete` and no
second public class.

## 4. Inventory

| Kind | Item | State | Tag |
|---|---|---|---|
| actor | SDK user (a script, a notebook, an agent harness) | existing | [stated ans:Q1] |
| component | `sf.ModelInference` and its `chat` namespace | planned | [stated ans:Q2] |
| component | reply types (`ChatCompletion`, `ChatCompletionChunk`, ...) | planned | [stated ans:Q2] |
| component | stream frame reader (SSE lines to chunks, chunks to one reply) | planned | [implied — ans:Q5] |
| component | recipe compiler `compile_candidate` | existing | [existing S/_evaluation/candidate.py:136] |
| component | `Client`, `AsyncClient` with the Engine login | existing | [existing S/client.py:49] |
| component | Engine chat route | existing (PR #1937) | [existing E/rest/chat_completions.py] |
| component | Engine stream error event | existing, changes | [implied — ans:Q5] |
| external | operator catalogue `GET /v1/operators` | existing | [existing S/_engine/catalog.py:40] |
| store | none: the SDK stores no prompt, no reply | — | [proposed] |
| external | analytics service: not used by this feature in this version | — | [proposed P9] |

Connections (each one is a contract in `contracts.md`): caller → `ModelInference` (Python API);
`ModelInference` → Engine (`POST /v1/chat/completions`, always streamed); `ModelInference` →
Engine (`GET /v1/operators`, only for a recipe with a reducer); caller → other library
(`endpoint()` values).

There is no data model, so this spec has no `erd.md`.

## 5. Decisions

### 5.1 Stated by the owner

| Id | Decision | Tag |
|---|---|---|
| D1 | The class is `sf.ModelInference(ensemble)`; the call is `.chat.complete(...)` | [stated ans:Q1] [stated ans:Q2] |
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
| P1 | `ModelInference(model, *, client=None)`: `model` is a recipe, a `sf.Url4`, or a string. A string that starts with `(` is URL4 text; each other string is a gateway model id. This is the rule of the Engine | one rule on both sides [existing E/chat/recipe.py:99] |
| P2 | The constructor sends no request. It compiles a recipe that needs no operator catalogue, so a recipe error shows where the user wrote it. A recipe with a reducer is compiled at each call, with the catalogue that the client keeps; the constructor does the shape checks that need no catalogue | fast errors; the text follows the catalogue, as an evaluation does |
| P3 | `complete(prompt=None, *, messages=None, tools=None, stream=False, stream_options=None, use_cache=True, max_retries=0, timeout=None, **other)`. Exactly one of `prompt` and `messages` | small surface |
| P4 | "Accept, warn, ignore" (D4) applies to a fixed list of the known OpenAI chat parameters. A keyword that is not in the list (for example the typo `tool=`) gives `TypeError`, as in the OpenAI SDK. `n` above 1, `logprobs=True`, `audio` and audio `modalities` give `PlanningError`, because the Engine refuses them | a typo must not drop the tools silently [existing E/rest/chat_body.py:256] |
| P5 | Reply types are frozen dataclasses (the SDK convention), with `to_dict()`. Short forms: `reply.text`, `reply.tool_calls`, `reply.cost_usd`, `reply.trace_id` | [existing S/answer.py:83] |
| P6 | `stream=True` gives a stream object (iterable, context manager, `close()`); with an async client, an async stream object. `stream_options={"include_usage": True}` works as in OpenAI: one last chunk with empty `choices`. The stream is buffered: the first chunk comes when the run has ended | copied OpenAI loops work [existing E/chat/sse.py:3] |
| P7 | `endpoint()` gives `base_url`, `model` and `headers` for other libraries. It is a method, not a property: on a hosted Engine it signs in first (`Client.login()`), and a reducer recipe needs the catalogue. Its text form hides the header values | the token is a credential |
| P8 | The SDK sends a new W3C `traceparent` with each call (the trace helper of today), so a reply and an error have a `trace_id` | support [existing S/_engine/trace.py] |
| P9 | No analytics event for this feature in this version, and no reply on disk. The analytics service accepts only four event names today, and the SDK tells users that it sends exactly four | [existing apps/analytics/src/analytics_service/contract.py:33] |
| P10 | Stream error event of the Engine: the `error` object gets `should_retry` (bool) and, when the Engine has one, `retry_after` (seconds) | D6, D8 |
| P11 | Read time limit of 60 s between bytes (the Engine sends a keep-alive each 15 s by default). `timeout=` is a total limit for one call; by default the Engine limit (600 s) applies | no silent hang |
| P12 | Docs: a new API page for `ModelInference`; the OpenAI guide page gets the SDK way to get the Candidate URL4 (`endpoint().model`), so the "run an evaluation first" step is only an alternative; README section; changelog entry | closes the follow-up of PR #1937 |
| P13 | Engine, plain route: a reply with tool calls and no text has `content: null` (today it has `""`; the stream has no `content` key; OpenAI sends null). Then the reply that the SDK builds from the stream is equal to the plain reply | one answer shape [existing E/rest/chat_answer.py:178] [existing E/chat/sse.py:101] |
| P14 | URL4 text that is an evaluation URL4 (the value of `report.candidates[...].url4`): the SDK takes its `candidate` source and sends that. The Engine refuses the linked text | `sf.ModelInference(report.candidates["x"].url4)` works [existing E/chat/recipe.py:149] |
| P15 | After a sign-in challenge of the hosted edge, the client sends the chat request one more time. This is different from `sf.classify`, which raises and lets the user retry. Reason: on this route, a 302, 401 or 403 answer always comes before a run exists (the status of a scheduled run is 200) | a token that expired must not fail an agent loop [existing S/client.py:571] |
| P16 | `openai==2.54.0` as a dev dependency of the SDK (the version of the Engine tests), so a test runs the docs example of `endpoint()` with the real OpenAI client. A new dependency needs your word; without it, a test with plain `httpx` covers the three values and the docs example is not run | tested docs |
| P17 | A recipe error of the compiler keeps its type of today (`ValueError` or `PlanningError`), as in `sf.evaluate`. A corrective loop gives `PlanningError`, code `recipe_not_supported`, from the SDK | one behaviour for one recipe error [existing S/_evaluation/candidate.py:808] |

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
| `prd/model-inference.md` | the object, `chat.complete`, sync and async, the stream |
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
| R3 | Typed overloads | The SDK uses pyright in basic mode. Overloads on the client type are valid; the constructor needs its own overloads, and `complete` needs one more overload for a `stream` value that is not a literal. A typing test comes first |
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

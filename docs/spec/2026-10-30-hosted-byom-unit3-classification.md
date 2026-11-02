# Hosted BYOM Unit 3: classification inference through the hosted Engine

Tickets, under epic `OME-1306`, one per landing: `OME-1794` (`aigateway`), `OME-1795`
(`screamingface-engine`), `OME-1796` (`client-sf`). Branch `OME-1794-hosted-byom-unit3`. Ledger:
`docs/work/2026-10-30-hosted-byom-unit3.md`. Plan: `docs/plan/2026-10-30-hosted-byom-unit3.md`
(written after this spec is approved). Base: origin/main `969d4e303`. The branch was moved there
from `f76cacf85`, through `05a7a6234`, `fed613da2`, `e915d8037` and `bc96df570`, before any commit; the only
cited file main changed on the way is `routes/model_parameters.py`, by one scope literal.

Governing design: the remote-endpoint component card in `screamingface-design`
(`solutions/screamingface/product/aigateway/component/provider-adapters/component/remote-endpoint/index.md`,
"Classification Contract", origin/main `63d41f7`). This spec decides how the current code meets
that contract. Where the two differ, the card wins and the difference is a finding to raise.

Code paths are relative to `apps/aigateway/src/aigateway/` in sections 1 and 4.1, and to
`apps/screamingface-engine/src/screamingface_engine/` in sections 3.3, 3.4 and 4.2, unless a path
starts at the repo root.

## 1. Problem

Units 0 to 2 serve chat models on configured endpoints, through the Gateway and the hosted
Engine. A configured endpoint can also host a text classifier, for example a Hugging Face
text-classification deployment. None of that path exists today:

- **Definitions refuse it.** `ChatTarget` and `_ChatTargetDoc` pin `task` to `"chat"` and
  `contract` to `"openai-chat-basic-v1"` (`plugins/remote_endpoint/definitions.py:45-51`,
  `:86-91`).
- **One list feeds every chat surface.** `register_models()` feeds `/v1/models`, model
  admission, model parameters and the `/v1/providers` predicate
  (`routes/models.py:64`, `routes/model_admission.py:168`, `routes/model_parameters.py:104`,
  `routes/providers.py:35`). A classifier placed there would be offered as a chat model, and a
  provider with only classifiers would disappear from `/v1/providers`.
- **Readiness is a chat ping** (`plugins/remote_endpoint/validation.py`).
- **No operation exists.** The Gateway has no `/v1/classifications`, the Engine has no
  `/classify` endpoint, and the SDK has no call for either.

## 2. Goal and non-goals

**Goal.** An authenticated caller sends a classifier model ID and a text to the hosted Engine.
A worker asks the Gateway. The Gateway calls the configured classifier with that account's own
Connection and returns the model's labels and scores unchanged. A classifier-only endpoint is
listed, connected and validated like a chat endpoint, without a fake chat model.

**Non-goals.** Routing on a label, any downstream model call, argmax, softmax, tie breaking,
batch input, zero-shot labels, images or audio, a classification cache, Taxonomy accounting, a
classifier-only Engine world, request-scoped credentials, and any live endpoint call. A real
classifier smoke is Unit 4, separately authorized.

## 3. Contract

### 3.1 Target declaration

A classifier is a target of a configured endpoint, in the same file and schema version as chat:

```toml
[[endpoints.targets]]
alias = "classifier_v1"
task = "text-classification"
contract = "hf-text-classification-v1"
request_path = "/"
response_envelope = "single-batch"   # or "flat"
score_semantics = "bounded-score"
```

- `task` selects the target kind; each kind has its own required fields and refuses the
  others' (a classifier has no `upstream_model`).
- An unknown `task` is refused at `endpoints.N.targets.M.task`. The refusal names the location
  and the rule and never echoes the value, like every refusal in this module.
- Aliases are unique across both kinds within an endpoint. `validation_target` may name either
  kind.
- `score_semantics` accepts only `"bounded-score"` in this unit. Raw scores are a later contract
  value, not a flag.
- The superseded endpoint-level `classifiers` and `base_url` forms stay refused.

### 3.2 Gateway operation

`POST /v1/classifications`, request:

```json
{"model": "byom_abcdef0123456789abcdef0123456789/classifier_v1", "input": "Text to classify"}
```

Success, `200`:

```json
{
  "object": "classification",
  "model": "byom_abcdef0123456789abcdef0123456789/classifier_v1",
  "contract": "classification-scores-v1",
  "scores": [{"label": "LABEL_0", "score": 0.8}, {"label": "LABEL_1", "score": 0.2}]
}
```

- **Body.** Exactly `model` and `input`, both JSON strings. Any other field, including `seed`,
  `top_k`, `function_to_apply` and `stream`, is refused with `400 unsupported_parameters` before
  any key read.
- **Wire.** The Gateway sends `{"inputs": <input>}` to `origin + request_path` with the
  Connection's bearer key. The text is forwarded byte for byte: no template, no truncation.
- **Result.** The configured envelope is decoded: `flat` is a list of `{label, score}`;
  `single-batch` is a list holding exactly one such list. Nothing else is flattened or picked.
- **Validation.** At least one item. Labels are nonempty strings, unique. Scores are finite
  numbers, not booleans, in `[0, 1]` for `bounded-score`. The sum is not checked.
- **Order.** Upstream order and ties are kept. Nothing is sorted, dropped or selected.

### 3.3 Engine ingress

One stable world endpoint, `/classify`, present whenever the Gateway integration is configured.

- The caller sends the encoded subrequest `/classify?q=(<context>)!classify`. The context is a
  JSON object with exactly `model` and `input`, both strings.
- The worker sends only those two values to `POST /v1/classifications`, under the trusted
  request scope. The context never supplies an origin, a header, a key or a path.
- The result is the Gateway's JSON, served as `application/json`. A large result follows the
  existing artifact redirect.
- Adding a classifier needs no Engine route and no world config entry.

### 3.4 Size

The direct-call limit stays 8 KiB of encoded path and query bytes, enforced by the App with
`414 uri_too_long` (`rest/mounts.py:322-325`). The JSON envelope counts. Measured with the
current url4 encoder and httpx for the model ID `byom_<32 hex>/classifier_v1`:

| Input made of | Largest input that fits |
|---|---|
| Envelope alone | 117 bytes of overhead |
| ASCII letters | 8075 characters |
| Cyrillic letters | 1345 characters |
| Double quotes | 2018 characters |
| CJK characters | 897 characters |
| Emoji | 672 characters |

## 4. Design

### 4.1 Gateway (`aigateway`)

| ID | Decision |
|---|---|
| G1 | **Typed classifier target.** A `ClassificationTarget` dataclass next to `ChatTarget`. `EndpointDefinition.targets` holds both. The document model picks the kind by `task` (section 3.1). |
| G2 | **Chat stays chat.** `register_models()` and the chat path see chat targets only. A classifier ID sent to chat gets the existing `400 invalid_model` before any key read. |
| G3 | **Two provider hooks, default empty.** One lists a provider's classifiers. One dispatches a classification. The base class answers "none" and "unsupported", so every existing plugin is unchanged. |
| G4 | **Provider listing by capability.** `/v1/providers` keeps a provider that has chat models or classifiers. Existing providers have no classifiers, so their rows do not change. |
| G5 | **Catalog.** `GET /v1/classifiers` lists the caller's granted classifiers, and `GET /v1/classifiers/details?model=` gives task, contract and access status (`execution_access`, as `/v1/model-parameters` computes it). Same grant gate (`VIEW`) and `private, no-store` headers as `/v1/model-parameters`, on success and on refusal. An ungranted caller gets the unknown-provider answer whatever the alias, so it cannot learn which aliases exist; a granted caller's unknown or chat alias gets `404 model_not_found`. |
| G6 | **One route, existing ports, the chat order.** Body shape first; a body that is not JSON, one nested past the decoder's depth included, is the `400` malformed-body refusal. Then the provider prefix and registry lookup, then the `INVOKE` grant, then the target and its task, then credential resolve and authorize through `ProviderAccess`, then dispatch through `dispatch_with_budgets` with the existing overload retry. The grant comes before any alias check, as in chat (`routes/chat.py:136` before `:702`), so an ungranted caller cannot probe aliases. Refusals reuse the chat route's: an ungranted or absent provider is `400 unknown provider`; a granted caller's unknown alias or chat alias is `400 invalid_model`. An unknown field is named in the refusal, unless a name cannot be encoded as UTF-8, which is `400 invalid_request` with no names. The Gateway's own `503 provider_queue_timeout` logs at WARNING and an upstream `503` at ERROR, as in chat. No credential read and no upstream I/O happen before these checks pass. A client disconnect answers `499`, as in chat. The route imports no chat module. |
| G7 | **Transport.** The existing endpoint client and bounded streamed read; `200` only; no redirects. Any other status or a malformed body ends as the existing sanitized failure. An upstream 401 or 403 is returned without trying another key. |
| G8 | **Readiness by task.** When `validation_target` is a classifier, the probe is one classification of a fixed synthetic text. It is `VALID` only when the result passes section 3.2 validation. The status table is the chat probe's. |
| G9 | **No cache, no accounting.** The classification path never reads or writes the global cache and emits no usage or cost. |
| G10 | **Files.** Decoder and request in a new `plugins/remote_endpoint/classification.py`; routes in new `routes/classifications.py` and `routes/classifiers.py`. `main.py` (oversized) gains only router includes. |

### 4.2 Engine (`screamingface-engine`)

| ID | Decision |
|---|---|
| E1 | **Registration.** `/classify` is registered in `build_world` (`world/factory.py`), right after `build_aigateway_world` returns and before the read-side mounts and the direct-mount snapshot (`:226-240`). Every production path builds through `build_world`, so the App table, cold and warm children and local mode all see it. Registering inside `build_aigateway_world` instead would change three prior exact-route-set tests (`apps/screamingface-engine/tests/unit/test_aigateway_connector.py:246`, `:271`, `:372`). |
| E2 | **Collision.** A declared model at `/classify` fails world composition with a named `WorldConfigError` before registration. A `[data]` mount at `/classify` already fails with a `WorldConfigError` when the read-side mounts register after it. Never a raw `ValueError`, never a silent skip, and the half-built world is closed. |
| E3 | **Strict envelope.** The intent must be `classify`. The context must be the exact two-field JSON object. Anything else fails permanently with url4's `malformed_source` (400) before any classification request. |
| E4 | **Refusals before inference.** The handler refuses any run that carries an answer seed, or runs in capture or frozen-copy replay mode (`request_scope.py:122-123`), with an Engine code mapped to `400` in `_ENGINE_STATUS` (`world/serving.py:196`). Without that mapping a permanent Engine code becomes `502`. The boundary is no classification request and no upstream inference, not zero Gateway requests (section 6, decision 6). A direct `/classify` call with either frozen-copy header is refused by the App before any run (`rest/mounts.py:308-311`), and a replay run opens no copy, so both make no Gateway request. A capture run reaches `/classify` only inside an expression on `GET /?q=` (`rest/routes.py:854`). Its executor opens the frozen copy before the expression and seals it after the failed run (`runner/executor.py:1117`, `:1127`). Those two existing requests stay; the handler then refuses, and no `POST /v1/classifications` is sent. |
| E5 | **Gateway call.** The existing per-node Gateway client, `_headers(scope)` (identity and `traceparent`, no Authorization), the budget headers, and the existing `_post_completion(path=...)`, `_raise_for_status` and `_json_or_raise`. The chat-only helpers (`_messages`, the completion loop, `parse_choice`, cache and attempt fields) are not used. |
| E6 | **Not found is one answer.** The Gateway's `400 unknown provider` and `400 invalid_model` both become one Engine code mapped to `404` in `_ENGINE_STATUS`, with one fixed message. A caller cannot tell an unknown, an ungranted and a chat model ID apart. The code is not url4's `endpoint_not_found`, which means the route itself is absent. |
| E7 | **Result.** The worker checks the Gateway's JSON against section 3.2 before returning it, so a Gateway fault cannot reach the caller as a success. |
| E8 | **Cost stays unknown, and says so.** The executor marks a run total unpriced only when a reported call has no cost; a call that reports nothing is simply absent, so a classification next to a priced chat call would leave a priced total that omits it (`runner/executor.py:518-528`, `:704-707`). Once a classification request is handed to `_post_completion`, the handler therefore reports one usage record with `cost_usd=None`, whatever the outcome, and the run total latches unpriced. Its two token counts are 0 only because the sink requires them; they are not measured values. A refusal before dispatch reports nothing. This keeps the total honest; it is not Taxonomy accounting (section 6, decision 7). `Cache-Control` is ignored because no classification cache exists. Transport retries follow the existing `_post_completion` rule. |
| E9 | **Files.** The handler lives in a new `world/classification.py` that imports no url4 module, so the url4 import allowlist (`apps/screamingface-engine/tests/unit/test_url4_executor.py:647-676`) stays as it is. It raises `RunnerRequestError` (`world/errors.py`) with a stable code; the registration in `world/factory.py`, already on that allowlist, turns it into url4's `ResolutionError`, as `_ModelEndpoint` does (`world/connector.py:487-491`). It reuses the connector's Gateway helpers (`_headers`, `_post_completion`, `_raise_for_status`, `_json_or_raise`) and adds the two budget headers the chat loop sends. After review, `world/connector.py` (1768 lines) gains one helper, `_report_unpriced_call`, next to `_report_usage`, for E8: the usage sink is a url4 import, which the allowlist keeps out of `world/classification.py`. |
| E10 | **Access-log redaction.** One filter on the `uvicorn.access` logger, installed by the App itself so every start path has it. It touches access records only, never other Engine logs. uvicorn 0.52.3 builds the line from five record arguments; the filter replaces only the third, the path with its query, by the part before the first `?`, before the line is formatted. Method, path, HTTP version and status stay. This removes the text of a direct `/classify` call and of an expression on `GET /?q=` alike, and chat `q=` too. |

### 4.3 Client SDK (`client-sf`), proposed

No public SDK path calls `/classify` today. The smallest helper:

- builds the context with `json.dumps` and the url4 subrequest encoder, which escapes `+` (the
  Engine decodes with `unquote_plus`);
- refuses an input whose encoded request exceeds 8 KiB before any network call;
- calls `/classify` through the SDK's existing Engine client and authentication, and decodes a
  typed result: label and score pairs in upstream order;
- never marks the call safe to replay. The existing GET seams mark every request so, which lets
  the auth layer re-send it after a re-login (`packages/screamingface/src/screamingface/client.py:484-496`).
  A paid call must not be re-sent, so the helper uses one new unmarked private seam;
- sends `Prefer: wait=30` and gives that request a read timeout of 45 seconds. The Engine bounds a
  direct call by the smaller of the request's wait and its own `sync_max_wait_s`
  (`apps/screamingface-engine/src/screamingface_engine/rest/mounts.py:346-348`). That limit is
  30 seconds by default and configurable, for example to 60, so the helper states its wait instead
  of relying on the default. Whatever the server limit, the Engine's own `504 timeout` then
  arrives before the client gives up;
- tells a result, url4's `{"error": {"code", "message"}}` envelope and a `303` artifact redirect
  apart, and fetches the redirect with a bounded read. It follows a `303` only when its
  `Location`, exactly as received, has the form the Engine's `signed_artifact_path` writes:
  `/artifacts/<hex id>?exp=<digits>&sig=<token>`. httpx resolves dot segments, so a prefix check
  would let `/artifacts/../classify?q=...` send the classification a second time; a dot, a `%`,
  an extra slash, a scheme or a host never fits that form. When Access challenges that fetch and
  the auth layer completes the login, the fetch alone is sent once more: Access stopped it at its
  edge, and reading a stored result bills nothing;
- raises the existing `EngineCapabilityError` for a `404` without that envelope, which is what an
  Engine without `/classify` answers, so an older Engine fails before any paid call. A `404` with
  the envelope is the classifier-not-found answer (E6) and keeps its code, except
  `result_unavailable`: the run finished and its result is gone, so it is the same
  `ExecutionError` as a failed artifact fetch;
- recommends a retry only after a confirmed refusal before sending (section 6, decision 8): a
  connect-phase failure, a `429` and a `503` with `Retry-After` (the Engine's runner-at-capacity and
  queue-unavailable answers, which state that nothing was queued; see section 8 for the publish
  case). Every other answer, including `500`, `502`, `504`, a bare `503` and url4's
  `x.admission_timeout`, which only an expression's `;t=` guard raises, and every transport
  failure after the request may have been sent, is not retryable, because the classification may
  have run and been billed. After a `303` the classification has run, so no failure to read its
  result is retryable, an Access login included. `EngineUnavailableError` and the other SDK calls
  do not change;
- refuses a model ID or text that cannot be encoded as UTF-8 before any request, without the text
  in the error, and turns a score that cannot become a float into `engine_contract_error`.

The result types are two frozen dataclasses: `Classification` (`model`, `contract`, `scores`) and
`LabelScore` (`label`, `score`). They live in a new public module `screamingface.classification`
and are re-exported from `screamingface`, as `FetchedMedia` is from `screamingface.media`. That
module is not in `PINNED_MODULES`; the top-level snapshot pins each type's constructor and fields
through the re-export, as it does for `FetchedMedia`. So `PINNED_MODULES` does not change and no
third protected test changes.

A classifier does not become a chat Model, and the helper is not a Router, a Recipe or a compiler
change.

## 5. Test plan

Every check uses fake upstreams, a fake Gateway and queue and worker substitutes. Nothing calls a
live key, a paid model or production.

- **Definitions.** A valid classifier target is accepted, alone and next to a chat target. Each
  incompatible `task` and `contract` pair is refused, both ways. A classifier with chat fields,
  a chat target with classifier fields, an unknown `task`, a duplicate alias across kinds, and a
  non-`bounded-score` value are each refused at their location, without the value in the message.
- **No cross-task call.** A chat call with a classifier ID and a classification call with a chat
  ID are both refused with no key read and no upstream I/O. `/v1/models`, admission and
  parameters never list a classifier.
- **Classifier-only provider.** Listed in `/v1/providers` for a granted account, absent for
  others; connectable; readiness `VALID` on a good fixture and not on a malformed one; a failed
  replacement keeps the previous key.
- **Inference.** A real route handler calls a fake classifier. It sees the exact path, bearer key
  and `{"inputs": ...}` body. Both envelopes decode. Ties come back in upstream order.
- **Refusals before I/O.** Extra body fields, an unknown ID, an ungranted ID, a chat ID, a
  missing key, and a model or input holding a lone surrogate each cause zero upstream requests.
- **Bad results.** Empty list, duplicate label, empty label, boolean, `NaN`, `Infinity`, a score
  outside `[0, 1]`, a two-item batch, a non-200 status and an oversized body with no length
  header each fail safely; the input and the key appear in no error or log line.
- **Isolation.** Two accounts and two endpoints under overlapping calls each reach only their own
  origin with only their own key.
- **Engine.** One `/classify` serves two targets, cold and warm, with no reconfiguration and no
  prior listing. The exact text and the caller identity reach the fake Gateway, with no
  Authorization header. A seed is refused with zero Gateway calls. The App answers `414` one byte
  past the limit and accepts the request at the limit. A collision at `/classify` fails
  composition. `/classify` stays in OpenAPI and metrics as one public path, and no classifier ID
  appears in either.
- **Capture and replay, through the real executor.** `Url4Executor` runs an expression calling
  `/classify` against a recording fake Gateway. Under a capture scope the Gateway sees only the
  frozen-copy open and seal, and no `POST /v1/classifications`; under a replay scope it sees no
  request. Both runs end with the refusal code. A direct `/classify` call with a frozen-copy
  header is refused by the App with no Gateway request.
- **Cost.** A dispatched classification reports exactly one usage record with no cost, after a
  success, a Gateway refusal or a contract failure alike; every refusal before dispatch reports
  none. Through the real executor, an expression with a priced chat call and a `/classify` call
  ends with an unpriced total, while the same run without the classification is priced.
- **Engine input checks.** A lone surrogate in the model or the input is `malformed_source` with
  no Gateway request. `$text`, `$item` and `$1` in a direct call's input reach the Gateway byte
  for byte. `check-publication` refuses a classifier target declared as an Engine model.
- **Wait bound.** With a non-default `sync_max_wait_s` of 60 seconds and a Gateway that never
  answers, a direct `/classify` call with a short `Prefer: wait` answers `504 timeout` at that wait,
  not at the server limit, and its run is stopped.
- **Access log.** A synthetic marker sent as a direct `/classify` call and nested inside an
  expression on `GET /?q=`, raw and percent-encoded, never appears in a formatted access line.
  The method, path and status still do. A non-access Engine log record is unchanged.
- **SDK.** Encoding round-trips `+`, `&`, quotes, newlines and non-ASCII text. The size check
  fires before any request. A `404` on `/classify` raises the capability error. The request
  carries `Prefer: wait=30` and a 45 second read timeout; a fake Engine with a limit of 10, 30 or
  60 seconds computes its bound from that header, and the bound is below the request's read
  timeout in each case. Each answer and transport failure of decision 8 maps to its retry
  recommendation. A lone surrogate is refused with no request and no text in the error, a score
  past the float range is `engine_contract_error`, `$` in the input stays literal, and an empty
  input is still sent. A `303` to a `Location` outside the signed artifact form, with dot
  segments, encoded ones, a scheme or a host, is not followed and no second request is sent; the
  Engine's own signed form is still fetched.
- **Gateway logs.** Records are captured by a handler on the `aigateway` logger, because the
  Gateway turns propagation off and `caplog` alone can pass on an empty capture. Each failure
  case asserts that its expected record is present, then that neither the key nor the input
  appears in any record.
- **Prior tests unchanged,** except the owner-approved changes in two files: in
  `test_definitions.py` the one value of section 6, decision 1, and the two type assertions of
  decision 1a; and the regenerated public surface snapshot of decision 4a.

## 6. Owner decisions (2026-10-30)

| # | Question | Decision |
|---|---|---|
| 1 | **One prior test case.** `test_unsupported_tasks_and_contracts_are_refused` (`apps/aigateway/tests/unit/remote_endpoint/test_definitions.py:354-366`) uses `"text-classification"` as its unsupported task. That task becomes supported, and a chat-shaped target with it is then refused at other locations. | **Approved.** That one value becomes `"embeddings"`. The test name, the location and the assertion stay, and the change is pinned in `.claude/test-change-approvals/OME-1794.json`. New tests cover the accepted classifier target, incompatible pairs and cross-task calls (section 5). |
| 1a | **Second case in the same file.** `targets` holds both kinds (G1), and `test_two_endpoints_become_ordered_definitions_with_canonical_targets` (`apps/aigateway/tests/unit/remote_endpoint/test_definitions.py:52-69`) reads `upstream_model`, which only a chat target has, so the type checker refuses it. | **Approved.** `targets` stays `tuple[ChatTarget \| ClassificationTarget, ...]`. Two `isinstance(..., ChatTarget)` assertions are added before the existing reads of `upstream_model`, with the `ChatTarget` import. Every prior assertion stays. Pinned in the same `OME-1794.json` entry. |
| 2 | **Classifier fixtures.** No actual classifier is chosen yet. | **Confirmed as a test contract.** Synthetic fixtures follow the Hugging Face text-classification response for both envelopes, `flat` and `single-batch`. They prove the code against that shape only, not compatibility with a real HF deployment, which stays unproven until Unit 4. |
| 3 | **Access-log redaction.** The design requires query contents out of access logs before sensitive input. Uvicorn logs the full query today, for chat `q=` too (Engine `cli.py:54-56` runs it with default logging). | **Every Engine access record,** as E10. Redacting `/classify` alone would leave text nested in `GET /?q=`. This covers Engine access logs only: ingress and proxy logging must be checked before sensitive input, and until then pilot input stays synthetic or public. |
| 4 | **SDK leaf.** | **Included,** as section 4.3, under its own `client-sf` leaf. |
| 4a | **SDK surface.** Any public export changes `packages/screamingface/tests/public_surface_snapshot.json`, a protected test file. | **`Client.classify` and `sf.classify`,** sync only, after the `fetch_media` precedent, plus the two result types of section 4.3. The snapshot is regenerated on the current base, which already holds main's `Mean`, `Judge` order, `Filter` judge and `Pick` output entries; those stay. The regenerated snapshot is pinned in `.claude/test-change-approvals/OME-1796.json`, with both blobs taken from that same base, and the change gets a `CHANGELOG.md` entry. |
| 5 | **PR shape.** | **One PR, three leaves under `OME-1306`:** `aigateway` (classification API, adapter, readiness), `screamingface-engine` (ingress, execution, access-log redaction), `client-sf` (the helper). |
| 6 | **Capture boundary.** A capture run opens its frozen copy at the Gateway before the expression and seals it after (`apps/screamingface-engine/src/screamingface_engine/runner/executor.py:1117`), so a refusal inside `/classify` cannot mean zero Gateway requests. | **No classification request and no upstream inference.** The existing open and seal stay, and the handler refuses before `POST /v1/classifications`. Replay and direct calls make no Gateway request. Checked through the real `Url4Executor` (E4, section 5). |
| 7 | **Cost of a mixed run** (review). Emitting no usage left a run with a priced chat call and a classification priced, with the classification left out. | **One record of unknown cost per dispatched classification,** as E8. A test proves the mixed run is unpriced, and a separate one that a refusal before dispatch reports nothing. No token counts are invented; the two required zeros are documented as not measured. |
| 8 | **SDK retry recommendation** (review). The Engine answers `502` both for permanent failures and for unknown transient ones, so the status alone cannot say whether retrying is safe. | **If the classification may have run, the SDK does not recommend retrying the whole call.** Only a confirmed refusal before sending is retryable (section 4.3). The SDK already never re-sends the call itself; this fixes the recommendation it gives. Classification-specific errors carry it; `EngineUnavailableError` and other SDK calls do not change. |
| 9 | **Empty input** (review). `""` reaches the classifier as a paid call. | **Allowed.** The contract takes a string, and a classifier may answer an empty text meaningfully. No trimming: spaces and newlines are part of the input. |
| 10 | **Review minors.** | **Fixed in this branch:** a lone surrogate is refused before I/O at all three layers, without replacing it and without the text in the error; `check-publication` refuses a classifier declared as an Engine model; the SDK turns a score past the float range into `engine_contract_error`; and section 8 records the queued run message and `$` in expressions. |
| 11 | **Second review** (2026-11-02). Three findings: a `303` to `/artifacts/../classify?q=...` passed the SDK's prefix check and httpx sent the classification again; a Gateway body of 10,000 nested arrays raised `RecursionError` and answered `500`; a score of `10**400` was said to escape the SDK as `OverflowError`. | **The first two are fixed in this branch:** the SDK follows only the exact signed artifact form (section 4.3), and the Gateway answers the malformed-body `400` (G6). **The third was already fixed** by decision 10, with its test since then; tests for a negative overflow and the integer scores `0` and `1` were added. |
| 12 | **Third review** (2026-11-02). Ten findings. SDK: an Access login on the artifact fetch answered `access_reauthenticated` marked retryable after the classification ran; the `admission_timeout` branch compared with a misspelled code no `/classify` call can reach; the Engine's `404 result_unavailable` after a run became `PlanningError`. Engine: percent-escapes that are not UTF-8 became U+FFFD and were classified; the access-log filter passes any record shape but uvicorn's; the caller's model ID reaches telemetry unbounded. Gateway: its own `503 provider_queue_timeout` logged at ERROR; a lone surrogate in an unknown field name answered `500`; no test pinned the grant before the alias. Engine and SDK: a publish-phase `503` keeps `Retry-After` though the run may be stored. | **Eight are fixed in this branch** (section 4.3, G6 and plan Phase R3); the access log gains a test through uvicorn's own protocols, and the filter itself is unchanged. **Not in this PR:** the publish-phase `503`, an Engine-wide behaviour pinned by earlier tests (section 8), and the model ID in telemetry. |

## 7. Rollout order

One PR keeps the contract and the joint checks together; deployment still goes in order. The
Gateway goes first, then the Engine, and the client call is used only once both serve it. An
older Engine answers `404` on `/classify`, which the helper turns into a capability error before
any paid call.

## 8. Residual risks

- **Unproven against a real service.** Fixtures prove the code against the HF response shape,
  not a deployed classifier.
- **Proxy logs unchecked.** Ingress and proxy access logs may still record the query. Pilot
  input stays synthetic or public until they are checked.
- **WebSocket lines keep their query.** uvicorn writes a WebSocket request target, query included,
  to `uvicorn.error`, not to the access logger, so E10 does not redact it. `/classify` and
  `GET /?q=` are plain HTTP, so their text is not affected.
- **Expression runs hide the new codes.** On `GET /?q=`, a code outside `ENGINE_ERROR_CODES` is
  reported as `internal_error` (Engine `rest/routes.py:88-127`). A `/classify` refusal inside an
  expression is still made before any classification request, but its caller sees that generic
  code. The direct mount, which the SDK helper uses, keeps the real code. Adding the new codes to
  that allowlist would change a pinned prior test
  (`apps/screamingface-engine/tests/unit/test_terminal_error_detail.py:336-349`) and is left out.
- **A refused capture run leaves a sealed copy.** It holds no classification entry, and a replay
  of it reaches the same refusal.
- **A cancelled run may still be charged.** A timeout stops the local run but cannot prove the
  remote service did not charge, as with chat.
- **A retry may double a charge.** A transport retry after a request that may have been sent can
  run the classifier twice. This is the existing chat rule. The SDK does not recommend a retry in
  that case (decision 8), but a caller can still retry.
- **A proxy `503` with `Retry-After` reads as admission.** The SDK cannot tell a fronting proxy's
  `503` with `Retry-After` from the Engine's own admission refusal, and marks both retryable.
  Proxies normally answer so without forwarding the request; this is an inference, not checked
  against the deployed ingress.
- **A queue-unavailable `503` may follow a stored run.** The Engine answers a JetStream publish
  failure with `503` and `Retry-After` and says nothing was queued
  (`apps/screamingface-engine/src/screamingface_engine/rest/routes.py:425-438`). A publish whose
  acknowledgement timed out may still have stored the message. A mount call names a new topic per
  request (`rest/mounts.py`), so a retry is a second run that `Nats-Msg-Id` deduplication does
  not catch, and the SDK marks that `503` retryable. `GET /?q=` reuses its token's topic, and the
  SDK reads a `409` after a re-sent start as admitted (`docs/spec/2026-09-28-sdk-run-isolation.md`).
  `stop(topic)` does not help: it writes no tombstone for a topic the App never saw scheduled.
  Closing this changes the Engine's shared mount answer and prior tests, so it is left out of
  this PR.
- **The input rests in the queued run.** Access logs are redacted, but the input is not absent
  from the system: a queued run carries the whole expression, the classification text included,
  as `URL4_CLOUD_EXPRESSION` in its JetStream run message
  (`apps/screamingface-engine/src/screamingface_engine/runner_queue.py:208`). This is one more
  reason pilot input stays synthetic or public.
- **`$` in an expression is literal.** Inside an expression, the `/classify` context is taken as
  written: `'{"model": ..., "input": "$text"}'` sends the four characters `$text` to a paid
  classifier, with no substitution and no error. An unquoted inline JSON context is reshaped by
  url4 and refused as `malformed_source`. A direct call through the SDK keeps `$` literal too.
- **No hosted readiness claim.** Like Unit 2, nothing here is hosted-ready until a real
  Linux NATS/JetStream check passes.

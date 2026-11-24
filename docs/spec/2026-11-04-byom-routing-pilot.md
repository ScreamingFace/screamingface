# BYOM routing pilot: one routed answer through the hosted Engine

Tickets, under epic `OME-1306`, one per landing: `OME-1822` (`screamingface-engine`),
`OME-1823` (`client-sf`), filed before Phase 1 (section 6, D5). Branch
`OME-1822-byom-routing-pilot` from origin/main `89e6acfeb`. Ledger:
`docs/work/2026-11-04-byom-routing-pilot.md`. Plan: `docs/plan/2026-11-04-byom-routing-pilot.md`.

Governing design: the Engine model-routing draft in `screamingface-design`
(`solutions/screamingface/product/engine/model-routing.md`, local draft of 2026-11-04). It owns
the routing boundary. This spec decides the names, the wire and the code that meet it. Where the
two differ, the draft wins and the difference is a finding to raise. The Unit 3 classification
contract (`docs/spec/2026-10-30-hosted-byom-unit3-classification.md`) is unchanged.

Engine paths are relative to `apps/screamingface-engine/src/screamingface_engine/`, SDK paths to
`packages/screamingface/src/screamingface/`, unless a path starts at the repo root.

## 1. Problem

Unit 3 returns a classifier's labels and scores (`/classify`). Nothing acts on them. A caller who
wants "the right model for this question" must classify, pick a label and call a chat model
themselves: two runs, two authorizations, and selection logic in every client.

## 2. Goal and non-goals

**Goal.** A caller sends a profile ID and one question to the Engine. One direct run, under one
identity and trace:

```text
SDK  GET /route-answer?q=({"profile": ..., "input": ...})!route-answer
  -> preflight: classifier and every branch visible and connected (metadata only)
  -> Gateway POST /v1/classifications -> model_router_v1 wrapper -> Laya
  -> validate scores, pick the unique highest label
  -> Gateway POST /v1/chat/completions -> the one model bound to that label, same question
  -> routed-answer-v1: the answer, the selected label and model, the unchanged scores
```

**Non-goals.** A control answer, synthesizer, Fusion, parallel branches, a fallback branch, a
confidence threshold, a routing-result cache, streaming, tools, web search, answer seeds,
capture or replay, an async SDK call, `sf.route_answer`, a Router Recipe, UI, Taxonomy
accounting, hot reload, a second profile registry, and any change to `/classify` or chat.

## 3. Contract

### 3.1 Routing profile (Engine world file)

Profiles live in the declared world file the App and every child already read
(`job_env.RUNNER_CONFIG`, read once by `read_world_file`). One file means one parsed revision for
the App, a cold run and a warm child, and `/healthz` already reports that file's digest.

```toml
[routing.profiles.expert_router_v1]
classifier = "byom_<hex>/model_router_v1"
classifier_contract = "classification-scores-v1"
policy = "unique-argmax-v1"

[routing.profiles.expert_router_v1.branches.general]
model = "byom_<hex>/general"
max_tokens = 1024

[routing.profiles.expert_router_v1.branches.code]
model = "byom_<hex>/code"
max_tokens = 1024

[routing.profiles.expert_router_v1.branches.math]
model = "byom_<hex>/math"
max_tokens = 1024
```

Composition rules, all local and structural, each a `WorldConfigError` that fails startup:

- R1. `[routing]` requires `[aigateway]`; its only key is `profiles`, a non-empty table.
- R2. A profile ID matches `^[a-z][a-z0-9_]{0,63}$`. A profile has exactly the keys
  `classifier`, `classifier_contract`, `policy`, `branches`.
- R3. `classifier` is `<provider>/<alias>`, both parts non-empty. It is not checked against any
  Engine list: the Gateway owns classifiers (Unit 3).
- R4. `classifier_contract` is `classification-scores-v1`; `policy` is `unique-argmax-v1`.
  These are the only values this slice supports.
- R5. `branches` has exactly the labels `general`, `code` and `math`. That set IS the exact set
  the classifier must return. Other label sets are a later extension.
- R6. A branch has exactly `model` and `max_tokens`. `model` is the `id` of any declared
  `[[aigateway.models]]` route of the world, public or private (`public_schema` does not
  matter), whose Gateway ID is `<provider>/<alias>`. Two labels may share a model.
- R7. `max_tokens` is an integer in `[1, 32768]`, not a boolean. It is the one generation
  parameter: `openai-chat-basic-v1` carries no other (`plugins/remote_endpoint/plugin.py:39`
  in `apps/aigateway/src/aigateway/`), so no other is accepted here.

No secret, origin, path or header belongs here. The profile `revision` is `sha256:` plus the hex
digest of the canonical JSON of the parsed profile (ID, classifier, contract, policy, branches;
sorted keys, compact separators). It is computed identically wherever the file is parsed.

A routing profile is not the retired `X-Profile` credential selector. The mount still refuses a
stated `X-Profile` header first (OME-1381); nothing here reads it.

### 3.2 Engine ingress

`GET /route-answer?q=(<context>)!route-answer`, served like `/classify`: a direct mount run on
the worker pool, the verified identity required, `X-Profile` and the frozen-copy headers refused,
8 KiB on the raw path and query (`414 uri_too_long`), and a percent-escape that does not decode
as UTF-8 refused at the App before any run (`400 malformed_source`).

`<context>` is exactly the JSON object `{"profile": <string>, "input": <string>}`: no other key,
no repeated key, no url4 parameter before `q`, both values UTF-8 encodable. The input must be
non-empty and must be a plain prompt to the chat path: the two readers the chat route applies
(`parse_candidate_input` and `fusion_picture_messages`) must both return no messages and raise
nothing. Otherwise the chat route would send something other than the caller's text.

The route is registered on every world that declares `[aigateway]`, before the direct-mount
snapshot, so an Engine's capability does not depend on its profiles. A declared model whose route
is `/route-answer` fails composition, as `/classify` does.

### 3.3 Execution order

One handler, one direct run. Each step runs only if the previous one succeeded.

1. **Mode.** An answer seed, a capture run or a replay run: `routing_unsupported`.
2. **Envelope and input** (3.2): `malformed_source`.
3. **Profile.** An ID this world does not declare: `routing_profile_not_found`.
4. **Preflight**, sequential, with the run's identity headers, no inference, no key check:
   `GET /v1/classifiers/details?model=<classifier>`, then
   `GET /v1/model-parameters?model=<branch model>` per branch in file order. Each read stops
   the preflight at once on these answers:
   - a transport failure, `429` or `5xx`: `routing_preflight_unavailable`, the one transient
     preflight outcome;
   - `400` or `404`, the Gateway's answer for an ungranted or absent target:
     `routing_profile_not_found`;
   - `409`, or `401` with the code `auth_required`: the target is visible, its Connection is
     not usable; noted, and the reads go on;
   - any other status, a redirect, a body that is not the published document, or a document for
     another model ID: `routing_preflight_failed`.

   Only when all four targets are visible are the noted and document checks decided, so a caller
   who cannot see every target learns nothing about the ones they can:
   - a noted Connection, or `execution_access` other than `configured`:
     `routing_connection_missing`;
   - a classifier whose `result_contract` is not the profile's, or a branch whose
     `parameters.max_tokens` is not `gateway.status == "enabled"` or whose `schema` does not
     admit the bound value (`type` integer, `minimum`, `maximum` when present):
     `routing_profile_mismatch`. A configuration error is found here, before Laya is called.
5. **Classification** through Unit 3's `ClassificationEndpoint`, unchanged: one Gateway call and
   its one unknown-cost record. `classifier_not_found` becomes `routing_profile_not_found`; every
   other error is relayed under the policy of 3.5 (6.1, C9).
6. **Scores.** The label set must equal the profile's exactly: else `routing_invalid_scores`.
   Unit 3 already refused, in step 5, a result for another model or contract, duplicate labels,
   booleans and scores outside `[0, 1]`, each relayed as `aigateway_bad_response` (6.1, C1).
7. **Selection** (`unique-argmax-v1`): the label with the highest score. If that score is held by
   more than one label, exactly as decoded: `routing_ambiguous`, and no chat call.
8. **Branch.** A nested dispatch on the same world node, so the call is the ordinary chat route
   with its scope, cache policy, limits, observation and refusals:
   `/<model route>?max_tokens=<n>&web_search=false&q=(<input>)`, with no
   intent, which the chat route sends as one user message holding the input. An ungranted branch
   answers url4's undeclared route there; it becomes `routing_profile_not_found`, so its path is
   never shown. Every other error is relayed under the policy of 3.5 (6.1, C9): a null message
   content is already `aigateway_bad_response` or `model_empty_content`, never an empty answer.
9. **Result** (3.4).

No step is retried by this handler and no other branch is ever tried. Cancellation of the run
cancels the step in flight; a cancelled step 5 never reaches step 8. The total bound is the mount
bound, `min(Prefer wait, sync_max_wait_s)`: at it the App stops the run and answers `504`. Each
Gateway call keeps its own configured timeout, which the stop cuts short.

### 3.4 Result `routed-answer-v1`

`200` with the handler's body, or `303` to a signed artifact over 1 MiB, as every mount:

```json
{
  "object": "routed_answer",
  "contract": "routed-answer-v1",
  "profile": "expert_router_v1",
  "revision": "sha256:<64 hex>",
  "policy": "unique-argmax-v1",
  "classification": {
    "model": "byom_<hex>/model_router_v1",
    "contract": "classification-scores-v1",
    "scores": [{"label": "general", "score": 0.07}, {"label": "code", "score": 0.91},
               {"label": "math", "score": 0.02}]
  },
  "selected": {"label": "code", "model": "byom_<hex>/code"},
  "answer": "<the selected model's message content>"
}
```

Scores keep the classifier's order and values. `selected.model` is the Gateway model ID of the
branch that answered. Nothing about unselected branches appears.

### 3.5 Errors

url4's envelope `{"error": {"code", "message"}}`. "Ran" names the paid calls that may have
happened before the error.

| Code | Status | When | Ran |
|---|---|---|---|
| `malformed_source` | 400 | envelope, escapes, empty or non-plain input (3.2) | nothing |
| `uri_too_long` | 414 | path and query over 8 KiB | nothing |
| `routing_unsupported` | 400 | answer seed, capture, replay | nothing |
| `routing_profile_not_found` | 404 | unknown profile, or a target not visible to the caller | nothing, or the classifier when access changed after preflight |
| `routing_connection_missing` | 409 | a target has no usable Connection | nothing |
| `routing_preflight_unavailable` | 502 | metadata read failed in transit, `429` or `5xx` | nothing |
| `routing_preflight_failed` | 502 | metadata refused otherwise, unreadable, or not the published document | nothing |
| `routing_profile_mismatch` | 502 | the profile does not fit a target's published contract | nothing |
| `routing_invalid_scores` | 502 | a label set other than the profile's | classifier |
| `routing_ambiguous` | 422 | tied highest score | classifier |
| relayed classifier codes | 502; `timeout` 504 | e.g. `aigateway_bad_response`, also for a result naming another model or contract; `timeout` | classifier |
| relayed branch codes | 502; `timeout` 504 | e.g. `aigateway_http_429`, `model_token_cap` | classifier and branch |

The messages name no model ID, origin or path. Every relayed classifier or branch failure
carries one fixed Engine message, `the routed answer failed after its classifier or branch call
was sent`; no upstream text crosses, in the envelope, the run's events or the runner's log (6.1,
C9). Unknown and ungranted profiles answer the same `404` with the same message.

Every routing code is the Engine's own. A Gateway or proxy body that names one keeps the
connector's `aigateway_http_<status>` code, so a relayed failure after a classifier or branch
call never claims that nothing ran (6.1, C6). No other code a Gateway or proxy body names is
kept either: every Gateway refusal of a classifier or branch call takes `aigateway_http_<status>`,
with the status and permanence kept, so it neither leaks, nor reads as a refusal of the request,
nor borrows an Engine diagnosis such as `model_token_cap` (6.1, C8, C9). The Engine's own code for
a sent call is not a refusal and is kept: `aigateway_bad_response`, `model_token_cap` from a
`length` answer, `timeout`.

### 3.6 SDK

```python
result = client.route_answer("expert_router_v1", question)
result.answer, result.selected_label, result.selected_model, result.scores
```

`Client.route_answer(profile: str, input: str) -> RoutedAnswer`, sync only. `RoutedAnswer` is a
frozen dataclass exported as `sf.RoutedAnswer`, fields in this order: `profile`, `revision`,
`policy`, `contract`, `classifier`, `scores` (`tuple[LabelScore, ...]`, classifier order),
`selected_label`, `selected_model`, `answer`. The decoder accepts a result only when all of
these hold, and raises `ExecutionError(engine_contract_error)` otherwise:

- `object` is `routed_answer`, `contract` is `routed-answer-v1`, `policy` is
  `unique-argmax-v1`, and `classification.contract` is `classification-scores-v1`;
- `profile` is the profile the caller asked for;
- `revision` matches `sha256:` followed by 64 lowercase hex digits;
- `classification.model`, `selected.model` and `answer` are strings, the two models non-empty;
- `scores` is a non-empty list of unique non-empty labels, each with a finite, non-boolean
  number in `[0, 1]`;
- `selected.label` holds the highest score, and no other label holds it.

Transport, as `classify`, through the same moved helpers: one GET never marked safe to replay,
a 2 MiB read limit, and a `303` followed only to the Engine's exact signed artifact path, fetched
once more only after an Access login. The waits differ: `route_answer` states `Prefer: wait=60`
(the Engine caps it at `sync_max_wait_s`) and reads for 75 s; `classify` keeps its 30 s wait,
45 s read, messages, codes and retry rules unchanged. Before any
request: `TypeError` for a non-`str` argument, `PlanningError(malformed_source)` for text UTF-8
cannot encode, `PlanningError(uri_too_long)` over 8 KiB, all naming the field, never the value.

| Answer | SDK error | Retryable |
|---|---|---|
| connect-phase failure | `EngineUnavailableError` | yes |
| failure after sending | `ExecutionError(routed_answer_outcome_unknown)` | no |
| plain `404` without the envelope | `EngineCapabilityError` | no |
| `401`, `403` | `AuthenticationError` | no |
| `routing_preflight_unavailable` | `ExecutionError` | yes, nothing ran |
| `routing_preflight_failed`, `routing_profile_mismatch` | `ExecutionError` | no, nothing ran |
| `400`, `404`, `409`, `414` | `PlanningError` with the code | no |
| `404 routing_profile_not_found` | `PlanningError` with the rerun and billing hint (6.1, C10) | no |
| HTTP `429` from the ingress, before any run | `ExecutionError` | yes |
| `503`, with or without `Retry-After` | `ExecutionError` | no |
| `result_unavailable`, artifact failure | `ExecutionError(result_unavailable)` | no |
| any other status | `ExecutionError` with the code | no |

WHY `503` is not retryable here, unlike `classify`: a queue-publish `503` may follow a run the
broker stored when its acknowledgement was lost, and repeating a routed answer can bill two
models. A `429` inside a run, from the classifier or the branch, reaches the caller as a relayed
code such as `aigateway_http_429` on a `502`, after the run started, and is not retryable either.
The three retryable rows are the only ones where nothing ran. Every non-retryable error after
sending says that asking again may run and bill the classifier, and the selected model, again.

### 3.7 Wrapper profile `model_router_v1`

A loopback compatibility wrapper registered as a Gateway `text-classification` target with
contract `hf-text-classification-v1`. It accepts exactly `{"inputs": <string>}` with a bearer
key checked before any I/O, and sends Laya:

```json
{
  "state": {"body": "<inputs, unchanged>"},
  "questions": {
    "expert": {
      "type": "choice",
      "instructions": "Which expert role should answer the request in `body`?",
      "criteria": {
        "general": "General questions, explanations, writing, summarization and everyday requests that are not specifically programming or mathematics.",
        "code": "Programming, code generation, debugging, refactoring and software engineering.",
        "math": "Mathematics, numerical calculations, equations and mathematical reasoning rather than programming requests."
      }
    }
  }
}
```

It returns `[{"label", "score"}]` from `answers.expert.probabilities` only, in Laya's order,
values unchanged, after checking `answers.expert.type == "choice"`, the exact three labels, and
finite non-boolean scores in `[0, 1]`. Never `confidence` or `answer_confidence`, no sorting,
normalizing or filling. Reported truncation of state or question is a `502`. Until Laya's
truncation report is qualified, the wrapper refuses an input over a configured byte bound
(`413`), set during qualification. Fixed upstream, TLS verified, no redirects, no cookies,
bounded reads, a deadline. `incident_category_v1` is untouched. Changing this wording later
needs a new alias and a new Engine profile ID.

## 4. Design

### 4.1 Engine

- `world/routing_config.py`: `RoutingProfile`, `RoutingBranch`, `parse_routing(raw, section)`.
  `config.py` (840 lines) gains only the `routing` key and field, and calls it.
- `world/routing.py`: `RoutedAnswerEndpoint(http_client, cfg, profiles, branch)` with steps 1 to
  9, the preflight reads on the connector's client and `_headers(scope)`, its own
  `ClassificationEndpoint`, and the routing status table. It imports no url4.
- `world/gateway_endpoints.py`: `install_gateway_endpoints` registers `/classify` and
  `/route-answer` on the node, with `branch` as a closure over
  `node.fetch(encode_subrequest(...), relative=True)` that turns `endpoint_not_found` into
  `routing_profile_not_found`, and the shared `RunnerRequestError` to `ResolutionError`
  translation. `world/factory.py` calls it (6.1, C3). On `/route-answer` only, `_relayed` gives
  every classifier or branch failure the fixed message of 3.5 and every Gateway refusal the code
  `aigateway_http_<status>`, keeping the permanence; a relayed failure never becomes the
  hidden-branch refusal (6.1, C8, C9).
- `error_text.py`: `ROUTING_CODES` joins `ENGINE_RESERVED_CODES`, so
  `connector._raise_for_status` never adopts a routing code from an upstream body (6.1, C6).
- `rest/mounts.py`: one table of the direct routes that refuse an undecodable escape, each with
  its own message, over `classification.undecodable_query`, which replaces `refuses_query`.
- `world/serving.py`: `**ROUTING_STATUS` in the mount status table.

### 4.2 SDK

- `_engine/direct_get.py`: `EngineGet`, the request encoding with its UTF-8 and 8 KiB checks,
  the read, the bounded body, the artifact path check and fetch, the url4 envelope reader and
  the never-sent set, moved from `_engine/classification.py` with a wording parameter
  (`DirectCall`) so `classify` keeps its exact messages and codes (6.1, C5).
- `_engine/routed_answer.py`: path, checks, error table 3.6, decoder.
- `routing.py`: `RoutedAnswer`. `client.py` and `__init__.py`: the method and the export.

### 4.3 Outside Git

The wrapper (3.7) with its offline tests, rebuilt from the 2026-11-03 local prototype, and the
Phase 4 loopback harness: a real Gateway with an isolated store and fake upstreams, the Engine in
local mode and the SDK, with every upstream call recorded by destination and key match. They are
pilot tooling, not the proof of routing: the Engine and SDK tests in the repository and CI are.
The ledger records the bundle's location, the commands that start it and their results.

## 5. Acceptance (deterministic)

1. Each of the three labels selects its branch; the other branches receive no call.
2. The classifier and the selected branch receive the input byte for byte; the branch gets one
   user message, the profile's `max_tokens` and nothing else, and no tools.
3. Every Gateway call carries the caller's identity; no other account's key is used.
4. Preflight, startup and the mount listing call no model. A `max_tokens` the branch's published
   contract does not admit is refused before the classifier is called.
5. Every row of 3.5 is produced by a test, with the calls made before it counted.
6. A tie, an extra, missing or renamed label, and a wrong model or contract never reach a branch.
7. A run cancelled during classification never calls a branch.
8. The run total stays unpriced with a priced branch, while the branch's answer alone is
   priced. The run is one span, so the classification and the branch share its one `self` frame:
   it is unpriced and its token counts are the branch's own (6.1, C2).
9. The SDK method drives one GET and decodes the result, every error row and the artifact path.
10. `classify`, chat and their prior tests are unchanged and green; no profile ID appears in the
    OpenAPI document or a metric label.

## 6. Owner decisions (2026-11-04)

Approved with edits; the edits are applied above.

- D1. Names as pinned: `/route-answer`, intent `route-answer`, `routed-answer-v1`,
  `unique-argmax-v1`, `Client.route_answer`, `RoutedAnswer`, the codes of 3.5.
- D2. `Client.route_answer` only; no `sf.route_answer` and no async method in this slice.
- D3. `503` is not retryable for `route_answer`, even with `Retry-After`. Retryable only: a
  connect-phase failure, an ingress `429` before any run, and `routing_preflight_unavailable`.
  Other preflight failures are told apart by cause and are not retryable (3.3, 3.6).
- D4. The wrapper and the loopback harness stay outside Git (4.3); the deterministic Engine and
  SDK tests stay in the repository and CI.
- D5. Two leaves under `OME-1306`, `screamingface-engine` and `client-sf`, filed before Phase 1;
  the branch is renamed to the Engine leaf's `OME-N-<desc>` before the approval manifest.
- D6. The SDK transport moves to `_engine/direct_get.py` (4.2) as a narrow refactor: `classify`
  keeps its messages, codes, retry rules and 30 s and 45 s timeouts.
- D7. Edits: `max_tokens` is the only generation parameter (R7); preflight checks it against
  each branch's published contract (3.3 step 4); exactly `general`, `code`, `math` (R5); the
  stricter SDK decoder (3.6).

### 6.1 Corrections found in implementation (2026-11-04)

Each keeps the approved behavior; only the wording or the file layout changes.

- C1. A classification result for another model or contract never reaches routing: Unit 3
  refuses it as `aigateway_bad_response` (3.3 step 6, 3.5). Answering `routing_invalid_scores`
  instead would need a change to Unit 3, which this slice keeps unchanged.
- C2. A direct run has one span, so acceptance 8 is about the run total and that one frame, not
  about two frames (5).
- C3. `world/factory.py` reached 474 lines. `_install_classification`, `_install_routing` and
  `_register` move unchanged to the new `world/gateway_endpoints.py`, and `factory.py` is 406
  lines. The new module imports url4, so `tests/unit/test_url4_executor.py` gains exactly one
  allowlist entry; every other entry and assertion is unchanged. Approved in chat on
  2026-11-04, approved again on main's base blobs on 2026-11-23, and pinned in
  `.claude/test-change-approvals/OME-1822.json`.
- C4. R6 names any declared model route of the world, public or private.
- C5. The SDK move (4.2) also takes the request encoding and the stage-2 call, which differ
  between `classify` and `route_answer` only in wording. `classify`'s refusal table and decoder
  stay in `_engine/classification.py`; `tests/test_classify.py` is unchanged and green.
- C6 (review). A Gateway or proxy body could carry a routing code, such as
  `{"detail": {"code": "routing_preflight_unavailable"}}`, through the classifier or branch
  call, and the SDK then read a failure after one or both POSTs as retryable. The routing
  codes now join the reserved set that `connector._raise_for_status` already keeps from
  upstream bodies (OME-941), and such a failure answers `aigateway_http_<status>`. The
  preflight's own `routing_preflight_unavailable` is unchanged and stays retryable. The SDK is
  unchanged.
- C7 (review). A metadata body nested past the JSON reader's depth raised `RecursionError`,
  which ended the run as `500 internal_error`. Both metadata readers now treat it as an
  unreadable body: `502 routing_preflight_failed`, with no POST.
- C8 (review). After the classifier or branch call, a relayed code with a status of its own
  reached the caller as a refusal: `classifier_not_found` as `404`, `malformed_source` as `400`,
  `identity_access_denied` as `403`, and at the branch `endpoint_not_found` became the
  hidden-branch `routing_profile_not_found`. The SDK then raised a refusal with no rerun hint,
  though a model may have run. On `/route-answer`, a relayed Gateway answer now keeps its code
  only when the mount answers that code as a Gateway failure, and otherwise takes
  `aigateway_http_<status>`; the branch never hides one. The Engine's own refusals are unchanged:
  malformed input, an unknown profile, an ungranted classifier or branch. `/classify`, Unit 3's
  codes and url4's are unchanged, and the reserved set does not grow. The SDK is unchanged.
  C9 replaces its rule for a relayed code, and C10 adds the SDK hint.
- C9 (review, 2026-11-23). A relayed classifier or branch failure carried the upstream text
  into the public envelope, the run's events and the runner's log, and C8 kept any code the
  mount answers as a Gateway failure. A body with `Authorization: Bearer ...`, a path, an origin
  or a private model ID came back verbatim, and so did a `detail.code` such as
  `/private/origin`. A screen of the message is not enough: a private model ID can read like a
  plain word. On `/route-answer` the relay now rewrites every classifier or branch failure
  before it becomes the run's terminal error: the fixed message of 3.5, every Gateway refusal's
  code replaced by `aigateway_http_<status>`, the permanence kept. A body naming
  `model_token_cap` no longer passes for the Engine's diagnosis of a `length` answer. The
  connector's own model-call log line and its observation read the lifted code inside the branch
  call, before the relay; closing them changes every model call and is a separate unit this
  pilot depends on (9). `/classify`, the chat path and the connector are unchanged here.
- C10 (review, 2026-11-23). An unknown profile and an ungranted classifier or branch answer the
  same `404 routing_profile_not_found`, and the second can come after the classifier ran and
  billed. The SDK cannot tell them apart without the 404 leaking which, so every
  `routing_profile_not_found` carries the rerun and billing hint (3.6).

## 7. Live inputs (pending, operator)

| Input | Needed |
|---|---|
| General model | Confirm `qwen3.8-27b`, its service and Gateway target |
| Code model, math model | Model ID, endpoint origin, chat path, auth, revision |
| Every chat service | Context and output limits, rate limits, `max_tokens` ceiling |
| Credential boundary | Which targets share origin, key and grants |
| Laya | Version, choice schema, token limits, truncation report, endpoint |
| Engine | `sync_max_wait_s` for the pilot (default 30 s) |
| Test window | Endpoints, accounts, request and output bounds, readiness calls, spend ceiling |

No live call, readiness call or key attach runs before these inputs and an approved window.

## 8. Rollout and rollback

Engine first: the route exists on every world, and with no `[routing]` table every profile is
`routing_profile_not_found`. Then the profile, then an SDK release that calls it. An older Engine
answers a plain `404`, which the SDK reports as `EngineCapabilityError` before any spend.
Rollback: stop routed submissions, drain, remove the profile. Chat, `/classify`, Connections and
grants are untouched by both directions.

## 9. Residual risks

- Laya's truncation report is not yet known; the wrapper's byte bound is the interim guard.
- Access can change between preflight and a call; the Gateway still authorizes each call.
- A transient preflight failure shows that the profile ID exists, though not what it binds.
  Profile IDs are not listed anywhere and carry no private value.
- A lost publish acknowledgement can leave a stored run behind a `503`; the SDK does not retry.
- Physical transport attempts are those of the existing connector; this slice adds none.
- `/classify` and the chat mounts still answer with the Gateway's own message, which the
  Gateway sanitizes (OME-1136); only `/route-answer` replaces it with a fixed message (C9).
- Until the connector unit (`gateway-code-provenance`) lands, the connector's model-call log line
  and observation carry whatever `detail.code` a Gateway or proxy body names, including on a
  routed answer's branch call. The pilot claims no log closure for that line, and it does not
  merge before that unit lands, or before the security owner explicitly accepts this risk
  (owner review, 2026-11-23).
- Local in-process evidence does not establish hosted Linux, NATS and JetStream execution.

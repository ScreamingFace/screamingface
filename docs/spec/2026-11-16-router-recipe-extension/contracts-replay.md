# Contracts: classification input, physical attempts and replay

Base `31c1158e8`. Path conventions, design citations and the strict-record rule are those of
[contracts.md](contracts.md).

## C7 — Gateway classification input, metadata and upstream attempts (Unit 5.1)

### Structured-choice input

`POST /v1/classifications` keeps exactly two body fields (`routes/classifications.py:35`):

```json
{"model": "<id>", "input": "text"}
{"model": "<id>", "input": {"contract": "classification-choice-input-v1", "text": "...",
  "instructions": "...", "options": [{"label": "general", "description": "..."}]}}
```

- A string `input` keeps today's scalar path, request and response body, byte for byte.
- An object `input` is valid only for a target whose declared contract is `systemone-choice-v1`.
  A scalar-only target refuses it, and a choice-only target refuses a string, with HTTP 400
  `unsupported_input`, before reading a key or any upstream I/O. Unknown keys are refused, never dropped.
- The SystemOne codec is a new module beside `plugins/remote_endpoint/classification.py`, selected by
  the target's contract in `plugin.classify` (`plugins/remote_endpoint/plugin.py:148-158`). It builds
  the native body with one `choice` question whose criteria follow `options` order, without
  `sort_keys`, and keeps the upstream model binding in the target, never in the request.
- It projects `answers.<question>.probabilities` to `classification-scores-v1` in returned order,
  without recalculation. Malformed, empty, duplicate, non-finite, boolean or out-of-range values, a
  wrong answer type or question identity fail as `provider_error`. A well-formed label outside the
  options is returned; coverage and unknown labels are Engine policy.
- Readiness uses the target's declared input with a bounded synthetic question; catalog, preflight
  and startup make no inference. Grants, request-local keys, fixed origins, no redirects or cookies,
  bounded I/O and no fallback stay as today.

#### Input rules and refusal order

An object `input` has exactly the keys `contract`, `text`, `instructions` and `options`. `contract` is
`classification-choice-input-v1`; `text` and `instructions` are strings, `instructions` nonempty;
`options` is a nonempty list of objects with exactly `label` and `description`, both strings,
`description` nonempty. A label is nonempty, has no control character and appears once in the list.
Every string is valid Unicode, as for the scalar input (`routes/classifications.py:120-129`). Any
other shape, an unknown key included, is HTTP 400 `invalid_request`, and the refusal names no caller
value.

The route keeps the Unit 3 order (`routes/classifications.py:5-8`): the body and input shape before
any provider lookup; then the provider, grant and classifier; then the target's input contract
(`unsupported_input`); then its limits, when the target declares them; then the credential and
dispatch. Every refusal uses the Gateway's `HTTPException` wire, the fields inside `detail`. A request
over a limit is HTTP 400:

```json
{"detail": {"code": "classifier_limit_exceeded", "limit": "max_text_chars", "message": "..."}}
```

`limit` names the first exceeded key in the order `max_text_chars`, `max_options`, `max_label_bytes`,
`max_description_chars`, `max_instructions_chars`, and the refusal names no caller value.

#### Native request

```json
{"model": "<upstream_model>", "state": {"body": "<text>"},
 "questions": {"choice": {"type": "choice", "instructions": "<instructions>",
                          "criteria": {"<label 1>": "<description 1>", "<label 2>": "<description 2>"}}}}
```

- The question ID is the fixed `choice`, and a request asks one question. Another ID is another
  contract version.
- `state` is the object `{"body": text}`, the shape of the design's example and of the pilot wrapper
  (`classification-capabilities.md:136-146`, `engine/model-routing.md:56-59`).
- `model` is sent only when the target configures `upstream_model`. Jev requires it; Laya 0.4.21 may
  omit it or name a Laya checkpoint (`classification-capabilities.md:132-133`, `:149-153`).
- Nothing else is sent: no Laya runtime control (`task`, `lang`, `lang_guess`, `max_len`,
  `head_max_len`, `min_confidence`), no Jev `assets` and no `TypeSafe-Danger-Zone-*` header. This
  common subset lets one codec serve both (`classification-capabilities.md:93-94`); a field only one
  of them takes needs another contract version.

#### Native response

- The transport bounds stay: HTTP 200, a JSON media type, identity encoding, at most 1,000,000 bytes
  and strict finite JSON (`plugins/remote_endpoint/transport.py:30`, `:148-154`, `:176-188`;
  `completion.py:42-54`). The codec also refuses a repeated key in any object, which `strict_json`
  alone would collapse to the last value.
- The body is an object whose `answers` is an object with the one key `choice`. That answer has `type`
  `"choice"` and `probabilities`, an object of 1 to `max_labels` entries. Each key is a label under the
  input's label rule and at most `max_label_bytes` UTF-8 bytes; each value is a number in `0..1`, not a
  boolean. Native answers key probabilities by label, so the projection keeps the object's key order
  (`classification-capabilities.md:155`). The sum is not checked: Laya rounds each value to four
  decimals without renormalizing.
- A non-null `error`, on the body or on the `choice` answer, fails the response even beside valid
  probabilities: a classifier that reports a failure gives no scores a Router may select by. An
  `error` of `null` is no error, as for a chat completion (`completion.py:90`, `:112`).
- `usage` is optional. When present it is an object, and the response fails when it reports lost
  input: `truncated` true, `state_tokens_dropped` above `0`, a nonempty `truncated_questions`, or an
  `options` key, Laya's report of colliding option spans (`classification-capabilities.md:170-173`).
  `truncated` that is not a boolean, `state_tokens_dropped` that is not a nonnegative integer and
  `truncated_questions` that is not a list fail as well.
- Other fields (`model`, `routing`, and the answer's `choice`, `confidence`, `answer_confidence` and
  `action`) are neither checked nor projected. Native usage reaches no evidence contract in this Unit
  (`classification-capabilities.md:181-182`).
- Every failure above, and every upstream refusal (Laya answers 413 over its own size limits and 422
  for a question it cannot take), is HTTP 502 `provider_error` with no upstream body
  (`transport.py:126-137`); only 429 and 503 keep their status for the overload retry.

### Catalog metadata

`ClassifierEntry` (`core/plugin_base/_ports.py:49-59`) and the `/v1/classifiers` and
`/v1/classifiers/details` rows gain `input_contracts` and `limits`:

```text
input_contracts = ["text"] | ["choice"] | ["text", "choice"]
limits          = TextLimits | ChoiceLimits | null
                  ChoiceLimits iff "choice" is in input_contracts; null only with ["text"]
TextLimits      = {"contract": "classifier-limits-v1", "max_labels": int, "max_label_bytes": int,
                   "max_text_chars": int}
ChoiceLimits    = {"contract": "classifier-limits-v1", "max_labels": int, "max_label_bytes": int,
                   "max_text_chars": int, "max_options": int, "max_description_chars": int,
                   "max_instructions_chars": int}
```

| Key | Unit | Meaning |
|---|---|---|
| `max_labels` | count | Labels a response may return; a longer response fails `provider_error` |
| `max_label_bytes` | UTF-8 bytes | Length of one returned label, and of one option label |
| `max_text_chars` | Unicode code points | Length of the question text, scalar or choice |
| `max_options` | count | Options in one choice input |
| `max_description_chars` | Unicode code points | Length of one option description |
| `max_instructions_chars` | Unicode code points | Length of the instructions |

Every value is a JSON integer in `1..2147483647`, never a boolean or a float. The values come from
the target config below, and the Gateway enforces exactly them: a request over a target limit is
refused with HTTP 400 `classifier_limit_exceeded` before upstream I/O, and a response over one fails
`provider_error`. `limits: null` means the target declares no limits. Direct scalar classification
then works as today, with no new check, while ADMIT and the SDK preflight refuse a Router that needs
that classifier (C17); for Router use, the operator qualifies the target and writes its limits.
`max_text_chars` is the target's own bound: Unit 6 makes a Router's effective question bound the
smaller of it and the measured Router question or carrier bound (C16). Trained vocabulary metadata
stays a Unit 8 option.

#### Target config

Schema version 1 gains these keys additively; a document without them parses as today.

```toml
[[endpoints.targets]]
alias = "router"
task = "text-classification"
contract = "systemone-choice-v1"
request_path = "/v1/systemone"
upstream_model = "<pinned provider model>"   # optional; sent as `model`

[endpoints.targets.limits]
max_labels = 32
max_label_bytes = 64
max_text_chars = 20000
max_options = 32
max_description_chars = 1024
max_instructions_chars = 4096
```

- A `systemone-choice-v1` target takes `alias`, `task`, `contract`, `request_path`, an optional
  `upstream_model` under the chat rule (1-256 printable ASCII characters without spaces,
  `plugins/remote_endpoint/definitions.py:49`, `:146-151`) and a required `limits` table of all six
  keys. It takes no `response_envelope` or `score_semantics`.
- An `hf-text-classification-v1` target gains an optional `limits` table of exactly the three text
  keys, each in `1..2147483647`. Without it the row's `limits` is `null`, and a string input keeps
  today's acceptance under the request body cap and the response byte cap.
- A `systemone-choice-v1` target's values hold these ranges:

  ```text
  1           <= max_options            <= 32
  max_options <= max_labels             <= 32
  1           <= max_label_bytes        <= 64
  1           <= max_description_chars  <= 1024
  1           <= max_instructions_chars <= 4096
  1           <= max_text_chars         <= 2147483647
  ```

  The first five follow the C16 rows for candidates, labels, descriptions and instructions.
- Every value is a TOML integer. A breach fails startup with the location and the rule, never the
  value (`definitions.py:7-8`).
- A catalog row copies the configured values and adds `"contract": "classifier-limits-v1"`.
  `input_contracts` is `["text"]` for an HF target and `["choice"]` for a SystemOne target; no target
  in this Unit declares both.

#### Token budgets

`classifier-limits-v1` has no token field, and no bound in C16 is a token count. The token-aware
bound is enforced inside the target, where the tokenizer is: the target refuses text whose token
count, special tokens included, exceeds its limit and never truncates it
(`classification-capabilities.md:70-72`), and that refusal reaches the Engine as a classifier failure
with a bounded code, never as a score vector. Unit 8 pins this for the BERT reference server. A
SystemOne target gets no token or length control from the Gateway, so its state and option budgets
are the server's own (Laya 0.4.21: `LAYA_MAX_TOKEN_BUDGET` and its `max_len` and `head_max_len`
defaults). Its size refusal and any reported truncation or colliding options reach the Engine as
`provider_error` (Native response, above). Jev documents no truncation report, so a Jev target relies
on `limits` the operator sets during qualification so that the largest admitted input fits its window
(`classification-capabilities.md:170-173`). If a target ever advertises token limits, they arrive as a
new `limits.contract` value: a strict C17 reader treats an unknown contract as an unusable row, so
the readers that accept it deploy before any Gateway writes it.

### Upstream attempts

The Gateway answers every non-streaming `POST /v1/chat/completions` and `POST /v1/classifications`,
success or error, with `X-AIGW-Upstream-Attempts: <n>`. Their frozen-copy replays,
`POST /v1/frozen-copies/{id}/chat/completions` and the C9 `POST /v1/frozen-copies/{id}/classifications`,
carry it too and always say `0`: a replay sends nothing upstream, whatever count the captured call had,
and the evidence stored in the copy is unchanged. A pure-ASGI middleware registered immediately
inside the outer `CallIdMiddleware` strips a whole-segment `root_path` exactly as
`middleware/body_cap.py:54-71` does, then matches those routed paths before downstream routing. It
binds one request-scoped mutable counter object at `0`; transport hooks mutate that object rather than
rebinding a `ContextVar`, so auth-disabled `BaseHTTPMiddleware` task boundaries cannot lose increments.
It injects the final value into `http.response.start`. Handled auth, body-cap, validation and
`HTTPException` responses therefore carry the header; an unhandled ServerError response outside user
middleware does not, so the Engine records `null`. Any Starlette/server request-body cap outside user
middleware stays disabled for these paths; if enabled later, its pre-user-middleware 413 is explicitly
outside the header promise and triggers a contract review.

The counter increments at physical HTTP send admission, never at `with_overload_retry` or a codec.
Chat reuses the request event hook on the app-lifetime LiteLLM accounting handler, including every
replacement client LiteLLM creates for its hidden connection-error resend. The remote-endpoint client
installs the same request-scoped observer on its shared HTTPX client and keeps transport retries at
`0`; Gateway overload retry merely causes another observed send. The status and body of every response
are unchanged; the count travels only in the header, so the scalar classification body stays byte-identical
(`apps/aigateway/tests/unit/remote_endpoint/test_app_classification.py:76` pins it).
The send observer runs before the accounting hook's `active_collector()` early return: the attempt
header is mandatory even when taxonomy/accounting collection is disabled or partial.

A LiteLLM dispatch that is not accounted sends through a second app-lifetime handler that carries
only the send observer. Both app-lifetime handlers close with the app, each in its own task: a
shutdown cancelled during a close waits for that close to end through every further cancellation,
runs every later shutdown step, then raises the cancellation, and a failed close is logged. Only
the end of the event loop itself (a second interrupt, a killed process) can stop a close; a
cancellation of the shutdown never does, so a close is never left to a task the loop's own teardown
would cancel. The shutdown drops each handler before closing it, so no request reuses a closing
pool and no pool outlives the app because its shutdown was cancelled.

Unit 5.1 inventories every non-streaming inference transport at its fresh base, installs the observer
on each one and updates this list if it differs. The current minimum is: shared and default LiteLLM
handlers, remote endpoint, local provider, OpenAI's injected HTTPX client, and the Gemini, Codex and
Antigravity HTTP clients.
No provider may serve these two routes with an unobserved inference transport. OAuth, readiness and
catalog HTTP clients are outside this request counter because they are not the chat/classification
inference send. Unit 5.1 must prove an injection seam for the generic LiteLLM path used by
HuggingFace/Ollama. Exact source for both shipped LiteLLM locks passes the dispatched `client` to their
base HTTP handler; the Unit test must prove the real Gateway wiring preserves that handler and its
hooks. If the probe fails, the Unit stops and revises C7 rather than emitting a false `0`.

| Origin | Header |
|---|---|
| Auth or dependency refusal before the handler | `0` |
| Malformed body, unknown field, `unsupported_input`, a C7 limit | `0` |
| Unknown model or provider, missing Connection, grant refusal | `0` |
| The Gateway's own admission shedding | `0` |
| Chat cache hit | `0` |
| Frozen-copy replay hit, miss or unavailable | `0` |
| Upstream answered, success or error, after `n` requests | `n` |
| Provider or codec error on an upstream response, after `n` requests | `n` |
| Transport failure on a request that may have been sent | `n`, the uncertain request included |
| A response that never reaches the middleware (an unhandled error, a dropped connection) | absent: the Engine records `null` (C8) |

`n` counts physical send admissions, not Engine requests or outer dispatch attempts. On a chat
success with complete accounting and `omitted_attempts == 0`, it equals
`sum(1 + attempt.redirect_hop_count for attempt in _aigw.accounting.attempts)`. Redirect hops are
physical sends folded into one accounting attempt. When accounting is partial or attempts were
omitted to fit the metadata bound, the body cannot independently verify the header and no mismatch is
inferred from list length alone.
Streaming chat responses are unchanged in Unit 5.1; the Engine sends no streaming call.

## C8 — Engine classification port and physical attempts (Units 5.2 and 6)

- Accepts a scalar text input or the C7 choice input; the public `GET /classify` mount and
  `client.classify(model, input)` (`client.py:543`) stay scalar and unchanged.
- Records every classifier call with `record_operation_call` (`operation_calls.py:184`) as the
  occurrence's classify operation, so the E4c budget ledger counts it. Today the port only reports
  an unpriced call (`world/classification.py:133`). An unknown cost counts as $0 for budget decisions
  with the E4c BU-9 warning and stays unknown in evidence.
- Seeds, by source. ScoringClassifier: in a seeded run the Router classify step sends no seed and
  does not refuse. LLMClassifier: its call follows the ordinary chat seed, capture, replay and cache
  contract, as the E4c selector call does. RegexClassifier: no model call. The direct `/classify` mount
  and `client.classify` keep refusing seed, capture and replay (`world/classification.py:137-143`).
- For Router-originated calls only, capture and replay replace today's refusal (C9). The Router
  binding and the attempt travel as call-key metadata (C9), never in the classification body; the
  binding is attribution-only, as `world/request_parameters.py:6-10` states for `binding`.

### Attempt facts

"Every physical attempt is recorded" and "Logical calls and physical attempts are distinct"
(`engine/router-execution.md:248`, `:367`). Unit 5.2 adds one attempt fact per bound call: the chat
and classification ports publish, for every call carrying `binding=` (a C2 `Calls` binding, or
`router_N` for a scoring classify call), after its last Engine attempt and on success and failure
alike:

```text
{"binding": str, "status": "answered" | "failed", "code": str | null,
 "engine_attempts": int ≥ 1, "upstream_attempts": int ≥ 0 | null, "possibly_billed": bool}
```

The facts go to the active recorder scopes on their own channel beside the operation-call recorders,
so `OperationCall` and every existing projection stay unchanged. JOIN (C4) reads the latest fact per
binding, as `_recorded` reads the latest call (`world/branch.py:800-808`).

| Field | Definition |
|---|---|
| `engine_attempts` | Every HTTP request the Engine sent for the logical call: the transport retry (`_TRANSPORT_RETRIES = 1`, `world/connector.py:165`, `:993-1040`) and, for Candidate chat calls, the OME-1872 answered-call retries (`world/candidate_call_retry.py`, `_post_answered`, `world/connector.py:1293-1332`). Unit 5.2 makes `_post_completion` return the count beside the possibly-billed mark it returns today |
| `upstream_attempts` | The sum of the C7 header over the Engine attempts. `null` when any Engine attempt got no response or a response without the header: unknown, never zero. `0` for a replayed or cached call (C7). On a chat success with complete accounting and no omitted attempts, disagreement with `sum(1 + redirect_hop_count)` is `null`; partial or bounded/omitted accounting supplies no independent mismatch check |
| `possibly_billed` | `true` when `upstream_attempts` is above `0`, or is `null` while the connector's existing mark (`world/connector.py:1031`) says an Engine attempt may have been sent; `false` only when every Engine attempt is known to have reached no provider |

Retries below the policy stay as on main: the Engine transport retry shared by classify and chat,
the OME-1872 retry for Candidate chat calls only (never classify), and the Gateway overload retry.
They are recorded, never added.

## C9 — Classify frozen copy and run manifest (Unit 6)

### Per-call entry

| Side | Change |
|---|---|
| Gateway store | `EntryKind` adds `"classify"` (`core/frozen_copy/store.py:42`); `kind` is `max_length=8` (`core/frozen_copy/models.py:67`), so no migration |
| Gateway digest | `canonical_digest({"kind": "classify", "request": {model, input}, "binding": b[, "attempt": a]})`; as for chat, Attempt 1 adds no `attempt` key (`core/frozen_copy/store.py:55-65`) |
| Headers | Existing `X-AIGW-Frozen-Copy`, `X-AIGW-Case-Key`, `X-AIGW-Call-Occurrence`; new `X-AIGW-Call-Binding` (`router_N`) and `X-AIGW-Call-Attempt` (an integer from 2, absent for Attempt 1), accepted only on capture and replay classify calls |
| Capture | Stores the request `{model, input}` as received, the response JSON as returned or the error status and body, and the available usage and cost (`null` today: classification has no usage accounting). Never a credential. The capture run's own attempt counts live in its stored C5, not in the entry |
| Replay | `POST /v1/frozen-copies/{id}/classifications`, sealed copy only, no plugin or credential, same caller auth and lookup as chat replay (`routes/frozen_copies.py:136-141`, `_sealed_copy` at `:94`); returns the recorded body and status with `X-AIGW-Upstream-Attempts: 0` |
| Engine lane | `Lane` adds `"classify"` (`capture_outcomes.py:24`); `digest` is the same canonical `{kind, request, binding[, attempt]}` preimage as the Gateway digest, and the occurrence key is `(case_key, "classify", digest)` |

The entry is keyed by kind, case key, Router binding, occurrence, attempt and request digest, exactly
as `engine/router-execution.md:371-378` lists. Neither the definition revision nor the policy is a
per-call field (`:383-385`). LLMClassifier and RegexClassifier evidence and every branch call replay
through their ordinary chat entries (`:371-372`); a call the copy does not hold misses as today
(`frozen_copy_miss`, `routes/frozen_copies.py:84-91`). Identical classifier requests in different
occurrences or attempts stay distinct. A replayed classification is free; an unknown captured price
stays unknown, so a budgeted Router takes the same decisions live and replayed. A captured cost, when
one exists, returns on replay as `cache.reference` through the mapping chat replay uses
(`routes/frozen_copies.py:113-133`); Unit 6 pins the classification response carrier here before code.
Today the captured cost is `null`.

Classification capture reuses chat capture's lost-reply completeness rule: the same probe marks a
possibly sent request whose reply was lost as an `ambiguous` `CaptureOutcome` in lane `classify`.
`CaptureTally` therefore reports the capture `partial`; it is not a complete pinned replay source. A
connect-phase failure that sent nothing is not ambiguous. No second attempt schedule or frozen-copy
store is introduced.

Both sides pin this classify call key before code:

```text
classify_digest = canonical_digest({
    "kind": "classify",
    "request": {"model": model, "input": input},
    "binding": binding,
    ["attempt": attempt] when attempt >= 2
})
occurrence = tally.next_occurrence(case_key, "classify", classify_digest)
```

The Engine never uses chat's body-only digest for lane `classify`; sibling Router bindings therefore
cannot share an occurrence stream when their classifier bodies are equal.

### Run manifest

"Replay validates the Router definition revision once at the run boundary"
(`engine/router-execution.md:383`).

- **Run definition set.** Before `url4_run`, in every run, the executor resolves each
  `router-spec.v1` intent of the run's url4 expression into its definition `D`: an inline `D` from
  the intent, a prepared `D` through the Router-input reader (C14), which reads, verifies and decodes
  the source once. It recomputes each revision from that `D` (C3) and binds the frozen set
  `{router_N: (revision, D)}` for the run, as `run_expression_scope` binds the run's own expression
  (`benchmarks/picture_admission.py:147`, entered at `runner/executor.py:1174`). This is the "read,
  verify and freeze" step of `engine/routing-inputs.md:35`, done once per run: ADMIT takes a prepared
  `D` from the set and never reads the source, so a source changed after the run starts cannot reach
  it. The step refuses the run before `url4_run`, with no Router record, when a prepared source cannot
  be read, verified or decoded (the reader's C14 code), when one `router` binding occurs twice, or
  when more than 256 Routers occur (C16); the last two are `router_definition_invalid`. It makes no
  other check: C2 validation and the metadata preflight stay per occurrence at ADMIT (C4), and a live
  run still claims no whole-plan sibling-spend guarantee (`engine/router-execution.md:167-170`).
- **Manifest.** The sorted projection `[{"binding": "router_N", "revision": "sha256:<64 hex>"}]` of
  the run definition set. Each revision is recomputed from the `D` the run will use, never copied
  from the declared `revision`, so a prepared source that changed since capture gives a different
  manifest even when the expression still declares the captured revision. The same function runs at
  capture and at replay.
- **Capture.** `seal_frozen_copy` (`world/connector.py:697-713`) sends
  `{"provenance": {"engine_version": v, "routers": <manifest>}}`; `routers` only when the manifest is
  non-empty.
- **Gateway reader, deployed first.** `Provenance` (`routes/frozen_copies.py:56-61`, `extra="forbid"`)
  gains optional `routers`: 1-256 strict `{binding, revision}` entries, `binding` matching
  `router_[0-9]+`, `revision` matching `sha256:[0-9a-f]{64}`. `FrozenCopyStore.seal` widens its
  `provenance` type from `dict[str, str]` (`core/frozen_copy/store.py:119-142`); the column is a JSON
  field, so no migration (`core/frozen_copy/models.py:42-43`). A new read route
  `GET /v1/frozen-copies/{copy_id}/provenance` returns `{"engine_version": str | null, "routers": [...]}`
  (`[]` when the seal sent none), for a sealed copy only through `_sealed_copy`, with the chat replay
  route's caller auth. The route publishes that strict response schema as a closed record
  (`extra="forbid"`, `additionalProperties: false`, as for its entries) and reads the stored row
  field by field with the seal's own types: a stored value the seal would refuse today, from an
  older writer or a damaged row, reads `null` for `engine_version` and `[]` for `routers`, never a
  500 and never the stored JSON itself. An invalid stored manifest therefore reads as a copy sealed
  without `routers`, which the Check below refuses. An old Gateway rejects a seal with `routers`, so
  the writer waits for the reader (C12).
- **Check.** In a replay run with a non-empty manifest, the executor reads that provenance after
  resolving the run definition set and before `url4_run`, beside the capture branch of
  `_evaluate_in_copy` (`runner/executor.py:1138-1160`), and compares the lists exactly. Unequal
  lists, or a copy sealed without `routers`, fail the run `frozen_copy_miss` before any replayed or
  live operation; an unknown or open copy fails `frozen_copy_unavailable`. Both are
  existing Engine codes (`error_text.py:64`). A replay run with an empty manifest sends no extra
  request and behaves as today.

Because the manifest covers every Router in the expression and is computed from the definitions the
run will use, changing any Router's definition, inline or prepared, for every source, policy,
default and quorum, is refused once at the boundary, and no call needs a revision field. Replay is
an execution, so a prepared source must still be readable then; an expired one fails the replay
before `url4_run` (`engine/routing-inputs.md:79`). Gateway and Engine readers deploy before any
writer; chat and tool copies keep their behavior.
